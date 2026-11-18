"""Monthly cash flows: same waterfall in one-month buckets, reconciling to annual."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.engine.date_utils import build_analysis_period, build_monthly_buckets
from src.engine.property_cashflow import run_valuation
from src.engine.types import ExpenseInput, LeaseInput, SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params

FIELDS = [
    "gross_potential_rent", "free_rent", "absorption_vacancy", "expense_recoveries",
    "general_vacancy_loss", "credit_loss", "effective_gross_income", "operating_expenses",
    "net_operating_income", "tenant_improvements", "leasing_commissions", "cash_flow_before_debt",
    "debt_service", "levered_cash_flow",
]


@pytest.fixture(scope="module")
def result():
    suite = SuiteInput(suite_id="s1", suite_name="Suite 100", area=Decimal("10000"), space_type="office")
    lease = LeaseInput(
        lease_id="l1", suite_id="s1", tenant_name="Tenant", area=Decimal("10000"),
        start_date=date(2023, 1, 1), end_date=date(2027, 6, 30),
        base_rent_per_unit=Decimal("30.00"), rent_payment_frequency="annual",
        escalation_type="flat", escalation_pct=None, cpi_floor=None, cpi_cap=None,
        rent_steps=(), free_rent_periods=(), recovery_type="nnn", pro_rata_share=None,
        base_year_stop_amount=None, expense_stop_per_sf=None, recovery_overrides=(),
        pct_rent_breakpoint=None, pct_rent_rate=None, renewal_probability_override=None,
    )
    expense = ExpenseInput(
        expense_id="e1", category="real_estate_taxes", base_amount=Decimal("100000"),
        growth_rate=Decimal("0.03"), is_recoverable=True, is_gross_up_eligible=False,
        gross_up_vacancy_pct=None, is_pct_of_egi=False, pct_of_egi=None,
    )
    params = replace(
        _make_params(),
        loan_amount=Decimal("2000000"), interest_rate=Decimal("0.06"),
        amortization_months=360, loan_term_months=60, io_period_months=12,
    )
    return run_valuation(
        property_start_date=date(2025, 1, 1), analysis_period_months=120, fiscal_year_end_month=12,
        suites=[suite], leases=[lease], market_assumptions={"office": _make_market()},
        expenses=[expense], params=params, include_monthly=True,
    )


def test_monthly_buckets_keep_analysis_year():
    period = build_analysis_period(date(2025, 1, 1), 24, 12)
    assert len(build_monthly_buckets(period).fiscal_years) == 24
    assert build_monthly_buckets(period).fiscal_years[13].year_number == 2


def test_one_row_per_month(result):
    assert len(result.monthly_cash_flows) == 120
    assert result.monthly_cash_flows[0].period_start == date(2025, 1, 1)
    assert result.monthly_cash_flows[0].period_end == date(2025, 1, 31)
    assert result.monthly_cash_flows[13].year == 2


def test_months_sum_to_years(result):
    for cf in result.annual_cash_flows:
        months = [m for m in result.monthly_cash_flows if m.year == cf.year]
        assert len(months) == 12
        for name in FIELDS:
            total = sum((getattr(m, name) for m in months), Decimal(0))
            assert abs(total - getattr(cf, name)) < Decimal("0.01"), (cf.year, name)


def test_expiry_lands_in_the_right_month(result):
    june, july = result.monthly_cash_flows[29], result.monthly_cash_flows[30]
    assert june.period_start == date(2027, 6, 1)
    assert june.absorption_vacancy == Decimal(0)
    assert july.absorption_vacancy < Decimal(0)   # weighted downtime starts after expiry
    assert july.gross_potential_rent < june.gross_potential_rent


def test_debt_service_by_month(result):
    io_month, amort_month = result.monthly_cash_flows[0], result.monthly_cash_flows[12]
    assert abs(-io_month.debt_service - Decimal("10000")) < Decimal("0.01")   # 2M x 6% / 12
    assert -amort_month.debt_service > -io_month.debt_service
    assert result.monthly_cash_flows[59].debt_service < amort_month.debt_service * 10  # balloon month
    assert result.monthly_cash_flows[60].debt_service == Decimal(0)


def test_monthly_vacancy_frequency_preserves_each_months_zero_floor():
    suite = SuiteInput(
        suite_id="s", suite_name="Vacant then leased", area=Decimal("10000"), space_type="office",
        absorption_start_date=date(2025, 1, 1), lease_up_months=6,
    )
    lease = LeaseInput(
        lease_id="l", suite_id="s", tenant_name="Tenant", area=Decimal("10000"),
        start_date=date(2025, 7, 1), end_date=date(2030, 6, 30),
        base_rent_per_unit=Decimal("30"), rent_payment_frequency="annual", escalation_type="flat",
        escalation_pct=None, cpi_floor=None, cpi_cap=None, rent_steps=(), free_rent_periods=(),
        recovery_type="none", pro_rata_share=None, base_year_stop_amount=None, expense_stop_per_sf=None,
        recovery_overrides=(), pct_rent_breakpoint=None, pct_rent_rate=None,
    )
    common = dict(
        property_start_date=date(2025, 1, 1), analysis_period_months=12, fiscal_year_end_month=12,
        suites=[suite], leases=[lease], market_assumptions={"office": _make_market()}, expenses=[],
    )
    annual = run_valuation(
        **common,
        params=replace(_make_params(), reduce_general_vacancy_by_downtime=True,
                       vacancy_on_gross_revenue=True, vacancy_calculation_frequency="annual"),
    )
    monthly = run_valuation(
        **common,
        params=replace(_make_params(), reduce_general_vacancy_by_downtime=True,
                       vacancy_on_gross_revenue=True, vacancy_calculation_frequency="monthly"),
    )

    assert annual.annual_cash_flows[0].general_vacancy_loss == 0
    assert monthly.annual_cash_flows[0].general_vacancy_loss < 0
    assert sum((m.general_vacancy_loss for m in monthly.monthly_cash_flows), Decimal(0)) == monthly.annual_cash_flows[0].general_vacancy_loss
