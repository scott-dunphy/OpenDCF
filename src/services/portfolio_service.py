"""
Portfolio service: assumption resolution, portfolio runs and scenario rollups.

A portfolio run values every property in the portfolio under the base case
(property model + resolved assumption profiles) and under each selected
scenario (base + scenario overrides). Stored property data is never modified.
"""

from __future__ import annotations

import json
from calendar import monthrange
from copy import copy
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.engine.assumption_overrides import (
    OverrideTargets,
    ResolvedAssumptions,
    ScopedValues,
    apply_assumptions,
    apply_storage_assumptions,
    resolve,
)
from src.models.portfolio import AssumptionProfile, Portfolio, PortfolioRun, PortfolioScenario
from src.models.portfolio import portfolio_properties
from src.models.property import Property
from src.models.valuation import Valuation
from src.schemas.common import ValuationStatus
from src.schemas.portfolio import (
    AssumptionValues,
    GroupRollup,
    PortfolioRunRead,
    PropertyRunResult,
    ScenarioOverride,
    ScenarioResult,
)
from src.services.valuation_service import ValuationService
from src.engine.dcf import xirr_details

# Property types valued by their own engines; portfolio runs use stored results.
_STANDALONE_TYPES = {"marina", "seniors_housing"}


def values_to_dict(values: AssumptionValues) -> dict[str, Decimal]:
    return {k: v for k, v in values.model_dump().items() if v is not None}


def property_scope(prop: Property) -> dict:
    """Keyword arguments that let resolve() match a property's CBSA, state and quality."""
    from src.services.cbsa import state_code

    return {"cbsa_code": prop.cbsa_code, "state": state_code(prop.state), "quality_score": prop.quality_score,
            "area_unit": prop.area_unit}


async def library_directions(db: AsyncSession) -> dict[str, str]:
    """Quality directions: defaults overlaid with the house settings."""
    from src.engine.assumption_overrides import default_directions
    from src.models.portfolio import AssumptionSettings

    settings = await db.get(AssumptionSettings, 1)
    return {**default_directions(), **json.loads(settings.directions_json if settings else "{}")}


def profile_layer(p: AssumptionProfile) -> ScopedValues:
    return ScopedValues(
        cbsa_code=p.cbsa_code,
        state=p.state,
        quality_score=p.quality_score,
        ranges={
            k: (Decimal(str(r["low"])), Decimal(str(r["high"])))
            for k, r in json.loads(p.ranges_json or "{}").items()
        },
        values={
            k: Decimal(str(v))
            for k, v in json.loads(p.values_json or "{}").items()
            if v is not None
        },
        portfolio_id=p.portfolio_id,
        property_type=p.property_type,
        market=p.market,
        mode="set",
        source=f"profile:{p.name}",
    )


def scenario_layers(s: PortfolioScenario) -> list[ScopedValues]:
    layers = []
    for raw in json.loads(s.overrides_json or "[]"):
        o = ScenarioOverride.model_validate(raw)
        layers.append(
            ScopedValues(
                values=values_to_dict(o.values),
                property_type=o.property_type.value if o.property_type else None,
                market=o.market,
                mode=o.mode,
                source=f"scenario:{s.name}",
            )
        )
    return layers


def _default_valuation(property_id: str) -> Valuation:
    """Transient valuation used when a property has no saved valuation."""
    return Valuation(
        property_id=property_id,
        name="Portfolio default",
        discount_rate=None,
        exit_cap_rate=None,
        exit_cap_applied_to_year=-1,
        exit_costs_pct=Decimal("0.02"),
        transfer_tax_preset="none",
        apply_stabilized_gross_up=True,
        capital_reserves_per_unit=Decimal("0.25"),
        use_mid_year_convention=False,
        io_period_months=0,
        loan_fees_pct=Decimal(0),
        acquisition_costs_pct=Decimal(0),
        exit_deduct_forward_capital=False,
    )


