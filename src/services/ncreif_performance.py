from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any


def _sum(rows: list[Any], field: str) -> Decimal:
    return sum((Decimal(str(getattr(row, field))) for row in rows), Decimal(0))


def forecast_ncreif_returns(
    monthly_cash_flows: list[Any],
    beginning_market_value: Decimal,
    exit_cap_rate: Decimal,
    ownership_pct: Decimal = Decimal(1),
    terminal_market_value: Decimal | None = None,
) -> dict:
    """Forecast NCREIF NPI-style quarterly property returns and chain-link total return.

    NCREIF denominator:
      BMV + 1/2 capital improvements - 1/2 partial sales - 1/3 NOI
    This forecast presently assumes no partial sales. Period-end values are forward-12-month
    NOI capitalizations; the final period can use the valuation's terminal gross value.
    """
    if beginning_market_value <= 0 or exit_cap_rate <= 0:
        raise ValueError("Beginning market value and exit cap rate must be positive")
    if not monthly_cash_flows:
        raise ValueError("Monthly cash flows are required")

    quarters: dict[tuple[int, int], list[Any]] = defaultdict(list)
    for row in monthly_cash_flows:
        quarter = (row.period_start.month - 1) // 3 + 1
        quarters[(row.period_start.year, quarter)].append(row)
    ordered = list(quarters.items())
    all_rows = [row for _, rows in ordered for row in rows]
    results = []
    bmv = Decimal(beginning_market_value)
    linked = Decimal(1)

    for index, ((year, quarter), rows) in enumerate(ordered):
        last_month = rows[-1]
        position = all_rows.index(last_month)
        forward = all_rows[position + 1 : position + 13]
        if len(forward) < 12:
            trailing = all_rows[max(0, position - 11) : position + 1]
            forward = trailing
        forward_noi = _sum(forward, "net_operating_income")
        if forward and len(forward) != 12:
            forward_noi = forward_noi * Decimal(12) / Decimal(len(forward))
        emv = forward_noi / exit_cap_rate
        if index == len(ordered) - 1 and terminal_market_value is not None:
            emv = Decimal(terminal_market_value)

        noi = _sum(rows, "net_operating_income")
        capital_improvements = -sum(
            (
                _sum(rows, "tenant_improvements"),
                _sum(rows, "leasing_commissions"),
                _sum(rows, "capital_reserves"),
                _sum(rows, "building_improvements"),
            ),
            Decimal(0),
        )
        partial_sales = Decimal(0)
        denominator = (
            bmv + capital_improvements / Decimal(2) - partial_sales / Decimal(2) - noi / Decimal(3)
        )
        if denominator <= 0:
            raise ValueError(f"NCREIF denominator is non-positive in {year} Q{quarter}")
        income_return = noi / denominator
        capital_return = (emv - bmv + partial_sales - capital_improvements) / denominator
        total_return = income_return + capital_return
        linked *= Decimal(1) + total_return
        results.append(
            {
                "period": f"{year} Q{quarter}",
                "period_end": str(last_month.period_end),
                "beginning_market_value": bmv * ownership_pct,
                "ending_market_value": emv * ownership_pct,
                "noi": noi * ownership_pct,
                "capital_improvements": capital_improvements * ownership_pct,
                "partial_sales": partial_sales,
                "denominator": denominator * ownership_pct,
                "income_return": income_return,
                "capital_return": capital_return,
                "total_return": total_return,
            }
        )
        bmv = emv

    first_date = all_rows[0].period_start
    last_date = all_rows[-1].period_end
    elapsed_days = Decimal((last_date - first_date).days + 1)
    years = elapsed_days / Decimal("365.25")
    cumulative = linked - Decimal(1)
    annualized = (
        linked ** (Decimal(1) / years) - Decimal(1)
        if years > 0 and linked > 0
        else None
    )
    return {
        "methodology": "NCREIF NPI-style forecast",
        "frequency": "quarterly",
        "ownership_pct": ownership_pct,
        "beginning_market_value_basis": beginning_market_value,
        "valuation_method": "forward 12-month NOI / exit cap rate",
        "cumulative_time_weighted_return": cumulative,
        "annualized_time_weighted_return": annualized,
        "periods": results,
        "warnings": [
            "Forecast returns are model projections, not reported NCREIF benchmark returns.",
            "Returns are unleveraged and gross of investment management fees.",
            "Partial sales are assumed to be zero.",
            *(
                ["Annualized return is unavailable because cumulative wealth is non-positive."]
                if linked <= 0
                else []
            ),
        ],
    }
