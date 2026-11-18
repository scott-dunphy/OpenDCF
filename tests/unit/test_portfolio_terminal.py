from datetime import date
from decimal import Decimal

from src.schemas.portfolio import PropertyRunResult
from src.services.portfolio_service import _terminal_proceeds


def _row(**kwargs) -> PropertyRunResult:
    return PropertyRunResult(
        property_id="p1",
        property_name="P1",
        property_type="office",
        ownership_pct=Decimal("0.5"),
        terminal_value=Decimal("980"),
        quarterly_market_value={"2029 Q2": Decimal("800"), "2035 Q4": Decimal("1000")},
        **kwargs,
    )


def test_interest_held_to_exit_gets_terminal_value():
    assert _terminal_proceeds(_row(), date(2035, 12, 31)) == (date(2035, 12, 31), Decimal("490"))


def test_mid_hold_disposition_sells_at_effective_to():
    sale_date, proceeds = _terminal_proceeds(
        _row(ownership_effective_to=date(2029, 6, 30)), date(2035, 12, 31)
    )
    assert sale_date == date(2029, 6, 30)
    # 800 forecast value x 98% net-of-exit-cost ratio x 50% ownership
    assert proceeds == Decimal("392")


def test_time_weighted_return_excludes_assets_without_quarterly_values():
    from src.services.portfolio_service import PortfolioService

    def row(pid, quarterly):
        return PropertyRunResult(
            property_id=pid, property_name=pid, property_type="office",
            ownership_pct=Decimal(1), value=Decimal("50000000"), share_value=Decimal("50000000"),
            quarterly_market_value=quarterly,
        )

    office = row("office", {"2025 Q1": Decimal("50000000")})
    marina = row("marina", {})
    result = PortfolioService(None)._rollup(None, "base", [office, marina])
    assert result.quarterly_time_weighted_returns["2025 Q1"] == Decimal(0)
