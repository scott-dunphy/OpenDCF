"""Year-by-year vacancy, credit loss, renewal probability and downtime (used by Monte Carlo paths)."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from tests.integration.test_engine_parity import _make_market
from tests.unit.test_growth_schedules import _flat_lease, _run

D = Decimal


def _noi(r):
    return [cf.net_operating_income for cf in r.annual_cash_flows]


class TestVacancyAndCreditSchedules:
    def test_vacancy_schedule_by_year(self):
        m = _make_market()
        flat = _run(_flat_lease(), market=m)
        sched = _run(_flat_lease(), market=replace(m, general_vacancy_schedule=(D("0.05"), D("0.15"))))
        a, b = flat.annual_cash_flows, sched.annual_cash_flows
        assert b[0].general_vacancy_loss == a[0].general_vacancy_loss
        # Year 2 onward: 15% instead of 5% (the last entry carries forward)
        for y in (1, 4):
            assert b[y].general_vacancy_loss == a[y].general_vacancy_loss * 3

    def test_credit_loss_schedule(self):
        m = _make_market()
        flat = _run(_flat_lease(), market=m)
        sched = _run(_flat_lease(), market=replace(m, credit_loss_schedule=(D("0.01"), D("0.03"))))
        assert sched.annual_cash_flows[2].credit_loss == flat.annual_cash_flows[2].credit_loss * 3

    def test_one_entry_schedules_match_single_values(self):
        m = _make_market()
        same = replace(m, general_vacancy_schedule=(m.general_vacancy_pct,),
                       credit_loss_schedule=(m.credit_loss_pct,),
                       renewal_probability_schedule=(m.renewal_probability,),
                       downtime_schedule=(m.downtime_months,))
        lease = _flat_lease(end_date=date(2026, 12, 31))
        assert _noi(_run(lease, market=m)) == _noi(_run(lease, market=same))


class TestLeasingSchedules:
    def test_renewal_probability_by_expiry_year(self):
        # Lease expires at the end of Year 2: only the Year 3 entry (first day of vacancy) matters
        lease = _flat_lease(end_date=date(2026, 12, 31))
        m = _make_market()
        sched = replace(m, renewal_probability_schedule=(D("1"), D("1"), D("0")))
        assert _noi(_run(lease, market=sched)) == _noi(_run(lease, market=replace(m, renewal_probability=D("0"))))

    def test_downtime_by_expiry_year(self):
        lease = _flat_lease(end_date=date(2026, 12, 31))
        m = replace(_make_market(), renewal_probability=D("0"))
        sched = replace(m, downtime_schedule=(0, 0, 12))
        assert _noi(_run(lease, market=sched)) == _noi(_run(lease, market=replace(m, downtime_months=12)))
        assert _noi(_run(lease, market=sched)) != _noi(_run(lease, market=m))
