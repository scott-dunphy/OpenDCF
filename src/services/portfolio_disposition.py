from collections import defaultdict
from datetime import date
from decimal import Decimal

from src.engine.dcf import xirr_details
from src.schemas.portfolio import (
    AllocationBucket,
    AllocationSensitivityResult,
    PortfolioDisposition,
    ScenarioResult,
)
from src.services.portfolio_service import _month_end, _ownership_on, _terminal_proceeds


def _quarter_key(value: date) -> str:
    return f"{value.year} Q{(value.month - 1) // 3 + 1}"


def _forecast_value(row, as_of: date) -> Decimal:
    values = row.quarterly_market_value
    if not values:
        return row.value or Decimal(0)
    target = _quarter_key(as_of)
    keys = list(values)
    selected = next((key for key in keys if key >= target), keys[-1])
    return values[selected]


def _xirr(cash_flows: dict[date, Decimal]):
    dates = sorted(cash_flows)
    return xirr_details([cash_flows[item] for item in dates], dates) if dates else None


def _liquidity(cash_flows: dict[date, Decimal]) -> Decimal:
    running = Decimal(0)
    minimum = Decimal(0)
    for value_date in sorted(cash_flows):
        running += cash_flows[value_date]
        minimum = min(minimum, running)
    return -minimum


def _buckets(rows: list[tuple[object, Decimal]], attribute: str) -> list[AllocationBucket]:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for row, value in rows:
        totals[getattr(row, attribute) or "(none)"] += value
    total = sum(totals.values(), Decimal(0))
    return [
        AllocationBucket(
            key=key, share_value=value, allocation_pct=value / total if total else Decimal(0)
        )
        for key, value in sorted(totals.items())
    ]


