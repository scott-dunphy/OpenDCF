from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.services.ncreif_performance import forecast_ncreif_returns


def month(number: int, noi: str = "100", capex: str = "0"):
    return SimpleNamespace(
        period_start=date(2026, number, 1),
        period_end=date(2026, number, 28),
        net_operating_income=Decimal(noi),
        tenant_improvements=-Decimal(capex),
        leasing_commissions=Decimal(0),
        capital_reserves=Decimal(0),
        building_improvements=Decimal(0),
    )


def test_ncreif_quarterly_formula_and_ownership_share():
    rows = [month(i, capex="30" if i == 1 else "0") for i in range(1, 7)]
    result = forecast_ncreif_returns(
        rows,
        beginning_market_value=Decimal("12000"),
        exit_cap_rate=Decimal("0.10"),
        ownership_pct=Decimal("0.50"),
        terminal_market_value=Decimal("12000"),
    )
    first = result["periods"][0]
    denominator = Decimal("12000") + Decimal("15") - Decimal("100")
    assert first["denominator"] == denominator * Decimal("0.50")
    assert first["income_return"] == Decimal("300") / denominator
    assert first["capital_improvements"] == Decimal("15")
    assert result["cumulative_time_weighted_return"] == (
        (Decimal(1) + result["periods"][0]["total_return"])
        * (Decimal(1) + result["periods"][1]["total_return"])
        - Decimal(1)
    )


def test_ncreif_partial_quarter_annualizes_using_elapsed_days():
    result = forecast_ncreif_returns(
        [month(1)], beginning_market_value=Decimal("12000"),
        exit_cap_rate=Decimal("0.10"), terminal_market_value=Decimal("12100"),
    )
    linked = Decimal(1) + result["periods"][0]["total_return"]
    expected = linked ** (Decimal("365.25") / Decimal(28)) - Decimal(1)
    assert abs(result["annualized_time_weighted_return"] - expected) < Decimal("0.00000001")
