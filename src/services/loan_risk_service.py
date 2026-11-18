"""
Loan book risk runs: build each collateral's NOI path and current value at the
as-of date, roll each loan's contractual schedule forward from origination,
run the Monte Carlo engine and summarize PD / LGD / EL, ratings, fair value
and LTV by loan and by rating bucket.
"""
from __future__ import annotations

import asyncio
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.engine.date_utils import add_months, start_of_month
from src.engine.loan_risk.params import (
    CALIBRATED_KEYS,
    CMM_WIDE_PRESET,
    CMM_WIDE_PRESET_NAME,
    RiskParameters,
)
from src.engine.loan_risk.ratings import (
    MOODYS_RATINGS,
    NAIC_CM_FACTORS,
    WORST_RATING,
    moodys_rating,
    naic_cm_category,
    naic_dsc,
    naic_ltv,
)
from src.engine.loan_risk.schedule import (
    LoanState,
    LoanTerms,
    ScheduleRow,
    project_schedule,
    roll_forward,
    weighted_average_life_years,
)
from src.engine.loan_risk.simulation import (
    CollateralInput,
    LoanRiskResult,
    loan_input_from_schedule,
    simulate,
)
from src.models.audit import RiskParameterSetVersion
from src.models.loan import LoanRiskRun, MortgageLoan, RiskParameterSet
from src.models.portfolio import portfolio_properties
from src.models.property import Property, Suite
from src.models.valuation import Valuation
from src.services.audit import jsonable, row_dict
from src.services.collateral_simulation_service import CollateralSimulationService

MODEL_UNSUPPORTED_TYPES = {"marina", "seniors_housing"}
DEFAULT_TAPE_NOI_GROWTH = Decimal("0.02")


def projection_start(as_of: date) -> date:
    """Month 1 of the projection: the as-of month when it starts on the 1st, else the next month."""
    return as_of if as_of.day == 1 else add_months(start_of_month(as_of), 1)


def loan_terms(loan: MortgageLoan) -> LoanTerms:
    return LoanTerms(
        origination_date=loan.origination_date,
        original_balance=loan.original_balance,
        maturity_date=loan.maturity_date,
        rate_type=loan.rate_type,
        coupon=loan.coupon,
        spread=loan.spread,
        index_floor=loan.index_floor,
        index_cap=loan.index_cap,
        amortization_months=loan.amortization_months,
        io_months=loan.io_months or 0,
    )


@dataclass
class LoanPosition:
    """A loan's contractual position at the as-of date."""
    loan: MortgageLoan
    terms: LoanTerms
    state: LoanState
    balance: Decimal
    scheduled_balance: Decimal
    balance_difference_pct: Decimal
    rate: Decimal
    rows: list[ScheduleRow]
    warnings: list[str] = field(default_factory=list)

    @property
    def next_12_debt_service(self) -> Decimal:
        return sum((r.interest + r.principal for r in self.rows[:12]), Decimal(0))


def loan_position(loan: MortgageLoan, as_of: date, index_rate: Decimal) -> LoanPosition:
    terms = loan_terms(loan)
    warnings: list[str] = []
    reported = loan.reported_balance
    if reported is not None and loan.balance_as_of_date and loan.balance_as_of_date != as_of:
        # Carry the tape's difference from schedule (curtailments, modifications) to the as-of date
        at_report = roll_forward(terms, loan.balance_as_of_date, index_rate)
        reported = roll_forward(terms, as_of, index_rate).scheduled_balance + (reported - at_report.scheduled_balance)
    state = roll_forward(terms, as_of, index_rate, reported)
    if abs(state.balance_difference_pct) > Decimal("0.005"):
        warnings.append(
            f"Reported balance differs from schedule by {float(state.balance_difference_pct):.1%}"
        )
    if state.remaining_term_months <= 0:
        warnings.append("Loan is past maturity; treated as maturing in month 1")
    rows = project_schedule(terms, state)
    return LoanPosition(
        loan=loan, terms=terms, state=state, balance=state.balance, scheduled_balance=state.scheduled_balance,
        balance_difference_pct=state.balance_difference_pct, rate=state.rate, rows=rows, warnings=warnings,
    )


