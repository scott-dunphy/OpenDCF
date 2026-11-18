from datetime import date
from decimal import Decimal

import pytest

from src.schemas.portfolio import PortfolioDisposition, PropertyRunResult, ScenarioResult
from src.services.portfolio_disposition import analyze_dispositions


def scenario(*rows: PropertyRunResult) -> ScenarioResult:
    total = sum((row.share_value or Decimal(0) for row in rows), Decimal(0))
    return ScenarioResult(
        scenario_name="Base", total_value=total, total_share_value=total,
        total_share_year1_noi=Decimal(0), properties=list(rows),
    )


def test_standalone_asset_remains_in_allocation_and_can_be_sold():
    marina = PropertyRunResult(
        property_id="m1", property_name="Marina", property_type="marina",
        ownership_pct=Decimal("0.5"), value=Decimal("200"), share_value=Decimal("100"),
    )
    retained = analyze_dispositions(
        scenario(marina),
        [PortfolioDisposition(property_id="m1", sale_date=date(2027, 1, 1), sale_price=Decimal("220"))],
    )
    assert retained.net_sale_proceeds == Decimal("107.800")
    assert retained.remaining_share_value == 0
    assert any("without a monthly forecast" in warning for warning in retained.warnings)


def test_disposition_rejects_date_outside_forecast():
    office = PropertyRunResult(
        property_id="o1", property_name="Office", property_type="office",
        ownership_pct=Decimal(1), value=Decimal("100"), share_value=Decimal("100"),
        monthly_cfbd={"2026-01-01": Decimal("1"), "2026-02-01": Decimal("1")},
        terminal_value=Decimal("100"),
    )
    with pytest.raises(ValueError, match="must be between"):
        analyze_dispositions(
            scenario(office),
            [PortfolioDisposition(property_id="o1", sale_date=date(2027, 1, 1))],
        )
