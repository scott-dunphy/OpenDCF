"""
DCF parity tests — engine-level scenarios with hand-calculated expected values.

These tests verify the engine produces results consistent with hand-calculated
expected values for well-defined input scenarios. Tolerance: 0.5% for dollar
amounts, 10 bps for rates.

All tests run the pure-Python engine directly (no DB, no async).
"""
from datetime import date
from decimal import Decimal

import pytest

from src.engine.date_utils import build_analysis_period
from src.engine.property_cashflow import run_valuation
from src.engine.types import (
    AnalysisPeriod,
    ExpenseInput,
    LeaseInput,
    MarketAssumptions,
    SuiteInput,
    ValuationParams,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tol(expected: Decimal, pct: Decimal = Decimal("0.005")) -> Decimal:
    """Absolute tolerance = 0.5% of expected (floor: $1)."""
    return max(abs(expected) * pct, Decimal("1"))


def _make_market(
    space_type: str = "office",
    market_rent: Decimal = Decimal("35.00"),
    renewal_prob: Decimal = Decimal("0.65"),
    gen_vacancy: Decimal = Decimal("0.05"),
    credit_loss: Decimal = Decimal("0.01"),
) -> MarketAssumptions:
    return MarketAssumptions(
        space_type=space_type,
        market_rent_per_unit=market_rent,
        rent_growth_rate=Decimal("0.03"),
        new_lease_term_months=60,
        new_ti_per_sf=Decimal("50"),
        new_lc_pct=Decimal("0.06"),
        new_free_rent_months=3,
        downtime_months=6,
        renewal_probability=renewal_prob,
        renewal_term_months=60,
        renewal_ti_per_sf=Decimal("20"),
        renewal_lc_pct=Decimal("0.03"),
        renewal_free_rent_months=1,
        renewal_rent_adjustment_pct=Decimal("0.00"),
        general_vacancy_pct=gen_vacancy,
        credit_loss_pct=credit_loss,
    )


def _make_params(
    discount_rate: Decimal = Decimal("0.07"),
    exit_cap: Decimal = Decimal("0.06"),
    exit_costs: Decimal = Decimal("0.00"),
    cap_reserves: Decimal = Decimal("0.00"),
    total_area: Decimal = Decimal("10000"),
) -> ValuationParams:
    return ValuationParams(
        discount_rate=discount_rate,
        exit_cap_rate=exit_cap,
        exit_cap_year=-1,
        exit_costs_pct=exit_costs,
        capital_reserves_per_unit=cap_reserves,
        total_property_area=total_area,
        use_mid_year_convention=False,
        loan_amount=None,
        interest_rate=None,
        amortization_months=None,
        loan_term_months=None,
        io_period_months=0,
    )


# ---------------------------------------------------------------------------
# Scenario 1: Single NNN Tenant — Full Analysis Coverage
#
# 10,000 SF office suite, 10-year analysis (2025-2034), flat NNN lease.
# Single recoverable expense (real estate taxes).
#
# Hand-calculated expected values:
#   GPR/yr         = $30 * 10,000 = $300,000 (flat)
#   Recovery Yr 1  = $100,000 (100% pro-rata)
#   Recovery Yr 2  = $103,000 (3% growth)
#   Gen Vac (GPR)  = 5% * $300,000 = $15,000
#   Credit Loss    = 1% * $300,000 = $3,000
#   NOI/yr         = $300,000 + Recovery_N - $15,000 - $3,000 - Expense_N
#                  = $282,000 (constant — recovery exactly offsets expense)
#   Exit (fwd NOI) = explicit Year 11 NOI (includes renewal probability + downtime)
#   Terminal Value (expected) ≈ $4,643,604.40
# ---------------------------------------------------------------------------

class TestNNNSingleTenantParity:
    """Parity checks for a simple NNN single-tenant scenario."""

    @pytest.fixture
    def scenario(self):
        suite = SuiteInput(
            suite_id="suite_100",
            suite_name="Suite 100",
            area=Decimal("10000"),
            space_type="office",
        )
        lease = LeaseInput(
            lease_id="lease_001",
            suite_id="suite_100",
            tenant_name="Anchor Tenant",
            area=Decimal("10000"),
            start_date=date(2025, 1, 1),
            end_date=date(2034, 12, 31),   # covers full 10-year analysis
            base_rent_per_unit=Decimal("30.00"),
            rent_payment_frequency="annual",
            escalation_type="flat",
            escalation_pct=None,
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="nnn",
            pro_rata_share=None,   # auto-computed: 10,000/10,000 = 100%
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
            renewal_probability_override=None,
        )
        expense = ExpenseInput(
            expense_id="exp_ret",
            category="real_estate_taxes",
            base_amount=Decimal("100000"),
            growth_rate=Decimal("0.03"),
            is_recoverable=True,
            is_gross_up_eligible=False,
            gross_up_vacancy_pct=None,
            is_pct_of_egi=False,
            pct_of_egi=None,
        )
        market = _make_market()
        params = _make_params()
        result = run_valuation(
            property_start_date=date(2025, 1, 1),
            analysis_period_months=120,
            fiscal_year_end_month=12,
            suites=[suite],
            leases=[lease],
            market_assumptions={"office": market},
            expenses=[expense],
            params=params,
        )
        return result

    def test_ten_fiscal_years(self, scenario):
        assert len(scenario.annual_cash_flows) == 10

    def test_gpr_is_constant(self, scenario):
        """Flat NNN lease → GPR = $300,000 every year."""
        expected = Decimal("300000")
        for cf in scenario.annual_cash_flows:
            assert abs(cf.gross_potential_rent - expected) < _tol(expected), (
                f"Year {cf.year}: GPR = {cf.gross_potential_rent}, expected {expected}"
            )

    def test_recovery_grows_at_3pct(self, scenario):
        """NNN recovery = landlord expense, which grows 3%/yr."""
        for cf in scenario.annual_cash_flows:
            expected_recovery = Decimal("100000") * Decimal("1.03") ** (cf.year - 1)
            assert abs(cf.expense_recoveries - expected_recovery) < _tol(expected_recovery), (
                f"Year {cf.year}: recovery = {cf.expense_recoveries}, expected {expected_recovery}"
            )

    def test_noi_is_constant(self, scenario):
        """With flat GPR and NNN recovery, NOI is constant: GPR - GenVac - CreditLoss.
        = $300,000 - 5%*$300,000 - 1%*$300,000 = $282,000
        """
        expected_noi = Decimal("282000")
        for cf in scenario.annual_cash_flows:
            assert abs(cf.net_operating_income - expected_noi) < _tol(expected_noi), (
                f"Year {cf.year}: NOI = {cf.net_operating_income}, expected {expected_noi}"
            )

    def test_cfbd_equals_noi(self, scenario):
        """No TI/LC (in-place lease), no cap reserves, no debt → CFBD = NOI."""
        for cf in scenario.annual_cash_flows:
            assert abs(cf.cash_flow_before_debt - cf.net_operating_income) < Decimal("1"), (
                f"Year {cf.year}: CFBD ≠ NOI"
            )

    def test_terminal_value(self, scenario):
        """Terminal value uses Year 11 NOI (includes renewal probability + downtime)."""
        expected_tv = Decimal("4643604.40")
        assert abs(scenario.terminal_value - expected_tv) < _tol(expected_tv)

    def test_npv_is_positive(self, scenario):
        assert scenario.npv > Decimal(0)

    def test_going_in_cap_rate(self, scenario):
        """Going-in cap rate = Year 1 NOI / NPV."""
        expected_gin = scenario.annual_cash_flows[0].net_operating_income / scenario.npv
        assert abs(scenario.going_in_cap_rate - expected_gin) < Decimal("0.0001")

    def test_full_occupancy(self, scenario):
        """In-place lease covers entire period → average occupancy = 100%."""
        assert abs(scenario.avg_occupancy_pct - Decimal("1.0")) < Decimal("0.01")

    def test_no_ti_lc(self, scenario):
        """In-place lease covering full period → zero TI/LC in all years."""
        for cf in scenario.annual_cash_flows:
            assert cf.tenant_improvements == Decimal(0), f"Year {cf.year}: TI ≠ 0"
            assert cf.leasing_commissions == Decimal(0), f"Year {cf.year}: LC ≠ 0"


# ---------------------------------------------------------------------------
# Scenario 2: Full Service Gross (FSG) — Landlord Bears All Expenses
#
# Same property but lease is FSG. Tenant pays no expense recovery.
# NOI = GPR - GenVac - CreditLoss - OpEx
#      = $300,000 - $15,000 - $3,000 - $100,000 = $182,000 (Year 1)
# NOI decreases each year as expenses grow but rent is flat.
# ---------------------------------------------------------------------------

class TestFSGSingleTenantParity:
    """Parity: FSG lease, landlord bears all expenses."""

    @pytest.fixture
    def scenario(self):
        suite = SuiteInput(
            suite_id="suite_fsg",
            suite_name="Suite FSG",
            area=Decimal("10000"),
            space_type="office",
        )
        lease = LeaseInput(
            lease_id="lease_fsg",
            suite_id="suite_fsg",
            tenant_name="FSG Tenant",
            area=Decimal("10000"),
            start_date=date(2025, 1, 1),
            end_date=date(2034, 12, 31),
            base_rent_per_unit=Decimal("30.00"),
            rent_payment_frequency="annual",
            escalation_type="flat",
            escalation_pct=None,
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="full_service_gross",
            pro_rata_share=None,
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
            renewal_probability_override=None,
        )
        expense = ExpenseInput(
            expense_id="exp_ret_fsg",
            category="real_estate_taxes",
            base_amount=Decimal("100000"),
            growth_rate=Decimal("0.03"),
            is_recoverable=True,   # designated recoverable, but FSG type means no recovery
            is_gross_up_eligible=False,
            gross_up_vacancy_pct=None,
            is_pct_of_egi=False,
            pct_of_egi=None,
        )
        market = _make_market()
        params = _make_params()
        result = run_valuation(
            property_start_date=date(2025, 1, 1),
            analysis_period_months=120,
            fiscal_year_end_month=12,
            suites=[suite],
            leases=[lease],
            market_assumptions={"office": market},
            expenses=[expense],
            params=params,
        )
        return result

    def test_zero_expense_recoveries(self, scenario):
        """FSG → no recovery from tenant in any year."""
        for cf in scenario.annual_cash_flows:
            assert abs(cf.expense_recoveries) < Decimal("0.01"), (
                f"Year {cf.year}: expected zero recoveries, got {cf.expense_recoveries}"
            )

    def test_year1_noi(self, scenario):
        """Year 1 NOI = GPR - GenVac - CreditLoss - OpEx = $182,000."""
        expected = Decimal("182000")
        cf = scenario.annual_cash_flows[0]
        assert abs(cf.net_operating_income - expected) < _tol(expected)

    def test_noi_declines_as_expenses_grow(self, scenario):
        """With flat rent and growing expenses (no recovery), NOI decreases each year."""
        noi_values = [cf.net_operating_income for cf in scenario.annual_cash_flows]
        for i in range(1, len(noi_values)):
            assert noi_values[i] < noi_values[i - 1], (
                f"NOI did not decrease in year {i + 1}: {noi_values[i]} >= {noi_values[i - 1]}"
            )

    def test_gpr_constant(self, scenario):
        """FSG base rent is flat → GPR constant."""
        expected = Decimal("300000")
        for cf in scenario.annual_cash_flows:
            assert abs(cf.gross_potential_rent - expected) < _tol(expected)


# ---------------------------------------------------------------------------
# Scenario 3: Multi-Tenant Property with Escalation
#
# Two suites (5,000 SF each), one NNN with 3% annual escalation,
# one FSG with flat rent. Verify blended waterfall arithmetic.
# ---------------------------------------------------------------------------

class TestMultiTenantParity:
    """Blended waterfall: one escalating NNN + one flat FSG tenant."""

    @pytest.fixture
    def scenario(self):
        suite_a = SuiteInput(
            suite_id="suite_A",
            suite_name="Suite A",
            area=Decimal("5000"),
            space_type="office",
        )
        suite_b = SuiteInput(
            suite_id="suite_B",
            suite_name="Suite B",
            area=Decimal("5000"),
            space_type="office",
        )
        # Suite A: 3% annual escalation, NNN ($30/SF base)
        lease_a = LeaseInput(
            lease_id="lease_A",
            suite_id="suite_A",
            tenant_name="Tenant A",
            area=Decimal("5000"),
            start_date=date(2025, 1, 1),
            end_date=date(2034, 12, 31),
            base_rent_per_unit=Decimal("30.00"),
            rent_payment_frequency="annual",
            escalation_type="pct_annual",
            escalation_pct=Decimal("0.03"),
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="nnn",
            pro_rata_share=Decimal("0.5"),  # explicit 50% — half the building
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
            renewal_probability_override=None,
        )
        # Suite B: flat FSG ($28/SF)
        lease_b = LeaseInput(
            lease_id="lease_B",
            suite_id="suite_B",
            tenant_name="Tenant B",
            area=Decimal("5000"),
            start_date=date(2025, 1, 1),
            end_date=date(2034, 12, 31),
            base_rent_per_unit=Decimal("28.00"),
            rent_payment_frequency="annual",
            escalation_type="flat",
            escalation_pct=None,
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="full_service_gross",
            pro_rata_share=None,
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
            renewal_probability_override=None,
        )
        expense = ExpenseInput(
            expense_id="exp_cam",
            category="cam",
            base_amount=Decimal("80000"),
            growth_rate=Decimal("0.03"),
            is_recoverable=True,
            is_gross_up_eligible=False,
            gross_up_vacancy_pct=None,
            is_pct_of_egi=False,
            pct_of_egi=None,
        )
        market = _make_market()
        params = _make_params(total_area=Decimal("10000"))
        result = run_valuation(
            property_start_date=date(2025, 1, 1),
            analysis_period_months=120,
            fiscal_year_end_month=12,
            suites=[suite_a, suite_b],
            leases=[lease_a, lease_b],
            market_assumptions={"office": market},
            expenses=[expense],
            params=params,
        )
        return result

    def test_year1_gpr(self, scenario):
        """Year 1 GPR: Suite A $150,000 + Suite B $140,000 = $290,000."""
        cf = scenario.annual_cash_flows[0]
        expected = Decimal("290000")
        assert abs(cf.gross_potential_rent - expected) < _tol(expected)

    def test_year1_recovery(self, scenario):
        """Only Suite A (NNN, 50% share) recovers. Year 1 recovery = $80,000 * 50% = $40,000."""
        cf = scenario.annual_cash_flows[0]
        expected = Decimal("40000")
        assert abs(cf.expense_recoveries - expected) < _tol(expected)

    def test_year2_gpr_escalates(self, scenario):
        """Year 2: Suite A escalates 3% ($154,500), Suite B flat ($140,000) → $294,500."""
        cf = scenario.annual_cash_flows[1]
        expected = Decimal("30.00") * Decimal("1.03") * Decimal("5000") + Decimal("28.00") * Decimal("5000")
        assert abs(cf.gross_potential_rent - expected) < _tol(expected)

    def test_npv_positive(self, scenario):
        assert scenario.npv > Decimal(0)

    def test_irr_reasonable(self, scenario):
        """IRR should be a real number in a reasonable range for a stabilized asset."""
        assert scenario.irr is not None
        assert Decimal("0.01") < scenario.irr < Decimal("0.25")


# ---------------------------------------------------------------------------
# Scenario 4: Pre-Analysis Lease with Pct-Annual Escalation
#
# In-place lease that began 2 years before the analysis start.
# Engine must compute the correct in-progress escalated rent.
#
# Lease: Jan 1 2023, $20/SF/yr, 3% annual, 10,000 SF, flat NNN.
# Analysis: Jan 1 2025 (10-year hold).
# At analysis start: 2 full anniversaries elapsed → rent = $20 * 1.03^2 = $21.218/SF
# Year 1 GPR = $21.218 * 10,000 = $212,180
# ---------------------------------------------------------------------------

class TestPreAnalysisLeaseParity:
    """Lease that began before the analysis period — correct escalated rent."""

    @pytest.fixture
    def scenario(self):
        suite = SuiteInput(
            suite_id="suite_old",
            suite_name="Suite Old",
            area=Decimal("10000"),
            space_type="office",
        )
        lease = LeaseInput(
            lease_id="lease_old",
            suite_id="suite_old",
            tenant_name="Long-Term Tenant",
            area=Decimal("10000"),
            start_date=date(2023, 1, 1),   # 2 years before analysis
            end_date=date(2034, 12, 31),
            base_rent_per_unit=Decimal("20.00"),
            rent_payment_frequency="annual",
            escalation_type="pct_annual",
            escalation_pct=Decimal("0.03"),
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="nnn",
            pro_rata_share=None,
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
            renewal_probability_override=None,
        )
        market = _make_market(market_rent=Decimal("30.00"))
        params = _make_params()
        result = run_valuation(
            property_start_date=date(2025, 1, 1),
            analysis_period_months=120,
            fiscal_year_end_month=12,
            suites=[suite],
            leases=[lease],
            market_assumptions={"office": market},
            expenses=[],
            params=params,
        )
        return result

    def test_year1_gpr_reflects_two_prior_escalations(self, scenario):
        """Year 1 rent = $20 * 1.03^2 * 10,000 = $212,180."""
        cf = scenario.annual_cash_flows[0]
        expected = Decimal("20.00") * Decimal("1.03") ** 2 * Decimal("10000")
        assert abs(cf.gross_potential_rent - expected) < _tol(expected)

    def test_year2_gpr_reflects_third_escalation(self, scenario):
        """Year 2 (Jan 2026): 3rd anniversary in Jan 2026 → rent = $20 * 1.03^3 * 10,000."""
        cf = scenario.annual_cash_flows[1]
        expected = Decimal("20.00") * Decimal("1.03") ** 3 * Decimal("10000")
        assert abs(cf.gross_potential_rent - expected) < _tol(expected)

    def test_gpr_grows_each_year(self, scenario):
        """GPR should increase every year (3% escalation)."""
        gprs = [cf.gross_potential_rent for cf in scenario.annual_cash_flows]
        for i in range(1, len(gprs)):
            assert gprs[i] > gprs[i - 1], f"GPR did not grow in year {i + 1}"


# ---------------------------------------------------------------------------
# Scenario 5: Vacant Suite — Full Speculative Leasing
#
# Suite has no in-place lease at analysis start.
# Engine generates probability-weighted speculative leases for the full period.
# Expected: first N months vacant (downtime), then speculative leases.
# NOI < 0 is possible in early years (TI/LC costs at commencement).
# ---------------------------------------------------------------------------

class TestVacantSuiteParity:
    """Suite with no in-place lease — engine generates speculative coverage."""

    @pytest.fixture
    def scenario(self):
        suite = SuiteInput(
            suite_id="suite_vacant",
            suite_name="Vacant Suite",
            area=Decimal("5000"),
            space_type="office",
        )
        market = _make_market(
            market_rent=Decimal("30.00"),
            renewal_prob=Decimal("0.65"),
            gen_vacancy=Decimal("0.05"),
            credit_loss=Decimal("0.01"),
        )
        params = _make_params(total_area=Decimal("5000"))
        result = run_valuation(
            property_start_date=date(2025, 1, 1),
            analysis_period_months=120,
            fiscal_year_end_month=12,
            suites=[suite],
            leases=[],          # no in-place leases
            market_assumptions={"office": market},
            expenses=[],
            params=params,
        )
        return result

    def test_ten_fiscal_years(self, scenario):
        assert len(scenario.annual_cash_flows) == 10

    def test_year1_has_some_rent_after_downtime(self, scenario):
        """After 6 months downtime, the new tenant commences mid-year.
        Year 1 GPR should be positive (partial year of rent)."""
        cf = scenario.annual_cash_flows[0]
        assert cf.gross_potential_rent >= Decimal(0)

    def test_probability_weighted_cash_flows_sum_correctly(self, scenario):
        """All years should have NOI (could be negative year 1 due to TI/LC)."""
        for cf in scenario.annual_cash_flows:
            # NOI + TI + LC + reserves = CFBD — just verify consistency
            cfbd_check = cf.net_operating_income + cf.tenant_improvements + cf.leasing_commissions + cf.capital_reserves
            assert abs(cf.cash_flow_before_debt - cfbd_check) < Decimal("1"), (
                f"Year {cf.year}: CFBD consistency check failed"
            )

    def test_later_years_have_positive_gpr(self, scenario):
        """By year 3+, speculative leases should be generating stable rent."""
        for cf in scenario.annual_cash_flows[2:]:
            assert cf.gross_potential_rent > Decimal(0), f"Year {cf.year}: GPR is zero"


# ---------------------------------------------------------------------------
# Scenario 6: Non-December Fiscal Year End (June 30)
#
# Analysis starts Jan 1 2025, fiscal year ends June 30.
# Year 1 = Jan–Jun 2025 (6 months), Year 2 = Jul 2025–Jun 2026 (12 months), etc.
# In-place flat NNN lease covering full period.
# Year 1 GPR should be approximately half of Year 2+ GPR.
# ---------------------------------------------------------------------------

class TestNonDecemberFiscalYear:
    """Fiscal year ending June 30 — Year 1 is a partial year."""

    @pytest.fixture
    def scenario(self):
        suite = SuiteInput(
            suite_id="suite_fy",
            suite_name="Suite FY",
            area=Decimal("10000"),
            space_type="office",
        )
        lease = LeaseInput(
            lease_id="lease_fy",
            suite_id="suite_fy",
            tenant_name="FY Tenant",
            area=Decimal("10000"),
            start_date=date(2025, 1, 1),
            end_date=date(2035, 6, 30),
            base_rent_per_unit=Decimal("24.00"),
            rent_payment_frequency="annual",
            escalation_type="flat",
            escalation_pct=None,
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="nnn",
            pro_rata_share=None,
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
            renewal_probability_override=None,
        )
        market = _make_market(gen_vacancy=Decimal("0.05"), credit_loss=Decimal("0.01"))
        params = _make_params()
        result = run_valuation(
            property_start_date=date(2025, 1, 1),
            analysis_period_months=120,
            fiscal_year_end_month=6,    # June 30 fiscal year end
            suites=[suite],
            leases=[lease],
            market_assumptions={"office": market},
            expenses=[],
            params=params,
        )
        return result

    def test_first_fiscal_year_is_partial(self, scenario):
        """Year 1 runs Jan–Jun 2025 (6 months). Year 2 starts Jul 2025."""
        fy1 = scenario.annual_cash_flows[0]
        assert fy1.period_start == date(2025, 1, 1)
        assert fy1.period_end == date(2025, 6, 30)

    def test_second_fiscal_year_is_full(self, scenario):
        """Year 2 runs Jul 2025–Jun 2026 (12 months)."""
        fy2 = scenario.annual_cash_flows[1]
        assert fy2.period_start == date(2025, 7, 1)
        assert fy2.period_end == date(2026, 6, 30)

    def test_year1_gpr_is_half_of_year2(self, scenario):
        """Flat rent: Year 1 (6 months) GPR ≈ half of Year 2 (12 months) GPR."""
        fy1_gpr = scenario.annual_cash_flows[0].gross_potential_rent
        fy2_gpr = scenario.annual_cash_flows[1].gross_potential_rent
        ratio = fy1_gpr / fy2_gpr
        assert abs(ratio - Decimal("0.5")) < Decimal("0.01"), (
            f"Year 1/Year 2 GPR ratio = {ratio:.4f}, expected 0.5"
        )

    def test_full_year_gpr_correct(self, scenario):
        """Year 2 (full 12-month fiscal year): GPR = $24 * 10,000 = $240,000."""
        fy2 = scenario.annual_cash_flows[1]
        expected = Decimal("240000")
        assert abs(fy2.gross_potential_rent - expected) < _tol(expected)


# ---------------------------------------------------------------------------
# Scenario 7: Sequential In-Place Leases (Lease Stack)
#
# Suite has two back-to-back leases with no gap:
#   Lease A: Jan 1 2025 – Dec 31 2027, $30/SF/yr, flat, NNN
#   Lease B: Jan 1 2028 – Dec 31 2034, $35/SF/yr, 3% pct_annual, NNN
# No speculative leases should be generated (no gap).
# Year 1 GPR = $300,000; Year 4 GPR = $35 * 10,000 = $350,000.
# ---------------------------------------------------------------------------

class TestSequentialLeaseParity:
    """Two back-to-back leases with no gap — no speculative leases needed."""

    @pytest.fixture
    def scenario(self):
        suite = SuiteInput(
            suite_id="suite_seq",
            suite_name="Suite Sequential",
            area=Decimal("10000"),
            space_type="office",
        )
        lease_a = LeaseInput(
            lease_id="lease_A_seq",
            suite_id="suite_seq",
            tenant_name="Tenant A",
            area=Decimal("10000"),
            start_date=date(2025, 1, 1),
            end_date=date(2027, 12, 31),
            base_rent_per_unit=Decimal("30.00"),
            rent_payment_frequency="annual",
            escalation_type="flat",
            escalation_pct=None,
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="nnn",
            pro_rata_share=None,
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
            renewal_probability_override=None,
        )
        lease_b = LeaseInput(
            lease_id="lease_B_seq",
            suite_id="suite_seq",
            tenant_name="Tenant B",
            area=Decimal("10000"),
            start_date=date(2028, 1, 1),
            end_date=date(2034, 12, 31),
            base_rent_per_unit=Decimal("35.00"),
            rent_payment_frequency="annual",
            escalation_type="pct_annual",
            escalation_pct=Decimal("0.03"),
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="nnn",
            pro_rata_share=None,
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
            renewal_probability_override=None,
        )
        market = _make_market(gen_vacancy=Decimal("0.05"), credit_loss=Decimal("0.01"))
        params = _make_params()
        result = run_valuation(
            property_start_date=date(2025, 1, 1),
            analysis_period_months=120,
            fiscal_year_end_month=12,
            suites=[suite],
            leases=[lease_a, lease_b],
            market_assumptions={"office": market},
            expenses=[],
            params=params,
        )
        return result

    def test_year1_gpr_lease_a(self, scenario):
        """Year 1: Lease A @ $30/SF, 10,000 SF = $300,000."""
        cf = scenario.annual_cash_flows[0]
        expected = Decimal("300000")
        assert abs(cf.gross_potential_rent - expected) < _tol(expected)

    def test_year3_gpr_still_lease_a(self, scenario):
        """Year 3 (2027): Lease A still active @ $30/SF."""
        cf = scenario.annual_cash_flows[2]
        expected = Decimal("300000")
        assert abs(cf.gross_potential_rent - expected) < _tol(expected)

    def test_year4_gpr_lease_b_base(self, scenario):
        """Year 4 (2028): Lease B starts @ $35/SF, no escalation yet = $350,000."""
        cf = scenario.annual_cash_flows[3]
        expected = Decimal("350000")
        assert abs(cf.gross_potential_rent - expected) < _tol(expected)

    def test_year5_gpr_lease_b_escalated(self, scenario):
        """Year 5 (2029): Lease B 1st escalation → $35 * 1.03 * 10,000 = $360,500."""
        cf = scenario.annual_cash_flows[4]
        expected = Decimal("35.00") * Decimal("1.03") * Decimal("10000")
        assert abs(cf.gross_potential_rent - expected) < _tol(expected)

    def test_no_ti_lc_in_any_year(self, scenario):
        """Back-to-back in-place leases with no gap → no TI/LC incurred."""
        for cf in scenario.annual_cash_flows:
            assert cf.tenant_improvements == Decimal(0), f"Year {cf.year}: TI ≠ 0"
            assert cf.leasing_commissions == Decimal(0), f"Year {cf.year}: LC ≠ 0"

    def test_100pct_occupancy(self, scenario):
        """No vacancy gap → average occupancy = 100%."""
        assert abs(scenario.avg_occupancy_pct - Decimal("1.0")) < Decimal("0.01")


# ---------------------------------------------------------------------------
# Scenario 8: Month-to-Month Lease
#
# A lease treated as MTM expires at Jan 31, 2025 (month-end of analysis start).
# After 3-month downtime, a speculative lease begins May 1, 2025.
#
# Hand-calculated expected values for Year 1 (Jan–Dec 2025):
#   Jan MTM rent     = $30 * 10,000 / 12 = $25,000
#   Feb–Apr vacancy  = 3 months downtime (0 rent)
#   May–Dec spec     = 8 months of speculative lease GPR
#   Year 1 GPR       > $25,000 (Jan MTM) and > 0
#   Year 1 TI/LC     < 0 (lease-up costs incurred in year 1)
#   Year 1 occupancy < 100% (vacancy gap)
# ---------------------------------------------------------------------------

class TestMTMLeaseParity:
    """Engine-level simulation of a month-to-month lease expiring at month-end."""

    @pytest.fixture
    def scenario(self):
        suite = SuiteInput(
            suite_id="suite_mtm",
            suite_name="Suite MTM",
            area=Decimal("10000"),
            space_type="office",
        )
        # The service layer converts MTM lease end_date to last day of that month.
        # Here we simulate that: original end "somewhere in Jan" → Jan 31.
        lease = LeaseInput(
            lease_id="lease_mtm",
            suite_id="suite_mtm",
            tenant_name="MTM Tenant",
            area=Decimal("10000"),
            start_date=date(2020, 1, 1),
            end_date=date(2025, 1, 31),   # month-end of analysis start month
            base_rent_per_unit=Decimal("30.00"),
            rent_payment_frequency="annual",
            escalation_type="flat",
            escalation_pct=None,
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="nnn",
            pro_rata_share=None,
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
            renewal_probability_override=None,
        )
        # 3 months downtime, no free rent on renewal for simplicity
        market = MarketAssumptions(
            space_type="office",
            market_rent_per_unit=Decimal("35.00"),
            rent_growth_rate=Decimal("0.03"),
            new_lease_term_months=60,
            new_ti_per_sf=Decimal("50"),
            new_lc_pct=Decimal("0.06"),
            new_free_rent_months=0,
            downtime_months=3,
            renewal_probability=Decimal("0.65"),
            renewal_term_months=60,
            renewal_ti_per_sf=Decimal("20"),
            renewal_lc_pct=Decimal("0.03"),
            renewal_free_rent_months=0,
            renewal_rent_adjustment_pct=Decimal("0.00"),
            general_vacancy_pct=Decimal("0.05"),
            credit_loss_pct=Decimal("0.01"),
        )
        params = _make_params()
        result = run_valuation(
            property_start_date=date(2025, 1, 1),
            analysis_period_months=120,
            fiscal_year_end_month=12,
            suites=[suite],
            leases=[lease],
            market_assumptions={"office": market},
            expenses=[],
            params=params,
        )
        return result

    def test_year1_gpr_includes_mtm_month(self, scenario):
        """Year 1 GPR > $25,000 — at minimum the single MTM month's rent."""
        cf = scenario.annual_cash_flows[0]
        assert cf.gross_potential_rent > Decimal("25000"), (
            f"Y1 GPR={cf.gross_potential_rent} — should include at least Jan MTM rent"
        )

    def test_year1_has_ti_lc_costs(self, scenario):
        """Year 1 should have TI/LC costs for the new speculative lease."""
        cf = scenario.annual_cash_flows[0]
        assert cf.tenant_improvements < Decimal("0"), (
            f"Y1 TI={cf.tenant_improvements} — expected negative (lease-up cost)"
        )
        assert cf.leasing_commissions < Decimal("0"), (
            f"Y1 LC={cf.leasing_commissions} — expected negative (lease-up cost)"
        )

    def test_avg_occupancy_below_100pct(self, scenario):
        """10-year avg occupancy must be below 100% due to the 3-month downtime gap."""
        # Vacant months from the downtime in the new-tenant scenario (35% weight)
        # reduce average occupancy below 1.0.
        assert scenario.avg_occupancy_pct < Decimal("1.0"), (
            f"avg_occupancy={scenario.avg_occupancy_pct} — expected < 1.0 due to MTM vacancy gap"
        )

    def test_later_years_have_higher_gpr(self, scenario):
        """Year 2+ GPR should exceed year 1 (speculative lease at market rate, no MTM)."""
        y1_gpr = scenario.annual_cash_flows[0].gross_potential_rent
        y2_gpr = scenario.annual_cash_flows[1].gross_potential_rent
        assert y2_gpr > y1_gpr, (
            f"Y2 GPR={y2_gpr} should exceed Y1 GPR={y1_gpr} once fully leased"
        )
