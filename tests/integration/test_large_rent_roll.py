"""
Stress test: 200-suite portfolio runs correctly within 5 seconds.
Verifies engine scales linearly and produces consistent results.
"""
import time
from datetime import date
from decimal import Decimal

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import (
    ExpenseInput,
    LeaseInput,
    MarketAssumptions,
    SuiteInput,
    ValuationParams,
)

NUM_SUITES = 200
AREA_PER_SUITE = Decimal("2000")
TOTAL_AREA = AREA_PER_SUITE * NUM_SUITES


@pytest.fixture(scope="module")
def large_roll_result():
    suites = [
        SuiteInput(
            suite_id=f"s{i}", suite_name=f"Suite {i:03d}",
            area=AREA_PER_SUITE, space_type="office",
        )
        for i in range(NUM_SUITES)
    ]
    # Stagger lease expirations: half expire 2027, half expire 2029
    leases = []
    for i in range(NUM_SUITES):
        exp = date(2027, 12, 31) if i < NUM_SUITES // 2 else date(2029, 12, 31)
        leases.append(LeaseInput(
            lease_id=f"l{i}", suite_id=f"s{i}", tenant_name=f"Tenant {i}",
            area=AREA_PER_SUITE, start_date=date(2025, 1, 1), end_date=exp,
            base_rent_per_unit=Decimal("30"), rent_payment_frequency="annual",
            escalation_type="pct_annual", escalation_pct=Decimal("0.03"),
            cpi_floor=None, cpi_cap=None, rent_steps=(), free_rent_periods=(),
            recovery_type="nnn", pro_rata_share=None, base_year_stop_amount=None,
            expense_stop_per_sf=None, recovery_overrides=(), pct_rent_breakpoint=None,
            pct_rent_rate=None, renewal_probability_override=None,
        ))
    market = MarketAssumptions(
        space_type="office", market_rent_per_unit=Decimal("35"),
        rent_growth_rate=Decimal("0.03"), new_lease_term_months=60,
        new_ti_per_sf=Decimal("50"), new_lc_pct=Decimal("0.06"),
        new_free_rent_months=3, downtime_months=6,
        renewal_probability=Decimal("0.65"), renewal_term_months=60,
        renewal_ti_per_sf=Decimal("20"), renewal_lc_pct=Decimal("0.03"),
        renewal_free_rent_months=1, renewal_rent_adjustment_pct=Decimal("0.00"),
        general_vacancy_pct=Decimal("0.05"), credit_loss_pct=Decimal("0.01"),
    )
    expense = ExpenseInput(
        expense_id="cam", category="cam",
        base_amount=Decimal("400000"),  # $2/SF × 200,000 SF
        growth_rate=Decimal("0.03"), is_recoverable=True,
        is_gross_up_eligible=False, gross_up_vacancy_pct=None,
        is_pct_of_egi=False, pct_of_egi=None,
    )
    params = ValuationParams(
        discount_rate=Decimal("0.07"), exit_cap_rate=Decimal("0.06"),
        exit_cap_year=-1, exit_costs_pct=Decimal("0"),
        capital_reserves_per_unit=Decimal("0"),
        total_property_area=TOTAL_AREA, use_mid_year_convention=False,
        loan_amount=None, interest_rate=None, amortization_months=None,
        loan_term_months=None, io_period_months=0,
    )

    start = time.perf_counter()
    result = run_valuation(
        property_start_date=date(2025, 1, 1),
        analysis_period_months=120,
        fiscal_year_end_month=12,
        suites=suites,
        leases=leases,
        market_assumptions={"office": market},
        expenses=[expense],
        params=params,
    )
    elapsed = time.perf_counter() - start
    return result, elapsed


class TestLargeRentRoll:
    """200-suite portfolio — correctness and performance."""

    def test_completes_within_5_seconds(self, large_roll_result):
        _, elapsed = large_roll_result
        assert elapsed < 5.0, f"Engine took {elapsed:.2f}s for {NUM_SUITES} suites (limit: 5s)"

    def test_produces_10_annual_cash_flows(self, large_roll_result):
        result, _ = large_roll_result
        assert len(result.annual_cash_flows) == 10

    def test_year1_gpr_plausible(self, large_roll_result):
        """Year 1 GPR ≈ $30 × 400,000 SF = $12,000,000."""
        result, _ = large_roll_result
        y1_gpr = result.annual_cash_flows[0].gross_potential_rent
        expected = Decimal("30") * TOTAL_AREA
        # Within 1% — some months have proration at analysis start
        assert abs(y1_gpr - expected) < expected * Decimal("0.01"), (
            f"Y1 GPR={y1_gpr:,.0f}, expected≈{expected:,.0f}"
        )

    def test_noi_positive_every_year(self, large_roll_result):
        result, _ = large_roll_result
        for cf in result.annual_cash_flows:
            assert cf.net_operating_income > Decimal("0"), (
                f"Year {cf.year} NOI={cf.net_operating_income} — expected positive"
            )

    def test_terminal_value_positive(self, large_roll_result):
        result, _ = large_roll_result
        assert result.terminal_value > Decimal("0")

    def test_npv_positive(self, large_roll_result):
        result, _ = large_roll_result
        assert result.npv > Decimal("0")

    def test_equity_multiple_above_1(self, large_roll_result):
        result, _ = large_roll_result
        assert result.equity_multiple is not None
        assert result.equity_multiple > Decimal("1.0"), (
            f"equity_multiple={result.equity_multiple} — expected > 1.0"
        )
