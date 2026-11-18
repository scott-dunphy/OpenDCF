"""published DCF software base-year recoveries (market leases' own base year, base year at the expense incurred, annual
occupancy, management fee over the base year), free rent by year, and space vacant until its first lease."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import RentStepInput, SuiteInput
from tests.integration.test_engine_parity import _make_params
from tests.unit.test_growth_schedules import _expense, _flat_lease
from tests.unit.test_leasing_costs_and_loss_base import _rollover_market, _run

D = Decimal


def _base_year_lease(**kw):
    return _flat_lease(recovery_type="base_year_stop", base_year=2025, **kw)


def _two_suites(second_start, expenses, months=24):
    """Suite A leased throughout on a 2025 base year; suite B vacant until its lease starts."""
    suites = [SuiteInput(suite_id=s, suite_name=s, area=D(5000), space_type="office") for s in ("A", "B")]
    leases = [_base_year_lease(lease_id="A", suite_id="A", area=D(5000)),
              _base_year_lease(lease_id="B", suite_id="B", area=D(5000), start_date=second_start)]
    return run_valuation(
        property_start_date=date(2025, 1, 1), analysis_period_months=months, fiscal_year_end_month=12,
        suites=suites, leases=leases, market_assumptions={"office": _rollover_market()}, expenses=expenses,
        params=replace(_make_params(), apply_stabilized_gross_up=False),
    )


class TestMarketLeaseBaseYear:
    def test_market_lease_takes_its_start_year_as_base_year(self):
        # Base-year lease expires Dec 2026 and renews at market Jan 2027 on a 2027 base year
        lease = _base_year_lease(end_date=date(2026, 12, 31))
        taxes = _expense(is_recoverable=True)          # $100,000 growing 3%
        cfs = _run(lease, market=_rollover_market(), expenses=[taxes]).annual_cash_flows
        assert cfs[1].expense_recoveries == pytest.approx(D(100000) * D("0.03"))
        assert cfs[2].expense_recoveries == 0
        assert cfs[3].expense_recoveries == pytest.approx(D(100000) * (D("1.03") ** 3 - D("1.03") ** 2))


class TestFreeRentSchedule:
    @pytest.mark.parametrize("schedule, months", [((D(2), D(2), D(2)), 2), ((D(2), D(2), D(0)), 0)])
    def test_free_rent_by_year_the_lease_starts(self, schedule, months):
        # Renewal starts Jan 2027 (Year 3) at $30: $25,000 a month
        m = _rollover_market(renewal_free_rent_months=2, renewal_free_rent_schedule=schedule)
        y3 = _run(market=m).annual_cash_flows[2]
        assert -y3.free_rent == pytest.approx(D(25000) * months)


class TestVacantUntilFirstLease:
    def test_no_market_leasing_before_a_signed_lease(self):
        lease = _flat_lease(start_date=date(2025, 7, 1))
        y1 = _run(lease, market=_rollover_market(renewal_free_rent_months=2)).annual_cash_flows[0]
        assert y1.gross_potential_rent == pytest.approx(D(25000) * 6)
        assert y1.absorption_vacancy == 0 and y1.free_rent == 0 and y1.tenant_improvements == 0


class TestBaseYearStop:
    def test_stop_is_the_expense_the_base_year_incurred_at_its_average_occupancy(self):
        # Half variable, $100,000 at full occupancy. 2025: B leases from July, so occupancy averages
        # 75% and the expense is 100,000 x (0.5 + 0.5 x 0.75) = 87,500; 2026 is full, 100,000.
        cleaning = _expense(category="cleaning", growth_rate=D(0), is_recoverable=True, variable_pct=D("0.5"))
        cfs = _two_suites(date(2025, 7, 1), [cleaning]).annual_cash_flows
        assert -cfs[0].expense_detail["cleaning"] == pytest.approx(D(87500))
        # A's 2025 share is its base year (no month-by-month recovery); in 2026 A and B each pay
        # half the increase over 87,500
        assert cfs[0].expense_recoveries == 0
        assert cfs[1].expense_recoveries == pytest.approx(D(12500))

    def test_management_fee_increase_over_the_base_year(self):
        # Rent rises from $30 to $40 in 2026; the 3% fee rises from 9,000 and the tenant pays the increase
        lease = _base_year_lease(escalation_type="fixed_step",
                                 rent_steps=(RentStepInput(date(2026, 1, 1), D(40)),))
        fee = _expense(category="management_fee", base_amount=D(0), growth_rate=D(0), is_recoverable=True,
                       is_pct_of_egi=True, pct_of_egi=D("0.03"))
        cfs = _run(lease, market=_rollover_market(), expenses=[fee]).annual_cash_flows
        assert cfs[0].expense_recoveries == 0
        # fee = 3% x (400,000 + fee - 9,000)
        fee_y2 = D("0.03") * D(391000) / D("0.97")
        assert cfs[1].expense_recoveries == pytest.approx(fee_y2 - 9000, rel=D("0.001"))