@dataclass
class Collateral:
    property: Property
    source: str                 # model | tape
    value: Decimal
    monthly_noi: list[Decimal]
    warnings: list[str] = field(default_factory=list)
    valuation: Valuation | None = None      # the valuation whose model produced the NOI path
    noi_paths: np.ndarray | None = None     # simulated monthly NOI per path (full property model only)
    exit_cap_rate: Decimal | None = None    # base cap rate for future values
    simulation_id: str | None = None        # the collateral simulation that produced noi_paths
    tape_loan_id: str | None = None         # the loan whose tape NOI / value was used
    tape_roll_factor: Decimal | None = None  # growth applied to roll tape value / NOI to the run date

    def snapshot(self) -> dict:
        v = self.valuation
        return {
            "property_id": self.property.id,
            "property_name": self.property.name,
            "property_type": self.property.property_type,
            "property_updated_at": jsonable(self.property.updated_at),
            "source": self.source,
            "valuation_id": v.id if v else None,
            "valuation_name": v.name if v else None,
            "valuation_updated_at": jsonable(v.updated_at) if v else None,
            "discount_rate": jsonable(v.discount_rate) if v else None,
            "exit_cap_rate": jsonable(v.exit_cap_rate) if v else None,
            "tape_loan_id": self.tape_loan_id,
            "tape_roll_factor": jsonable(self.tape_roll_factor),
            "base_exit_cap_rate": jsonable(self.exit_cap_rate),
            "value": str(self.value),
            "noi_year1": str(self.noi_year1),
            "monthly_noi": [str(round(x, 2)) for x in self.monthly_noi],
            "simulation_id": self.simulation_id,
            "warnings": self.warnings,
        }

    @property
    def noi_year1(self) -> Decimal:
        return sum(self.monthly_noi[:12], Decimal(0))


def record_version(db: AsyncSession, row: RiskParameterSet) -> None:
    """Keep a copy of this parameter set version (call after the row has an id)."""
    db.add(RiskParameterSetVersion(
        parameter_set_id=row.id, version=row.version, name=row.name, comment=row.comment,
        params_json=row.params_json,
    ))