def _safe_ratio(num: Decimal, den: Decimal) -> Decimal | None:
    return num / den if den else None


def _month_end(value: date) -> date:
    return value.replace(day=monthrange(value.year, value.month)[1])


def _ownership_on(row: PropertyRunResult, value_date: date) -> Decimal:
    """Ownership applicable on a dated cash flow, including acquisition/disposition bounds."""
    if row.ownership_effective_from and value_date < row.ownership_effective_from:
        return Decimal(0)
    if row.ownership_effective_to and value_date > row.ownership_effective_to:
        return Decimal(0)
    return row.ownership_pct


def _terminal_proceeds(row: PropertyRunResult, terminal_date: date) -> tuple[date, Decimal]:
    """Dated ownership-share sale proceeds. When the interest ends before the modeled exit,
    the share is sold at its effective_to date for the forecast quarterly value, net of
    the same exit-cost haircut as the modeled terminal value."""
    terminal = row.terminal_value or Decimal(0)
    sale_date = row.ownership_effective_to
    if sale_date is None or sale_date >= terminal_date:
        return terminal_date, terminal * _ownership_on(row, terminal_date)
    if sale_date < (row.ownership_effective_from or sale_date):
        return sale_date, Decimal(0)
    values = row.quarterly_market_value
    if not values:
        return sale_date, terminal * row.ownership_pct
    target = f"{sale_date.year} Q{(sale_date.month - 1) // 3 + 1}"
    keys = list(values)
    gross_at_sale = values[next((key for key in keys if key >= target), keys[-1])]
    gross_at_exit = values[keys[-1]]
    net_ratio = terminal / gross_at_exit if gross_at_exit else Decimal(1)
    return sale_date, gross_at_sale * net_ratio * row.ownership_pct


