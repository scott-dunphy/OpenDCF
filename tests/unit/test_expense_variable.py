"""Fixed/variable expense split and per-area expense entry."""
from datetime import date
from decimal import Decimal

from src.engine.expense_engine import _grossed_up_expense, occupancy_adjusted_expense
from src.engine.property_cashflow import run_valuation
from src.engine.types import SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_growth_schedules import _expense, _flat_lease

D = Decimal


class TestOccupancyAdjustment:
    def test_zero_variable_is_unchanged(self):
        assert occupancy_adjusted_expense(D("1000"), _expense(), D("0.5")) == D("1000")

    def test_variable_share_scales_with_occupancy(self):
        exp = _expense(variable_pct=D("0.6"))
        # 1000 x (0.4 + 0.6 x 0.5) = 700
        assert occupancy_adjusted_expense(D("1000"), exp, D("0.5")) == D("700.0")
        assert occupancy_adjusted_expense(D("1000"), exp, D("1")) == D("1000")

    def test_gross_up_only_lifts_variable_share(self):
        exp = _expense(variable_pct=D("0.6"), is_gross_up_eligible=True, gross_up_vacancy_pct=D("0.95"))
        # 1000 x (0.4 + 0.6 x 0.95) = 970
        assert _grossed_up_expense(D("1000"), exp, D("0.5")) == D("970.00")
        # Above the reference occupancy: actual
        assert _grossed_up_expense(D("1000"), exp, D("0.98")) == D("988.0")
        # Not eligible: actual
        assert _grossed_up_expense(D("1000"), _expense(variable_pct=D("0.6")), D("0.5")) == D("700.0")


class TestWaterfallVariableExpense:
    def test_half_vacant_building_incurs_less_variable_expense(self):
        suites = [
            SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office"),
            SuiteInput(suite_id="S2", suite_name="200", area=D("10000"), space_type="office"),
        ]
        r = run_valuation(
            property_start_date=date(2025, 1, 1),
            analysis_period_months=12,
            fiscal_year_end_month=12,
            suites=suites,
            leases=[_flat_lease()],  # only S1 leased; S2 has no market match below -> vacant
            market_assumptions={},
            expenses=[_expense(variable_pct=D("0.5"))],
            params=_make_params(total_area=D("20000")),
        )
        # Occupancy 50%: 100,000 x (0.5 + 0.5 x 0.5) = 75,000
        assert -r.annual_cash_flows[0].operating_expenses == D("75000.00")
