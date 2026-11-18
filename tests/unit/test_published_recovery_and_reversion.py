"""published DCF software options: market lease rent steps, vacancy exclusion switches, calendar-year recoveries,
recovery cap groups and growth caps, and reversion NOI adjusted for full occupancy."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import ExpenseRecoveryOverride, SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_growth_schedules import _expense, _flat_lease
from tests.unit.test_leasing_costs_and_loss_base import _rollover_market, _run

D = Decimal


class TestMarketLeaseRentSteps:
    def test_step_raises_rent_and_lc(self):
        # Renewal Jan 2027 at $30, no growth: up 10% from lease month 25 (Jan 2029)
        cfs = _run(market=_rollover_market(lease_rent_steps=((25, D("0.10")),))).annual_cash_flows
        assert cfs[3].gross_potential_rent == pytest.approx(D(300000))
        assert cfs[4].gross_potential_rent == pytest.approx(D(330000))
        assert -cfs[2].leasing_commissions == pytest.approx(D(300000) * D("5.3") * D("0.04"))


class TestVacancyExclusion:
    def _market(self, **kw):
        return _rollover_market(general_vacancy_pct=D("0.05"), **kw)

    def test_exclusion_ends_at_rollover_by_default(self):
        lease = _flat_lease(end_date=date(2026, 12, 31), exclude_from_general_vacancy=True)
        cfs = _run(lease, market=self._market()).annual_cash_flows
        assert cfs[0].general_vacancy_loss == 0
        assert cfs[3].general_vacancy_loss == pytest.approx(D(-15000))

    def test_exclusion_carries_to_market_leases_when_switched_off(self):
        lease = _flat_lease(end_date=date(2026, 12, 31), exclude_from_general_vacancy=True,
                            vacancy_exclusion_ends_at_rollover=False)
        cfs = _run(lease, market=self._market()).annual_cash_flows
        assert all(cf.general_vacancy_loss == 0 for cf in cfs)

    def test_market_profile_excludes_its_suites(self):
        lease = _flat_lease(end_date=date(2026, 12, 31))
        cfs = _run(lease, market=self._market(exclude_from_general_vacancy=True)).annual_cash_flows
        assert all(cf.general_vacancy_loss == 0 for cf in cfs)


class TestCalendarYearRecoveries:
    def test_recoveries_bill_on_calendar_years(self):
        # Fiscal years end June; taxes $100,000 in Year 1 growing 3%
        suite = SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office")
        lease = _flat_lease(start_date=date(2025, 7, 1), end_date=date(2034, 6, 30), recovery_type="nnn")
        r = run_valuation(
            property_start_date=date(2025, 7, 1), analysis_period_months=36, fiscal_year_end_month=6,
            suites=[suite], leases=[lease], market_assumptions={"office": _make_market()},
            expenses=[_expense(is_recoverable=True)],
            params=replace(_make_params(), calendar_year_recoveries=True),
        )
        # Calendar 2026: half Year 1 + half Year 2 = 101,500; calendar 2027: 104,545
        assert r.annual_cash_flows[1].expense_recoveries == pytest.approx((D(101500) + D(104545)) / 2)


    def test_base_year_before_analysis_is_its_calendar_year_expense(self):
        # Fiscal years end June; base year 2023 predates the analysis. Its stop is calendar 2023:
        # half of Year -2 and half of Year -1, deflated at 3%.
        suite = SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office")
        lease = _flat_lease(start_date=date(2023, 1, 1), end_date=date(2034, 6, 30),
                            recovery_type="base_year_stop", base_year=2023)
        r = run_valuation(
            property_start_date=date(2025, 7, 1), analysis_period_months=36, fiscal_year_end_month=6,
            suites=[suite], leases=[lease], market_assumptions={"office": _make_market()},
            expenses=[_expense(is_recoverable=True)],
            params=replace(_make_params(), calendar_year_recoveries=True),
        )
        g = D("1.03")
        stop = (D(100000) / g ** 3 + D(100000) / g ** 2) / 2
        cal_2025 = (D(100000) / g + D(100000)) / 2
        cal_2026 = (D(100000) + D(103000)) / 2
        assert r.annual_cash_flows[0].expense_recoveries == pytest.approx((cal_2025 - stop + cal_2026 - stop) / 2)

class TestRecoveryCapGroups:
    def _expenses(self):
        return [_expense(expense_id="C", category="cam", base_amount=D(50000), growth_rate=D("0.05"),
                         is_recoverable=True),
                _expense(expense_id="I", category="insurance", base_amount=D(30000), growth_rate=D("0.05"),
                         is_recoverable=True)]

    def _lease(self, **cap):
        overrides = tuple(ExpenseRecoveryOverride(expense_category=cat, recovery_type="nnn",
                                                  base_year_stop_amount=None, cap_per_sf_annual=None,
                                                  floor_per_sf_annual=None, admin_fee_pct=None)
                          for cat in ("cam", "insurance"))
        overrides = tuple(replace(o, **cap) for o in overrides)
        return _flat_lease(recovery_type="nnn", recovery_overrides=overrides)

    def test_group_shares_one_per_sf_cap(self):
        separate = self._lease(cap_per_sf_annual=D(6))
        grouped = self._lease(cap_per_sf_annual=D(6), cap_group="cam_ins")
        assert _run(separate, expenses=self._expenses()).annual_cash_flows[0].expense_recoveries == pytest.approx(
            D(80000))
        assert _run(grouped, expenses=self._expenses()).annual_cash_flows[0].expense_recoveries == pytest.approx(
            D(60000))

    def test_growth_cap_from_lease_start_year(self):
        cfs = _run(self._lease(cap_group="cam_ins", cap_growth_pct=D("0.02")),
                   expenses=self._expenses()).annual_cash_flows
        assert cfs[0].expense_recoveries == pytest.approx(D(80000))
        assert cfs[1].expense_recoveries == pytest.approx(D(81600))


class TestFullOccupancyReversion:
    def test_forward_noi_fills_downtime_at_market_without_general_vacancy(self):
        # Lease expires Dec 2029; the new tenant starts after 6 months down with 3 months free.
        # Full occupancy: all of Year 6 at market rent, less the free rent, no general vacancy.
        lease = _flat_lease(end_date=date(2029, 12, 31))
        market = _make_market(renewal_prob=D(0), credit_loss=D(0))
        plain = _run(lease, market=market)
        full = _run(lease, market=market, exit_noi_full_occupancy=True)
        rent = D(35) * D("1.03") ** 5 * 10000
        assert full.terminal_noi_basis == pytest.approx(rent * 9 / 12)
        # As projected, Year 6 loses the six months of downtime and pays general vacancy
        assert full.terminal_noi_basis - plain.terminal_noi_basis > rent * 6 / 12


class TestPartialMonthVacancy:
    def test_downtime_between_mid_month_dates_is_prorated(self):
        # Lease ends Apr 6 2027 with 6 months down: vacant Apr 7 - Oct 6, so 24/30 of April and
        # 6/31 of October count, not the whole of both months
        lease = _flat_lease(end_date=date(2027, 4, 6))
        market = replace(_make_market(renewal_prob=D(0), gen_vacancy=D(0), credit_loss=D(0)), rent_growth_rate=D(0))
        y3 = _run(lease, market=market).annual_cash_flows[2]
        months = D(24) / 30 + 5 + D(6) / 31
        assert y3.absorption_vacancy == pytest.approx(D(-35) * 10000 / 12 * months)