class PortfolioService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.valuations = ValuationService(db)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    async def load_portfolio(self, portfolio_id: str) -> Portfolio | None:
        result = await self.db.execute(
            select(Portfolio)
            .where(Portfolio.id == portfolio_id)
            .options(selectinload(Portfolio.properties), selectinload(Portfolio.scenarios))
        )
        return result.scalar_one_or_none()

    async def profile_layers(self, portfolio_id: str | None) -> list[ScopedValues]:
        stmt = select(AssumptionProfile).where(
            (AssumptionProfile.portfolio_id.is_(None))
            | (AssumptionProfile.portfolio_id == portfolio_id)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [profile_layer(p) for p in rows]

    async def _latest_valuation(self, property_id: str) -> Valuation | None:
        result = await self.db.execute(
            select(Valuation)
            .where(Valuation.property_id == property_id)
            .order_by((Valuation.review_status == "draft").desc(), Valuation.updated_at.desc(),
                      Valuation.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def resolve_for_property(
        self, prop: Property, portfolio_id: str | None
    ) -> ResolvedAssumptions:
        layers = await self.profile_layers(portfolio_id)
        return resolve(layers, portfolio_id, prop.property_type, prop.market, **property_scope(prop),
                       directions=await library_directions(self.db))

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------

    async def approved_snapshots(self, property_ids: list[str]) -> dict[str, list[tuple]]:
        """Per property: (valuation, snapshot) for every snapshot ever approved, including ones
        reopened since, so an earlier quarter can still be reproduced."""
        from sqlalchemy.orm import defer

        from src.models.valuation import ValuationSnapshot

        if not property_ids:
            return {}
        rows = (await self.db.execute(
            select(Valuation, ValuationSnapshot)
            .join(ValuationSnapshot, ValuationSnapshot.valuation_id == Valuation.id)
            .where(Valuation.property_id.in_(property_ids), ValuationSnapshot.approved_at.is_not(None))
            .options(
                defer(ValuationSnapshot.inputs_json), defer(ValuationSnapshot.results_json),
                defer(ValuationSnapshot.recovery_audit_json), defer(Valuation.result_tenant_cash_flows_json),
                defer(Valuation.result_recovery_audit_json),
            )
        )).all()
        out: dict[str, list] = {}
        for valuation, snapshot in rows:
            out.setdefault(valuation.property_id, []).append((valuation, snapshot))
        return out

    async def _approved_as_of(self, properties: list[Property], as_of: date) -> dict[str, dict]:
        """Per property: the latest snapshot approved with a date of value on or before `as_of`,
        the property as frozen, its engine inputs (rebuilt once, reused by every case), the
        difference between the approved value and today's engine on those inputs, and any notes."""
        from src.models.valuation import ValuationSnapshot
        from src.services.valuation_snapshot import frozen_property, restored

        approved = await self.approved_snapshots([p.id for p in properties])
        out: dict[str, dict] = {}
        for prop in properties:
            eligible = [(v, s) for v, s in approved.get(prop.id, []) if s.value_date <= as_of]
            if not eligible:
                continue
            latest_date = max(s.value_date for _, s in eligible)
            same_date = [(v, s) for v, s in eligible if s.value_date == latest_date]
            valuation, snapshot = max(same_date, key=lambda vs: vs[1].approved_at)
            snapshot_inputs = json.loads((await self.db.execute(
                select(ValuationSnapshot.inputs_json).where(ValuationSnapshot.id == snapshot.id)
            )).scalar_one())
            frozen_prop = frozen_property(snapshot_inputs)
            frozen_id = frozen_prop.id
            frozen_prop.id = prop.id  # a property merged into this one froze under its old id
            entry = {"valuation": valuation, "snapshot": snapshot, "property": frozen_prop,
                     "inputs": None, "drift": Decimal(0), "warnings": []}
            if len(same_date) > 1:
                entry["warnings"].append(
                    f"{len(same_date)} approvals for {latest_date.isoformat()}; used the one on "
                    f"'{valuation.name}' approved most recently"
                )
            if snapshot.status == "reopened":
                entry["warnings"].append(
                    f"This approval was reopened on {snapshot.reopened_at:%Y-%m-%d}: {snapshot.reopen_reason}"
                )
            if entry["property"].property_type not in _STANDALONE_TYPES:
                async with restored(snapshot_inputs) as session:
                    frozen = ValuationService(session)
                    entry["inputs"] = await frozen.build_engine_inputs(
                        await session.get(Valuation, valuation.id), await session.get(Property, frozen_id)
                    )
                # Every case is shifted by this, so the base is the approved value and scenario
                # changes measure only the scenario, not engine changes since approval
                rerun = copy(entry["inputs"]).run().npv
                if snapshot.result_npv is not None:
                    entry["drift"] = snapshot.result_npv - rerun
                    if rerun.quantize(Decimal("0.01")) != snapshot.result_npv:
                        entry["warnings"].append(
                            f"Today's engine values the approved inputs at {rerun:,.0f}, not the approved "
                            f"{snapshot.result_npv:,.0f}; every case is adjusted by the difference"
                        )
            out[prop.id] = entry
        return out

    async def _value_property(
        self,
        prop: Property,
        resolved: ResolvedAssumptions,
        ownership_pct: Decimal | None = None,
        interest: dict | None = None,
        as_of: date | None = None,
        approved: dict | None = None,
    ) -> PropertyRunResult:
        own = (
            ownership_pct
            if ownership_pct is not None
            else (prop.ownership_pct if prop.ownership_pct is not None else Decimal(1))
        )
        row = PropertyRunResult(
            property_id=prop.id,
            property_name=prop.name,
            property_type=prop.property_type,
            market=prop.market,
            ownership_pct=own,
            ownership_effective_from=interest.get("effective_from") if interest else None,
            ownership_effective_to=interest.get("effective_to") if interest else None,
            acquisition_cost=interest.get("acquisition_cost") if interest else None,
            commitment=interest.get("commitment") if interest else None,
            currency=interest.get("currency", "USD") if interest else "USD",
            resolved_assumptions={k: v for k, v in resolved.values.items()},
        )
        if as_of is not None:
            if approved is None:
                row.error = f"No approved valuation as of {as_of.isoformat()}"
                return row
            if _ownership_on(row, as_of) == 0:
                row.error = f"Not owned on {as_of.isoformat()}"
                return row
            valuation = approved["valuation"]
            row.valuation_id, row.valuation_name = valuation.id, valuation.name
            row.value_date = approved["snapshot"].value_date
            row.warnings.extend(approved["warnings"])
        else:
            valuation = await self._latest_valuation(prop.id)

        if prop.property_type in _STANDALONE_TYPES and approved is not None:
            row.rerun = False
            row.value = approved["snapshot"].result_npv
            if valuation.snapshot_id == approved["snapshot"].id:  # stored results are this approval's
                row.going_in_cap_rate = valuation.result_going_in_cap_rate
                row.irr = valuation.result_irr
                row.levered_irr = valuation.result_levered_irr
                row.terminal_value = valuation.result_exit_value
        elif prop.property_type in _STANDALONE_TYPES:
            row.rerun = False
            if valuation is None or valuation.status != ValuationStatus.COMPLETED.value:
                row.error = "No completed valuation for this property type"
                return row
            row.value = valuation.result_npv
            row.going_in_cap_rate = valuation.result_going_in_cap_rate
            row.irr = valuation.result_irr
            row.levered_irr = valuation.result_levered_irr
            row.terminal_value = valuation.result_exit_value
            cfs = json.loads(valuation.result_cash_flows_json or "[]")
            if cfs:
                row.year1_noi = Decimal(str(cfs[0]["net_operating_income"]))
        else:
            try:
                if approved is not None:
                    inputs = copy(approved["inputs"])  # each case on its own copy of the frozen inputs
                else:
                    inputs = await self.valuations.build_engine_inputs(
                        valuation or _default_valuation(prop.id), prop
                    )
                    if valuation is None:
                        row.warnings.append(
                            "No valuation, so no market leasing assumptions: vacant and expiring space is not re-leased"
                        )
                    elif valuation.review_status != "draft":
                        row.warnings.append(
                            f"'{valuation.name}' is frozen and there is no draft: its assumptions are run on "
                            "the property's current inputs, which can differ from the reviewed value"
                        )
                targets = apply_assumptions(
                    OverrideTargets(
                        params=inputs.params,
                        market=inputs.market,
                        expenses=inputs.expenses,
                        other_income=inputs.other_income,
                        cpi_assumption=inputs.cpi_assumption,
                        cpi_schedule=inputs.cpi_schedule,
                    ),
                    resolved,
                )
                if not targets.params.discount_rate or not targets.params.exit_cap_rate:
                    row.error = (
                        "No discount rate / exit cap: add a valuation or an assumption profile"
                    )
                    return row
                inputs.params = targets.params
                inputs.market = targets.market
                inputs.expenses = targets.expenses
                inputs.other_income = targets.other_income
                inputs.cpi_assumption = targets.cpi_assumption
                inputs.cpi_schedule = targets.cpi_schedule
                if getattr(inputs, "storage_model", None) is not None:
                    inputs.storage_model, ignored = apply_storage_assumptions(inputs.storage_model, resolved)
                    if ignored:
                        row.warnings.append(
                            "Not applied to this self storage unit mix: " + ", ".join(ignored)
                        )
                result = inputs.run(include_monthly=True)
            except Exception as exc:  # one bad property must not sink the portfolio
                row.error = str(exc)
                return row

            row.value = result.npv
            if approved is not None:
                row.value = (result.npv + approved["drift"]).quantize(Decimal("0.01"))
            row.irr = result.irr
            row.going_in_cap_rate = result.going_in_cap_rate
            row.levered_irr = result.returns.levered_irr if result.returns else None
            row.terminal_value = result.terminal_value
            row.direct_cap_value = result.direct_cap_value
            cfs = result.annual_cash_flows
            if cfs:
                row.year1_noi = cfs[0].net_operating_income
            # By calendar year from the monthly cash flows, so properties with different
            # fiscal years or start months add up over the same twelve months
            for cf in result.monthly_cash_flows:
                y = cf.period_start.year
                key = cf.period_start.isoformat()
                row.annual_noi[y] = row.annual_noi.get(y, Decimal(0)) + cf.net_operating_income
                row.annual_cfbd[y] = row.annual_cfbd.get(y, Decimal(0)) + cf.cash_flow_before_debt
                row.monthly_noi[key] = cf.net_operating_income
                row.monthly_cfbd[key] = cf.cash_flow_before_debt
                row.monthly_capital[key] = (
                    cf.tenant_improvements
                    + cf.leasing_commissions
                    + cf.capital_reserves
                    + cf.building_improvements
                )
                row.monthly_debt_service[key] = cf.debt_service
            monthly = result.monthly_cash_flows
            for position, cf in enumerate(monthly):
                is_quarter_end = cf.period_start.month in {3, 6, 9, 12}
                if not is_quarter_end and position != len(monthly) - 1:
                    continue
                forward = monthly[position + 1 : position + 13]
                if len(forward) < 12:
                    forward = monthly[max(0, position - 11) : position + 1]
                forward_noi = sum((item.net_operating_income for item in forward), Decimal(0))
                if forward and len(forward) < 12:
                    forward_noi = forward_noi * Decimal(12) / Decimal(len(forward))
                period = f"{cf.period_start.year} Q{(cf.period_start.month - 1) // 3 + 1}"
                row.quarterly_market_value[period] = forward_noi / targets.params.exit_cap_rate
            if row.quarterly_market_value:
                row.quarterly_market_value[list(row.quarterly_market_value)[-1]] = (
                    result.terminal_gross_value
                )

        # Ownership on the run's as-of date, else on the property's analysis start
        held_on = as_of or prop.analysis_start_date
        if row.value is not None:
            row.share_value = row.value * _ownership_on(row, held_on)
        if row.year1_noi is not None:
            row.share_year1_noi = row.year1_noi * _ownership_on(row, held_on)
        return row

    @staticmethod
    def _group(rows: list[PropertyRunResult], key_fn) -> list[GroupRollup]:
        groups: dict[str, list[PropertyRunResult]] = defaultdict(list)
        for r in rows:
            if r.share_value is not None:
                groups[key_fn(r)].append(r)
        out = []
        for key in sorted(groups):
            members = groups[key]
            value = sum((r.share_value for r in members), Decimal(0))
            noi = sum((r.share_year1_noi or Decimal(0) for r in members), Decimal(0))
            irr_rows = [r for r in members if r.irr is not None]
            irr_value = sum((r.share_value for r in irr_rows), Decimal(0))
            out.append(
                GroupRollup(
                    key=key,
                    property_count=len(members),
                    share_value=value,
                    share_year1_noi=noi,
                    implied_cap_rate=_safe_ratio(noi, value),
                    value_weighted_irr=(
                        _safe_ratio(
                            sum((r.irr * r.share_value for r in irr_rows), Decimal(0)), irr_value
                        )
                        if irr_rows
                        else None
                    ),
                )
            )
        return out

    def _rollup(
        self,
        scenario_id: str | None,
        name: str,
        rows: list[PropertyRunResult],
        probability_pct: Decimal | None = None,
    ) -> ScenarioResult:
        ok = [r for r in rows if r.share_value is not None]
        total = sum((r.value for r in ok), Decimal(0))
        share = sum((r.share_value for r in ok), Decimal(0))
        noi = sum((r.share_year1_noi or Decimal(0) for r in ok), Decimal(0))
        irr_rows = [r for r in ok if r.irr is not None]
        irr_value = sum((r.share_value for r in irr_rows), Decimal(0))

        annual_noi: dict[int, Decimal] = defaultdict(Decimal)
        annual_cfbd: dict[int, Decimal] = defaultdict(Decimal)
        monthly_noi: dict[str, Decimal] = defaultdict(Decimal)
        monthly_cfbd: dict[str, Decimal] = defaultdict(Decimal)
        monthly_capital: dict[str, Decimal] = defaultdict(Decimal)
        monthly_debt: dict[str, Decimal] = defaultdict(Decimal)
        for r in ok:
            if not r.monthly_noi:
                for y, v in r.annual_noi.items():
                    annual_noi[y] += v * _ownership_on(r, date(y, 12, 31))
                for y, v in r.annual_cfbd.items():
                    annual_cfbd[y] += v * _ownership_on(r, date(y, 12, 31))
            for key, value in r.monthly_noi.items():
                cash_date = _month_end(date.fromisoformat(key))
                share_amount = value * _ownership_on(r, cash_date)
                monthly_noi[key] += share_amount
                annual_noi[cash_date.year] += share_amount
            for key, value in r.monthly_cfbd.items():
                cash_date = _month_end(date.fromisoformat(key))
                share_amount = value * _ownership_on(r, cash_date)
                monthly_cfbd[key] += share_amount
                annual_cfbd[cash_date.year] += share_amount
            for key, value in r.monthly_capital.items():
                monthly_capital[key] += value * _ownership_on(r, _month_end(date.fromisoformat(key)))
            for key, value in r.monthly_debt_service.items():
                monthly_debt[key] += value * _ownership_on(r, _month_end(date.fromisoformat(key)))

        dated_cash_flows: dict[date, Decimal] = defaultdict(Decimal)
        for row in ok:
            if not row.monthly_cfbd:
                continue
            dates = sorted(date.fromisoformat(key) for key in row.monthly_cfbd)
            investment_date = row.ownership_effective_from or dates[0]
            initial_investment = (
                row.acquisition_cost
                if row.acquisition_cost is not None
                else (row.share_value or Decimal(0))
            )
            dated_cash_flows[investment_date] -= initial_investment
            for key, value in row.monthly_cfbd.items():
                cash_date = _month_end(date.fromisoformat(key))
                dated_cash_flows[cash_date] += value * _ownership_on(row, cash_date)
            sale_date, proceeds = _terminal_proceeds(row, _month_end(dates[-1]))
            dated_cash_flows[sale_date] += proceeds
        ordered_dates = sorted(dated_cash_flows)
        xirr = (
            xirr_details([dated_cash_flows[item] for item in ordered_dates], ordered_dates)
            if ordered_dates
            else None
        )
        running = Decimal(0)
        minimum = Decimal(0)
        for key in sorted(monthly_cfbd):
            running += monthly_cfbd[key]
            minimum = min(minimum, running)
        weights = (
            [row.share_value / share for row in ok if row.share_value is not None] if share else []
        )
        hhi = sum((weight * weight for weight in weights), Decimal(0)) if weights else None
        risk_alerts = []
        if weights and max(weights) > Decimal("0.25"):
            risk_alerts.append("Largest property exceeds 25% of ownership-share value.")
        for label, key_fn, limit in (
            ("property type", lambda item: item.property_type, Decimal("0.60")),
            ("market", lambda item: item.market or "(none)", Decimal("0.65")),
        ):
            exposure: dict[str, Decimal] = defaultdict(Decimal)
            for row in ok:
                exposure[key_fn(row)] += row.share_value or Decimal(0)
            for key, value in exposure.items():
                if share and value / share > limit:
                    risk_alerts.append(
                        f"{label.title()} concentration in {key} is {(value / share):.1%}, "
                        f"above the {limit:.0%} reference threshold."
                    )
        quarter_values: dict[str, Decimal] = defaultdict(Decimal)
        for row in ok:
            for period, value in row.quarterly_market_value.items():
                quarter_values[period] += value * row.ownership_pct
        quarterly_returns: dict[str, Decimal] = {}
        linked_return = Decimal(1)
        # Same basis as quarter_values: only rows with a quarterly forecast, at ownership_pct
        beginning_value = sum(
            (row.value * row.ownership_pct for row in ok if row.quarterly_market_value and row.value is not None),
            Decimal(0),
        )
        for period in sorted(quarter_values):
            year_text, quarter_text = period.split(" Q")
            year, quarter = int(year_text), int(quarter_text)
            months = {quarter * 3 - 2, quarter * 3 - 1, quarter * 3}
            period_noi = sum(
                (
                    value
                    for key, value in monthly_noi.items()
                    if date.fromisoformat(key).year == year
                    and date.fromisoformat(key).month in months
                ),
                Decimal(0),
            )
            period_capital = -sum(
                (
                    value
                    for key, value in monthly_capital.items()
                    if date.fromisoformat(key).year == year
                    and date.fromisoformat(key).month in months
                ),
                Decimal(0),
            )
            denominator = beginning_value + period_capital / Decimal(2) - period_noi / Decimal(3)
            if denominator > 0:
                total_return = (
                    period_noi + quarter_values[period] - beginning_value - period_capital
                ) / denominator
                quarterly_returns[period] = total_return
                linked_return *= Decimal(1) + total_return
            beginning_value = quarter_values[period]

        return ScenarioResult(
            scenario_id=scenario_id,
            scenario_name=name,
            excluded_count=len(rows) - len(ok),
            probability_pct=probability_pct,
            total_value=total,
            total_share_value=share,
            total_share_year1_noi=noi,
            implied_cap_rate=_safe_ratio(noi, share),
            value_weighted_irr=(
                _safe_ratio(sum((r.irr * r.share_value for r in irr_rows), Decimal(0)), irr_value)
                if irr_rows
                else None
            ),
            portfolio_xirr=xirr.rate if xirr else None,
            portfolio_xirr_status=xirr.status if xirr else "not_calculated",
            minimum_cumulative_cash=minimum,
            required_liquidity=-minimum,
            concentration_hhi=hhi,
            largest_property_pct=max(weights) if weights else None,
            portfolio_time_weighted_return=(
                linked_return - Decimal(1) if quarterly_returns else None
            ),
            quarterly_time_weighted_returns=quarterly_returns,
            risk_alerts=risk_alerts,
            by_property_type=self._group(ok, lambda r: r.property_type),
            by_market=self._group(ok, lambda r: r.market or "(none)"),
            by_type_and_market=self._group(
                ok, lambda r: f"{r.property_type} | {r.market or '(none)'}"
            ),
            share_annual_noi=dict(sorted(annual_noi.items())),
            share_annual_cfbd=dict(sorted(annual_cfbd.items())),
            share_monthly_cash_flow=dict(sorted(monthly_cfbd.items())),
            share_monthly_noi=dict(sorted(monthly_noi.items())),
            share_monthly_capital=dict(sorted(monthly_capital.items())),
            share_monthly_debt_service=dict(sorted(monthly_debt.items())),
            properties=rows,
        )

    async def run(
        self,
        portfolio: Portfolio,
        scenario_ids: list[str],
        include_base: bool = True,
        name: str | None = None,
        as_of: date | None = None,
    ) -> PortfolioRun:
        scenarios_by_id = {s.id: s for s in portfolio.scenarios}
        missing = [sid for sid in scenario_ids if sid not in scenarios_by_id]
        if missing:
            raise ValueError(f"Scenario(s) not in portfolio: {', '.join(missing)}")

        layers = await self.profile_layers(portfolio.id)
        directions = await library_directions(self.db)
        interest_rows = (
            (
                await self.db.execute(
                    select(portfolio_properties).where(
                        portfolio_properties.c.portfolio_id == portfolio.id
                    )
                )
            )
            .mappings()
            .all()
        )
        interests = {row["property_id"]: row for row in interest_rows}
        approved: dict[str, dict] = {}
        if as_of is not None:
            # Approved values are used as reviewed: no library layers, only scenario overrides
            layers = []
            approved = await self._approved_as_of(list(portfolio.properties), as_of)
        # As-of runs describe each property as it was frozen (type, market, quality)
        subjects = [approved[p.id]["property"] if p.id in approved else p for p in portfolio.properties]
        base_resolved = {
            p.id: resolve(layers, portfolio.id, p.property_type, p.market, **property_scope(p), directions=directions)
            for p in subjects
        }

        results: list[ScenarioResult] = []
        cases: list[tuple[str | None, str, list[ScopedValues], Decimal | None]] = []
        if include_base:
            cases.append((None, "Base", [], None))
        for sid in scenario_ids:
            s = scenarios_by_id[sid]
            probability = Decimal(str(s.probability_pct)) if s.probability_pct is not None else None
            cases.append((s.id, s.name, scenario_layers(s), probability))

        probabilities = [item[3] for item in cases if item[0] is not None and item[3] is not None]
        probability_total = sum(probabilities, Decimal(0))
        if probability_total > Decimal(1):
            raise ValueError("Selected scenario probabilities may not exceed 1.0")
        if probabilities and include_base:
            # The unsassigned probability is explicitly the base case, rather than silently
            # renormalizing only the selected downside/upside cases.
            cases[0] = (None, "Base", [], Decimal(1) - probability_total)
        elif probabilities and probability_total != Decimal(1):
            raise ValueError(
                "Selected scenario probabilities must total 1.0 when the base case is excluded"
            )

        for scenario_id, scenario_name, extra, probability in cases:
            rows = []
            for prop in subjects:
                resolved = base_resolved[prop.id]
                if extra:
                    resolved = resolve(
                        extra, portfolio.id, prop.property_type, prop.market, base=resolved,
                        **property_scope(prop), directions=directions,
                    )
                interest = interests.get(prop.id)
                own = None
                if interest is not None:
                    own = Decimal(str(interest["ownership_pct"]))
                rows.append(await self._value_property(
                    prop, resolved, own, dict(interest) if interest else None,
                    as_of=as_of, approved=approved.get(prop.id),
                ))
            results.append(self._rollup(scenario_id, scenario_name, rows, probability))

        base = next((r for r in results if r.scenario_id is None), None)
        if base is not None and base.total_share_value:
            base_values = {
                item.property_id: item.share_value or Decimal(0) for item in base.properties
            }
            for r in results:
                r.change_vs_base_pct = r.total_share_value / base.total_share_value - Decimal(1)
                r.property_value_attribution = {
                    item.property_id: (item.share_value or Decimal(0))
                    - base_values.get(item.property_id, Decimal(0))
                    for item in r.properties
                }

        run = PortfolioRun(
            portfolio_id=portfolio.id,
            name=name,
            as_of=as_of,
            results_json=json.dumps([r.model_dump(mode="json") for r in results]),
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    @staticmethod
    def run_to_read(run: PortfolioRun) -> PortfolioRunRead:
        scenarios = [ScenarioResult.model_validate(r) for r in json.loads(run.results_json or "[]")]
        weighted = [item for item in scenarios if item.probability_pct is not None]
        probability_sum = sum((item.probability_pct for item in weighted), Decimal(0))
        if weighted and probability_sum != Decimal(1):
            raise ValueError("Stored scenario probabilities do not total 1.0")
        return PortfolioRunRead(
            id=run.id,
            portfolio_id=run.portfolio_id,
            name=run.name,
            as_of=run.as_of,
            created_at=run.created_at,
            scenarios=scenarios,
            probability_weighted_value=(
                sum(
                    (item.total_share_value * item.probability_pct for item in weighted), Decimal(0)
                )
                / probability_sum
                if probability_sum
                else None
            ),
            probability_weighted_year1_noi=(
                sum(
                    (item.total_share_year1_noi * item.probability_pct for item in weighted),
                    Decimal(0),
                )
                / probability_sum
                if probability_sum
                else None
            ),
        )