class LoanRiskService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Parameter sets
    # ------------------------------------------------------------------

    async def default_parameter_set(self) -> RiskParameterSet:
        row = (await self.db.execute(
            select(RiskParameterSet).where(RiskParameterSet.is_default.is_(True)).limit(1)
        )).scalar_one_or_none()
        if row is None:
            row = RiskParameterSet(
                name="Base case", version=1, is_default=True,
                params_json=json.dumps(RiskParameters().to_dict()),
                comment="Starting defaults; calibrate to the lender's loss history.",
            )
            self.db.add(row)
            await self.db.flush()
            record_version(self.db, row)
            await self.db.commit()
            await self.db.refresh(row)
        await self._ensure_calibration(row)
        return row

    async def _ensure_calibration(self, default_row: RiskParameterSet) -> None:
        """Refresh a pre-calibration default set and add the wide-scenario CMM preset if missing."""
        defaults = RiskParameters()
        params = json.loads(default_row.params_json)
        changed = "workout_carry_pct" not in params
        if changed:
            for k in CALIBRATED_KEYS:
                params[k] = getattr(defaults, k)
            params.setdefault("driver_volatility", dict(defaults.driver_volatility))
            params["driver_volatility"]["cap_rate"] = defaults.vol("cap_rate")
            default_row.params_json = json.dumps(params)
            default_row.version += 1
            default_row.comment = "Calibrated settings refreshed (scripts/calibrate_default_model.py)."
            record_version(self.db, default_row)
        exists = (await self.db.execute(
            select(RiskParameterSet.id).where(RiskParameterSet.name == CMM_WIDE_PRESET_NAME).limit(1)
        )).scalar_one_or_none()
        if exists is None:
            changed = True
            preset = dict(CMM_WIDE_PRESET)
            cap_vol = preset.pop("cap_rate_volatility")
            p = replace(defaults, **preset, driver_volatility=dict(defaults.driver_volatility, cap_rate=cap_vol))
            row = RiskParameterSet(
                name=CMM_WIDE_PRESET_NAME, version=1, is_default=False, params_json=json.dumps(p.to_dict()),
                comment="Scenarios widened until losses alone match the Moody's CMM grid; wider than NCREIF history.",
            )
            self.db.add(row)
            await self.db.flush()
            record_version(self.db, row)
        if changed:
            await self.db.commit()
            await self.db.refresh(default_row)

    # ------------------------------------------------------------------
    # Collateral
    # ------------------------------------------------------------------

    async def _latest_valuation(self, property_id: str) -> Valuation | None:
        rows = (await self.db.execute(
            select(Valuation).where(Valuation.property_id == property_id)
            .order_by(Valuation.updated_at.desc(), Valuation.created_at.desc())
        )).scalars().all()
        for v in rows:
            if v.discount_rate is not None and v.exit_cap_rate is not None:
                return v
        return None

    async def build_collateral(
        self, prop: Property, loans: list[MortgageLoan], as_of: date, horizon_months: int,
        params: RiskParameters, set_info: dict | None = None,
    ) -> Collateral:
        """Full property model when available, otherwise the loan tape's NOI and value."""
        warnings: list[str] = []
        valuation = await self._latest_valuation(prop.id)
        has_suites = valuation is not None and (await self.db.execute(
            select(Suite.id).where(Suite.valuation_id == valuation.id).limit(1)
        )).first() is not None
        unsupported = prop.property_type in MODEL_UNSUPPORTED_TYPES or (
            prop.property_type == "self_storage" and valuation is not None
            and bool(valuation.self_storage_assumptions_json)
        )
        if not unsupported and has_suites and valuation is not None:
            try:
                return await self._model_collateral(prop, valuation, as_of, horizon_months, params, set_info or {})
            except Exception as exc:  # noqa: BLE001 - fall back to tape data, keep the reason
                warnings.append(f"Property model failed ({exc}); used loan tape collateral")
        elif unsupported:
            warnings.append("Property type not modeled monthly; used loan tape collateral")
        elif not has_suites or valuation is None:
            warnings.append("No full property model with discount and exit cap rates; used loan tape collateral")

        tape = next((l for l in loans if l.tape_noi is not None and l.tape_value is not None), None)
        if tape is None:
            raise ValueError("No property model and no tape NOI / value on the loan")
        growth = tape.tape_noi_growth if tape.tape_noi_growth is not None else DEFAULT_TAPE_NOI_GROWTH
        # Roll the tape value (and its NOI, taken as of the same date) to the projection start at the
        # NOI growth rate, i.e. at an unchanged cap rate
        start = projection_start(as_of)
        if tape.tape_value_date is None:
            factor = Decimal(1)
            warnings.append("Tape value has no value date; used as of the run date without adjustment")
        else:
            years = Decimal((start - tape.tape_value_date).days) / Decimal("365.25")
            factor = (1 + growth) ** years
        months = horizon_months + 12
        monthly = [
            tape.tape_noi * factor / 12 * (1 + growth) ** Decimal(str((m // 12)))
            for m in range(months)
        ]
        exit_cap = tape.tape_exit_cap_rate or next(
            (l.tape_exit_cap_rate for l in loans if l.tape_exit_cap_rate), None
        )
        if exit_cap is None:
            warnings.append("No tape exit cap rate; future values use the tape NOI / value cap rate")
        return Collateral(
            property=prop, source="tape", value=tape.tape_value * factor, monthly_noi=monthly,
            warnings=warnings, tape_loan_id=tape.id, tape_roll_factor=factor, exit_cap_rate=exit_cap,
        )

    async def _model_collateral(
        self, prop: Property, valuation: Valuation, as_of: date, horizon_months: int, params: RiskParameters,
        set_info: dict,
    ) -> Collateral:
        """
        Value today from the deterministic model; NOI on each path from collateral Monte Carlo
        (the full engine on every path, reused while the inputs are unchanged).
        """
        sims = CollateralSimulationService(self.db)
        start = projection_start(as_of)
        # Collateral value and NOI are unlevered: drop the owner's financing and price
        value_case = await sims.case_for(valuation, prop, start=start, unlevered=True)
        value_run = await asyncio.to_thread(value_case.run)
        path_months = max(12, math.ceil((horizon_months + 12) / 12) * 12)
        path_case = replace(value_case, analysis_period_months=path_months)
        outcome = await sims.get_or_run(prop, valuation, path_case, params, "loan_risk", include_monthly=True,
                                        **set_info)
        monthly = [Decimal(str(round(float(x), 2))) for x in outcome.arrays["base_monthly_noi"]]
        return Collateral(
            property=prop, source="model", value=value_run.npv, monthly_noi=monthly, valuation=valuation,
            noi_paths=outcome.arrays["monthly_noi"], simulation_id=outcome.simulation.id,
            exit_cap_rate=value_case.params.exit_cap_rate,
        )

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def load_loans(self, portfolio_id: str | None) -> list[MortgageLoan]:
        stmt = select(MortgageLoan)
        if portfolio_id:
            member_ids = select(portfolio_properties.c.property_id).where(
                portfolio_properties.c.portfolio_id == portfolio_id
            )
            stmt = stmt.where(
                (MortgageLoan.portfolio_id == portfolio_id) | MortgageLoan.property_id.in_(member_ids)
            )
        return list((await self.db.execute(stmt.order_by(MortgageLoan.external_id))).scalars().all())

    async def execute(self, run_id: str) -> LoanRiskRun:
        run = await self.db.get(LoanRiskRun, run_id)
        if run is None:
            raise LookupError("Run not found")
        run.status = "running"
        await self.db.commit()
        try:
            params = RiskParameters.from_dict(json.loads(run.params_json))
            results, inputs = await self._compute(run, params)
            run.results_json = json.dumps(results)
            run.inputs_json = json.dumps(inputs)
            run.status = "completed"
            run.progress = Decimal(1)
        except Exception as exc:  # noqa: BLE001 - recorded on the run
            run.status = "failed"
            run.error_message = str(exc)
        await self.db.commit()
        return run

    async def _set_progress(self, run: LoanRiskRun, value: float) -> None:
        run.progress = Decimal(str(round(value, 4)))
        await self.db.commit()

    async def _compute(self, run: LoanRiskRun, params: RiskParameters) -> tuple[dict, dict]:
        as_of = run.as_of_date
        loans = await self.load_loans(run.portfolio_id)
        if not loans:
            raise ValueError("No loans to run")
        index0 = Decimal(str(sorted(params.index_curve)[0][1])) if params.index_curve else Decimal(0)

        positions = {l.id: loan_position(l, as_of, index0) for l in loans}
        by_property: dict[str, list[MortgageLoan]] = defaultdict(list)
        for l in loans:
            by_property[l.property_id].append(l)

        collateral: dict[str, Collateral] = {}
        props: dict[str, Property] = {}
        errors: dict[str, str] = {}
        for i, (prop_id, prop_loans) in enumerate(by_property.items()):
            prop = await self.db.get(Property, prop_id)
            props[prop_id] = prop
            horizon = max(
                len(positions[l.id].rows) + l.extension_count * l.extension_months for l in prop_loans
            ) + params.liquidation_lag(prop.property_type) + 12
            try:
                collateral[prop_id] = await self.build_collateral(
                    prop, prop_loans, as_of, horizon, params,
                    set_info={"parameter_set_id": run.parameter_set_id,
                              "parameter_set_version": run.parameter_set_version},
                )
            except Exception as exc:  # noqa: BLE001 - reported per loan
                errors[prop_id] = str(exc)
            await self._set_progress(run, 0.4 * (i + 1) / len(by_property))

        sim_collateral = [
            CollateralInput(
                key=pid, property_type=c.property.property_type, market=c.property.market,
                monthly_noi=np.array([float(x) for x in c.monthly_noi]),
                current_value=float(c.value), noi_paths=c.noi_paths,
                exit_cap_rate=float(c.exit_cap_rate) if c.exit_cap_rate else None,
            )
            for pid, c in collateral.items()
        ]
        sim_loans = [
            loan_input_from_schedule(
                l.id, l.property_id, positions[l.id].terms, positions[l.id].state,
                positions[l.id].rows, lien_position=l.lien_position, extension_count=l.extension_count,
                extension_months=l.extension_months, delinquency_status=l.delinquency_status,
            )
            for l in loans if l.property_id in collateral
        ]
        sim_results, portfolio = await asyncio.to_thread(simulate, sim_collateral, sim_loans, params)
        await self._set_progress(run, 0.95)
        by_loan = {r.loan_id: r for r in sim_results}

        previous = await self._previous_ratings(run)
        rows = []
        for l in loans:
            rows.append(self._loan_row(
                l, positions, by_property[l.property_id], props[l.property_id], collateral.get(l.property_id),
                by_loan.get(l.id), errors.get(l.property_id), previous.get(l.id),
            ))
        ok = [r for r in rows if r["error"] is None]
        inputs = {
            "as_of_date": as_of.isoformat(),
            "index_rate_at_start": str(index0),
            "loans": [row_dict(l) for l in loans],
            "collateral": {pid: c.snapshot() for pid, c in collateral.items()},
            "collateral_errors": errors,
        }
        return {
            "as_of_date": as_of.isoformat(),
            "loan_count": len(rows),
            "loans": rows,
            "portfolio": {
                "total_balance": portfolio.total_balance,
                "expected_loss_amount": portfolio.expected_loss_amount,
                "expected_loss": portfolio.expected_loss,
                "loss_std": portfolio.loss_std,
                "var": portfolio.var,
                "expected_shortfall_99": portfolio.expected_shortfall_99,
                "histogram": portfolio.histogram,
                "fair_value": sum(r["fair_value"] for r in ok),
                "weighted_ltv": _weighted(ok, "ltv"),
                "weighted_dscr": _weighted(ok, "dscr"),
                "weighted_pd": _weighted(ok, "pd_cumulative"),
                "weighted_lgd": _weighted([r for r in ok if r["lgd"] is not None], "lgd"),
            },
            "moodys_buckets": _buckets(ok, "moodys_rating", MOODYS_RATINGS + [WORST_RATING]),
            "naic_buckets": _buckets(ok, "naic_cm", list(NAIC_CM_FACTORS)),
            "maturity_wall": _maturity_wall(ok),
        }, inputs

    async def _previous_ratings(self, run: LoanRiskRun) -> dict[str, str]:
        prev = (await self.db.execute(
            select(LoanRiskRun)
            .where(LoanRiskRun.status == "completed", LoanRiskRun.id != run.id,
                   LoanRiskRun.portfolio_id.is_(None) if run.portfolio_id is None
                   else LoanRiskRun.portfolio_id == run.portfolio_id)
            .order_by(LoanRiskRun.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if prev is None or not prev.results_json:
            return {}
        return {r["loan_id"]: r["moodys_rating"] for r in json.loads(prev.results_json)["loans"]
                if r.get("moodys_rating")}

    def _loan_row(
        self,
        loan: MortgageLoan,
        positions: dict[str, LoanPosition],
        siblings: list[MortgageLoan],
        prop: Property,
        col: Collateral | None,
        sim: LoanRiskResult | None,
        error: str | None,
        previous_rating: str | None,
    ) -> dict:
        pos = positions[loan.id]
        row = {
            "loan_id": loan.id,
            "external_id": loan.external_id,
            "name": loan.name,
            "property_id": loan.property_id,
            "property_name": prop.name,
            "property_type": prop.property_type,
            "market": prop.market,
            "lien_position": loan.lien_position,
            "origination_date": loan.origination_date.isoformat(),
            "maturity_date": loan.maturity_date.isoformat(),
            "original_balance": float(loan.original_balance),
            "balance": float(pos.balance),
            "scheduled_balance": float(pos.scheduled_balance),
            "rate": float(pos.rate),
            "remaining_term_months": len(pos.rows),
            "wal_years": float(weighted_average_life_years(pos.rows)),
            "delinquency_status": loan.delinquency_status,
            "warnings": list(pos.warnings) + (list(col.warnings) if col else []),
            "error": error,
            "collateral_source": col.source if col else None,
            "collateral_simulation_id": col.simulation_id if col else None,
        }
        if col is None or sim is None:
            row["error"] = error or "Not simulated"
            return row

        seniors = [s for s in siblings if s.lien_position <= loan.lien_position]
        cum_balance = sum((positions[s.id].balance for s in seniors), Decimal(0))
        cum_ds = sum((positions[s.id].next_12_debt_service for s in seniors), Decimal(0))
        noi1 = col.noi_year1
        value = col.value
        ltv = cum_balance / value if value > 0 else None
        dscr = noi1 / cum_ds if cum_ds > 0 else None
        dsc_naic = naic_dsc(noi1, cum_balance, pos.rate)
        ltv_naic = naic_ltv(cum_balance, value)
        rating = moodys_rating(sim.expected_loss, row["wal_years"])
        row.update({
            "collateral_value": float(value),
            "noi_year1": float(noi1),
            "ltv": float(ltv) if ltv is not None else None,
            "own_ltv": float(pos.balance / value) if value > 0 else None,
            "dscr": float(dscr) if dscr is not None else None,
            "debt_yield": float(noi1 / cum_balance) if cum_balance > 0 else None,
            "naic_dsc": float(dsc_naic) if dsc_naic is not None else None,
            "naic_ltv": float(ltv_naic) if ltv_naic is not None else None,
            "naic_cm": naic_cm_category(dsc_naic, ltv_naic, loan.delinquency_status, loan.lien_position == 1),
            "pd_cumulative": sim.pd_cumulative,
            "pd_term": sim.pd_term,
            "pd_maturity": sim.pd_maturity,
            "pd_one_year": sim.pd_one_year,
            "pd_annualized": sim.pd_annualized,
            "pd_by_year": sim.pd_by_year,
            "lgd": sim.lgd,
            "expected_loss": sim.expected_loss,
            "expected_loss_amount": sim.expected_loss_amount,
            "loss_percentiles": sim.loss_percentiles,
            "fair_value": sim.fair_value,
            "fair_value_price": sim.fair_value_price,
            "moodys_rating": rating,
            "previous_moodys_rating": previous_rating,
            "value_fan": sim.value_percentiles,
            "balance_by_year": [float(pos.balance)] + [
                float(pos.rows[m - 1].ending_balance) for m in range(12, len(pos.rows) + 1, 12)
            ],
        })
        return row


def _weighted(rows: list[dict], key: str) -> float | None:
    pairs = [(r["balance"], r[key]) for r in rows if r.get(key) is not None and math.isfinite(r[key])]
    total = sum(b for b, _ in pairs)
    return sum(b * v for b, v in pairs) / total if total else None


def _buckets(rows: list[dict], key: str, order: list[str]) -> list[dict]:
    total = sum(r["balance"] for r in rows) or 1.0
    out = []
    for bucket in order:
        group = [r for r in rows if r.get(key) == bucket]
        if not group:
            continue
        balance = sum(r["balance"] for r in group)
        el_amount = sum(r["expected_loss_amount"] for r in group)
        out.append({
            "bucket": bucket,
            "loan_count": len(group),
            "balance": balance,
            "share_of_balance": balance / total,
            "pd": _weighted(group, "pd_cumulative"),
            "lgd": _weighted([r for r in group if r["lgd"] is not None], "lgd"),
            "expected_loss": el_amount / balance if balance else 0.0,
            "expected_loss_amount": el_amount,
            "ltv": _weighted(group, "ltv"),
            "dscr": _weighted(group, "dscr"),
            "fair_value": sum(r["fair_value"] for r in group),
            "rbc_factor": NAIC_CM_FACTORS.get(bucket),
        })
    return out


def _maturity_wall(rows: list[dict]) -> list[dict]:
    by_year: dict[int, float] = defaultdict(float)
    for r in rows:
        by_year[int(r["maturity_date"][:4])] += r["balance"]
    return [{"year": y, "balance": b} for y, b in sorted(by_year.items())]