def analyze_dispositions(
    scenario: ScenarioResult,
    dispositions: list[PortfolioDisposition],
) -> AllocationSensitivityResult:
    by_id = {row.property_id: row for row in scenario.properties}
    if len({item.property_id for item in dispositions}) != len(dispositions):
        raise ValueError("Each property may appear only once in a disposition plan")
    missing = [item.property_id for item in dispositions if item.property_id not in by_id]
    if missing:
        raise ValueError(f"Property not found in portfolio run: {', '.join(missing)}")
    disposition_by_id = {item.property_id: item for item in dispositions}
    as_of = max(item.sale_date for item in dispositions)
    baseline_cash: dict[date, Decimal] = defaultdict(Decimal)
    adjusted_cash: dict[date, Decimal] = defaultdict(Decimal)
    operating_baseline: dict[date, Decimal] = defaultdict(Decimal)
    operating_adjusted: dict[date, Decimal] = defaultdict(Decimal)
    disposition_results = []
    remaining = []
    omitted_return_assets: list[str] = []

    for row in scenario.properties:
        if row.share_value is None:
            continue
        disposition = disposition_by_id.get(row.property_id)
        if not row.monthly_cfbd:
            omitted_return_assets.append(row.property_name)
            ownership = row.ownership_pct
            if disposition is None:
                remaining.append((row, row.share_value))
                continue
            gross_price = disposition.sale_price or row.value or Decimal(0)
            share_gross = gross_price * ownership
            costs = share_gross * disposition.sale_cost_pct
            net = share_gross - costs
            adjusted_cash[disposition.sale_date] += net
            operating_adjusted[disposition.sale_date] += net
            disposition_results.append(
                {
                    "property_id": row.property_id,
                    "property_name": row.property_name,
                    "sale_date": disposition.sale_date,
                    "gross_sale_price": gross_price,
                    "ownership_share_proceeds": share_gross,
                    "sale_costs": costs,
                    "net_share_proceeds": net,
                    "forecast_value_used": disposition.sale_price is None,
                }
            )
            continue
        ownership = row.ownership_pct
        monthly_dates = sorted(date.fromisoformat(key) for key in row.monthly_cfbd)
        start, end = monthly_dates[0], monthly_dates[-1]
        investment_date = row.ownership_effective_from or start
        initial_investment = row.acquisition_cost if row.acquisition_cost is not None else row.share_value
        baseline_cash[investment_date] -= initial_investment
        adjusted_cash[investment_date] -= initial_investment
        for key, value in row.monthly_cfbd.items():
            cash_date = _month_end(date.fromisoformat(key))
            share_cash = value * _ownership_on(row, cash_date)
            baseline_cash[cash_date] += share_cash
            operating_baseline[cash_date] += share_cash
        terminal_date = _month_end(end)
        sale_date, proceeds = _terminal_proceeds(row, terminal_date)
        baseline_cash[sale_date] += proceeds

        if disposition is None:
            for key, value in row.monthly_cfbd.items():
                cash_date = _month_end(date.fromisoformat(key))
                share_cash = value * _ownership_on(row, cash_date)
                adjusted_cash[cash_date] += share_cash
                operating_adjusted[cash_date] += share_cash
            adjusted_cash[sale_date] += proceeds
            remaining.append((row, _forecast_value(row, as_of) * _ownership_on(row, as_of)))
            continue

        if disposition.sale_date < start or disposition.sale_date > terminal_date:
            raise ValueError(
                f"Sale date for {row.property_name} must be between {start} and {terminal_date}"
            )

        for key, value in row.monthly_cfbd.items():
            cash_date = _month_end(date.fromisoformat(key))
            if cash_date <= disposition.sale_date:
                share_cash = value * _ownership_on(row, cash_date)
                adjusted_cash[cash_date] += share_cash
                operating_adjusted[cash_date] += share_cash
        forecast_used = disposition.sale_price is None
        gross_price = disposition.sale_price or _forecast_value(row, disposition.sale_date)
        share_gross = gross_price * _ownership_on(row, disposition.sale_date)
        costs = share_gross * disposition.sale_cost_pct
        net = share_gross - costs
        adjusted_cash[disposition.sale_date] += net
        operating_adjusted[disposition.sale_date] += net
        disposition_results.append(
            {
                "property_id": row.property_id,
                "property_name": row.property_name,
                "sale_date": disposition.sale_date,
                "gross_sale_price": gross_price,
                "ownership_share_proceeds": share_gross,
                "sale_costs": costs,
                "net_share_proceeds": net,
                "forecast_value_used": forecast_used,
            }
        )

    before = _xirr(baseline_cash)
    after = _xirr(adjusted_cash)
    remaining_value = sum((value for _, value in remaining), Decimal(0))
    weights = [value / remaining_value for _, value in remaining] if remaining_value else []
    return AllocationSensitivityResult(
        scenario_id=scenario.scenario_id,
        scenario_name=scenario.scenario_name,
        as_of_date=as_of,
        beginning_share_value=scenario.total_share_value,
        remaining_share_value=remaining_value,
        net_sale_proceeds=sum(
            (item["net_share_proceeds"] for item in disposition_results), Decimal(0)
        ),
        portfolio_xirr_before=before.rate if before else None,
        portfolio_xirr_after=after.rate if after else None,
        required_liquidity_before=_liquidity(operating_baseline),
        required_liquidity_after=_liquidity(operating_adjusted),
        concentration_hhi_before=scenario.concentration_hhi,
        concentration_hhi_after=sum((weight * weight for weight in weights), Decimal(0))
        if weights
        else None,
        largest_property_pct_before=scenario.largest_property_pct,
        largest_property_pct_after=max(weights) if weights else None,
        by_property_type=_buckets(remaining, "property_type"),
        by_market=_buckets(remaining, "market"),
        dispositions=disposition_results,
        warnings=[
            "Sales are modeled at the selected date without intra-month operating proration.",
            "Blank sale prices use the nearest forecast quarter-end market value.",
            "Taxes, debt defeasance, JV promotes, and fund-level fees are excluded.",
            *(
                [
                    "Return calculations exclude operating cash flows for assets without a monthly "
                    f"forecast: {', '.join(omitted_return_assets)}. Allocation and sale proceeds include them."
                ]
                if omitted_return_assets
                else []
            ),
        ],
    )
