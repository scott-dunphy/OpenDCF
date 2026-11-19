"""Market lease commencement rounded forward to the first of the next month (round_start_to_month)."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from src.engine.date_utils import build_analysis_period
from src.engine.renewal_engine import generate_speculative_leases
from tests.unit.test_renewal_engine import make_market, make_suite

ANALYSIS = build_analysis_period(date(2025, 1, 1), 36, 12)


def _run(market, vacancy=date(2025, 4, 15), **kw):
    return generate_speculative_leases(
        suite=make_suite(), vacancy_start_date=vacancy, analysis=ANALYSIS, market=market, **kw)


def _vacant_through(slices) -> date:
    vacant = [s for s in slices if s.is_vacant]
    last = max(vacant, key=lambda s: s.period_start)
    return last.period_end if last.month_fraction == 1 else None


def _market(**kw):
    return make_market(new_term=60, new_free_rent=0, renewal_free_rent=0, **kw)


def test_mid_month_start_rounds_to_next_month_with_vacancy_through_month_end():
    m = replace(_market(renewal_prob=0.0, downtime=4), round_start_to_month=True)
    slices, leases = _run(m)
    assert leases[0].start_date == date(2025, 9, 1)
    assert _vacant_through(slices) == date(2025, 8, 31)
    aug = [s for s in slices if s.period_start == date(2025, 8, 1)]
    assert len(aug) == 1 and aug[0].is_vacant and aug[0].month_fraction == 1
    sep = [s for s in slices if s.period_start == date(2025, 9, 1)]
    assert len(sep) == 1 and not sep[0].is_vacant and sep[0].base_rent > 0


def test_flag_off_keeps_mid_month_start():
    m = _market(renewal_prob=0.0, downtime=4)
    _, leases = _run(m)
    assert leases[0].start_date == date(2025, 8, 15)


def test_start_on_first_of_month_unchanged():
    m = _market(renewal_prob=0.4, downtime=4)
    off = _run(m, vacancy=date(2025, 4, 1))
    on = _run(replace(m, round_start_to_month=True), vacancy=date(2025, 4, 1))
    assert on == off


def test_tree_renewal_branch_not_rounded():
    m = replace(_market(renewal_prob=0.6, downtime=4), round_start_to_month=True)
    _, leases = _run(m)
    starts = {lse.lease_id.split("_")[1]: lse.start_date for lse in leases if lse.lease_id.endswith(("_R", "_N"))}
    assert starts == {"renew": date(2025, 4, 15), "new": date(2025, 9, 1)}


def test_tree_new_tenant_zero_downtime_rounds_with_stub_vacancy():
    m = replace(_market(renewal_prob=0.0, downtime=0), round_start_to_month=True)
    slices, leases = _run(m)
    assert leases[0].start_date == date(2025, 5, 1)
    vacant = [s for s in slices if s.is_vacant]
    assert len(vacant) == 1 and vacant[0].month_fraction == Decimal(16) / Decimal(30)


def test_blended_rollover_rounds_start():
    # 50% renewal x 0 + 50% new x 6 = 3 months weighted downtime: Apr 15 -> Jul 15 -> Aug 1
    m = replace(_market(renewal_prob=0.5, downtime=6), rollover_method="blended", round_start_to_month=True)
    slices, leases = _run(m)
    assert leases[0].start_date == date(2025, 8, 1)
    assert _vacant_through(slices) == date(2025, 7, 31)
    _, off_leases = _run(replace(m, round_start_to_month=False))
    assert off_leases[0].start_date == date(2025, 7, 15)


def test_blended_zero_downtime_still_rounds_with_stub_vacancy():
    m = replace(_market(renewal_prob=1.0, downtime=6), rollover_method="blended", round_start_to_month=True)
    slices, leases = _run(m)
    assert leases[0].start_date == date(2025, 5, 1)
    vacant = [s for s in slices if s.is_vacant]
    assert len(vacant) == 1 and vacant[0].period_start == date(2025, 4, 1)
    assert vacant[0].month_fraction == Decimal(16) / Decimal(30)
