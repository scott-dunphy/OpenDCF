from datetime import date
from dataclasses import replace
from decimal import Decimal

from src.engine.property_cashflow import run_valuation
from src.engine.types import LeaseInput, MarketAssumptions, SuiteInput, ValuationParams


def _params(total_units: Decimal) -> ValuationParams:
    return ValuationParams(
        discount_rate=Decimal("0.08"),
        exit_cap_rate=Decimal("0.06"),
        exit_cap_year=-1,
        exit_costs_pct=Decimal("0.00"),
        capital_reserves_per_unit=Decimal("0"),
        total_property_area=total_units,
        use_mid_year_convention=False,
        loan_amount=None,
        interest_rate=None,
        amortization_months=None,
        loan_term_months=None,
        io_period_months=0,
    )


def _market(
    *,
    renewal_probability: Decimal,
    new_free_rent_months: int,
    renewal_free_rent_months: int,
) -> MarketAssumptions:
    return MarketAssumptions(
        space_type="one_bed",
        market_rent_per_unit=Decimal("1000"),
        rent_growth_rate=Decimal("0"),
        new_lease_term_months=12,
        new_ti_per_sf=Decimal("0"),
        new_lc_pct=Decimal("0"),
        new_free_rent_months=new_free_rent_months,
        downtime_months=0,
        renewal_probability=renewal_probability,
        renewal_term_months=12,
        renewal_ti_per_sf=Decimal("0"),
        renewal_lc_pct=Decimal("0"),
        renewal_free_rent_months=renewal_free_rent_months,
        renewal_rent_adjustment_pct=Decimal("0"),
        general_vacancy_pct=Decimal("0"),
        credit_loss_pct=Decimal("0"),
        rent_payment_frequency="monthly",
    )


def test_multifamily_market_occupancy_applies_blended_concessions():
    suites = [
        SuiteInput(
            suite_id="u1",
            suite_name="Unit Type 1BR",
            area=Decimal("100"),
            space_type="one_bed",
        )
    ]
    market = _market(
        renewal_probability=Decimal("0.60"),
        new_free_rent_months=2,
        renewal_free_rent_months=1,
    )

    result = run_valuation(
        property_start_date=date(2026, 1, 1),
        analysis_period_months=12,
        fiscal_year_end_month=12,
        suites=suites,
        leases=[],
        market_assumptions={"one_bed": market},
        expenses=[],
        params=_params(total_units=Decimal("100")),
        property_type="multifamily",
    )

    cf = result.annual_cash_flows[0]
    # Annual GPR = 100 units * $1,000/mo * 12
    assert abs(cf.gross_potential_rent - Decimal("1200000")) < Decimal("0.01")

    # Blended concession months per unit-year:
    # (1-0.60)*2 + 0.60*1 = 1.4 months
    # Free rent = -(1.4/12) * annual GPR = -140,000
    assert abs(cf.free_rent - Decimal("-140000")) < Decimal("0.5")
    assert abs(cf.net_operating_income - Decimal("1060000")) < Decimal("0.5")


def test_multifamily_market_occupancy_no_concessions_when_months_zero():
    suites = [
        SuiteInput(
            suite_id="u1",
            suite_name="Unit Type 1BR",
            area=Decimal("100"),
            space_type="one_bed",
        )
    ]
    market = _market(
        renewal_probability=Decimal("0.60"),
        new_free_rent_months=0,
        renewal_free_rent_months=0,
    )

    result = run_valuation(
        property_start_date=date(2026, 1, 1),
        analysis_period_months=12,
        fiscal_year_end_month=12,
        suites=suites,
        leases=[],
        market_assumptions={"one_bed": market},
        expenses=[],
        params=_params(total_units=Decimal("100")),
        property_type="multifamily",
    )

    cf = result.annual_cash_flows[0]
    assert abs(cf.free_rent - Decimal("0")) < Decimal("0.01")


def test_multifamily_market_occupancy_timed_concessions_by_year():
    suites = [
        SuiteInput(
            suite_id="u1",
            suite_name="Unit Type 1BR",
            area=Decimal("100"),
            space_type="one_bed",
        )
    ]
    market = _market(
        renewal_probability=Decimal("0.60"),
        new_free_rent_months=2,
        renewal_free_rent_months=1,
    )
    market = replace(
        market,
        concession_timing_mode="timed",
        concession_year1_months=Decimal("2.0"),
        concession_year2_months=Decimal("1.0"),
        concession_stabilized_months=Decimal("0.5"),
    )

    result = run_valuation(
        property_start_date=date(2026, 1, 1),
        analysis_period_months=24,
        fiscal_year_end_month=12,
        suites=suites,
        leases=[],
        market_assumptions={"one_bed": market},
        expenses=[],
        params=_params(total_units=Decimal("100")),
        property_type="multifamily",
    )

    y1, y2 = result.annual_cash_flows
    # Annual GPR each year = 100 units * $1,000/mo * 12
    assert abs(y1.gross_potential_rent - Decimal("1200000")) < Decimal("0.01")
    assert abs(y2.gross_potential_rent - Decimal("1200000")) < Decimal("0.01")

    # Timed mode should override blended:
    # Y1: 2.0 months => -(2/12)*1,200,000 = -200,000
    # Y2: 1.0 month  => -(1/12)*1,200,000 = -100,000
    assert abs(y1.free_rent - Decimal("-200000")) < Decimal("0.5")
    assert abs(y2.free_rent - Decimal("-100000")) < Decimal("0.5")


def test_multifamily_in_place_months_also_receive_concession_drag():
    suites = [
        SuiteInput(
            suite_id="u1",
            suite_name="Unit Type 1BR",
            area=Decimal("100"),
            space_type="one_bed",
        )
    ]
    market = _market(
        renewal_probability=Decimal("0.50"),
        new_free_rent_months=2,
        renewal_free_rent_months=1,
    )
    # Blended concession months = 1.5 months/year.
    leases = [
        LeaseInput(
            lease_id="l1",
            suite_id="u1",
            tenant_name="InPlace Tenant",
            area=Decimal("100"),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            base_rent_per_unit=Decimal("1000"),
            rent_payment_frequency="monthly",
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
            renewal_probability_override=None,
        )
    ]

    result = run_valuation(
        property_start_date=date(2026, 1, 1),
        analysis_period_months=12,
        fiscal_year_end_month=12,
        suites=suites,
        leases=leases,
        market_assumptions={"one_bed": market},
        expenses=[],
        params=_params(total_units=Decimal("100")),
        property_type="multifamily",
    )

    cf = result.annual_cash_flows[0]
    # Annual GPR = 100 * 1000 * 12 = 1,200,000
    # Free rent from concession drag = -(1.5/12) * 1,200,000 = -150,000
    assert abs(cf.gross_potential_rent - Decimal("1200000")) < Decimal("0.01")
    assert abs(cf.free_rent - Decimal("-150000")) < Decimal("0.5")
