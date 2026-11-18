from datetime import date
from decimal import Decimal

from src.engine.property_cashflow import run_valuation
from src.engine.types import LeaseInput, MarketAssumptions, SuiteInput, ValuationParams


def _base_inputs(exit_cap_year: int) -> tuple[list[SuiteInput], list[LeaseInput], dict[str, MarketAssumptions], ValuationParams]:
    suites = [
        SuiteInput(
            suite_id="suite_1",
            suite_name="Suite 1",
            area=Decimal("1000"),
            space_type="office",
        )
    ]
    leases = [
        LeaseInput(
            lease_id="lease_1",
            suite_id="suite_1",
            tenant_name="Tenant A",
            area=Decimal("1000"),
            start_date=date(2025, 1, 1),
            end_date=date(2034, 12, 31),
            base_rent_per_unit=Decimal("10.00"),
            rent_payment_frequency="annual",
            escalation_type="flat",
            escalation_pct=None,
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="none",
            pro_rata_share=None,
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
        )
    ]
    market = {
        "office": MarketAssumptions(
            space_type="office",
            market_rent_per_unit=Decimal("30.00"),
            rent_growth_rate=Decimal("0"),
            new_lease_term_months=60,
            new_ti_per_sf=Decimal("0"),
            new_lc_pct=Decimal("0"),
            new_free_rent_months=0,
            downtime_months=0,
            renewal_probability=Decimal("1"),
            renewal_term_months=60,
            renewal_ti_per_sf=Decimal("0"),
            renewal_lc_pct=Decimal("0"),
            renewal_free_rent_months=0,
            renewal_rent_adjustment_pct=Decimal("0"),
            general_vacancy_pct=Decimal("0"),
            credit_loss_pct=Decimal("0"),
        )
    }
    params = ValuationParams(
        discount_rate=Decimal("0.08"),
        exit_cap_rate=Decimal("0.10"),
        exit_cap_year=exit_cap_year,
        exit_costs_pct=Decimal("0"),
        capital_reserves_per_unit=Decimal("0"),
        total_property_area=Decimal("1000"),
        use_mid_year_convention=False,
        loan_amount=None,
        interest_rate=None,
        amortization_months=None,
        loan_term_months=None,
        io_period_months=0,
    )
    return suites, leases, market, params


def test_terminal_value_uses_hold_plus_one_noi_when_exit_cap_year_is_forward():
    suites, leases, market, params = _base_inputs(exit_cap_year=-1)
    result = run_valuation(
        property_start_date=date(2025, 1, 1),
        analysis_period_months=120,
        fiscal_year_end_month=12,
        suites=suites,
        leases=leases,
        market_assumptions=market,
        expenses=[],
        params=params,
    )

    # Year 10 NOI is based on in-place rent: 10 * 1000 = 10,000
    assert abs(result.annual_cash_flows[-1].net_operating_income - Decimal("10000")) < Decimal("0.01")
    # Year 11 NOI should re-lease to market: 30 * 1000 = 30,000
    expected_terminal = Decimal("30000") / Decimal("0.10")
    assert abs(result.terminal_value - expected_terminal) < Decimal("0.01")


def test_terminal_value_uses_explicit_year_when_exit_cap_year_is_set():
    suites, leases, market, params = _base_inputs(exit_cap_year=10)
    result = run_valuation(
        property_start_date=date(2025, 1, 1),
        analysis_period_months=120,
        fiscal_year_end_month=12,
        suites=suites,
        leases=leases,
        market_assumptions=market,
        expenses=[],
        params=params,
    )

    expected_terminal = Decimal("10000") / Decimal("0.10")
    assert abs(result.terminal_value - expected_terminal) < Decimal("0.01")
