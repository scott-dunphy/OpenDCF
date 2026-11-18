"""Occupancy basis of recoveries: day-weighted occupancy, pool gross-up over the included suites,
calendar-year occupancy for calendar recoveries, and pre-analysis base years in deducting pools."""
from collections import defaultdict
from dataclasses import replace
from datetime import date
from decimal import Decimal

from src.engine.property_cashflow import run_valuation
from src.engine.types import RecoveryPoolInput, SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_growth_schedules import _expense, _flat_lease
from tests.unit.test_leasing_costs_and_loss_base import _rollover_market

D = Decimal
# Anchor 50,000 SF and two 10,000 SF inline suites: 70,000 SF
SUITES = [
    SuiteInput(suite_id="A", suite_name="Anchor", area=D("50000"), space_type="anchor"),
    SuiteInput(suite_id="I1", suite_name="101", area=D("10000"), space_type="inline"),
    SuiteInput(suite_id="I2", suite_name="102", area=D("10000"), space_type="inline"),
]


def _cam(**kw):
    base = dict(category="cam", base_amount=D(700000), growth_rate=D("0"), is_recoverable=True)
    base.update(kw)
    return _expense(**base)


def _market(space_type, **kw):
    return replace(_make_market(space_type=space_type), **kw)


def _pool(**kw):
    return RecoveryPoolInput(pool_id="P", name="CAM pool", expense_categories=("cam",), **kw)


def _run(leases, pools=(), expenses=None, market=None, months=36, suites=SUITES, total_area=D("70000"), **params_kw):
    params = replace(_make_params(total_area=total_area), **params_kw)
    return run_valuation(
        property_start_date=date(2025, 1, 1), analysis_period_months=months, fiscal_year_end_month=12,
        suites=suites, leases=leases, market_assumptions=market or {},
        expenses=expenses or [_cam()], params=params, recovery_pools=tuple(pools),
    )


def _rec(result, suite_id, year):
    return next((d.expense_recovery for d in result.suite_annual_details
                 if d.suite_id == suite_id and d.year == year), D(0))


def _total_rec(result, year):
    return sum((_rec(result, s.suite_id, year) for s in SUITES), D(0))


def _anchor(**kw):
    return _flat_lease(lease_id="LA", suite_id="A", area=D("50000"), recovery_type="nnn", **kw)


def _inline(lease_id, suite_id, **kw):
    return _flat_lease(lease_id=lease_id, suite_id=suite_id, area=D("10000"), recovery_type="nnn", **kw)


# --- Day-weighted occupancy (a lease ending or starting mid-month) ---

def test_mid_month_renewal_counts_the_suite_once_in_property_occupancy():
    """I1 ends 6/14 and renews 6/15; I2 is dark all year: occupancy is 50% every day, so a fully
    variable CAM of 100,000 at full occupancy incurs 50,000."""
    suites = [SuiteInput(suite_id="I1", suite_name="1", area=D("10000"), space_type="inline"),
              SuiteInput(suite_id="I2", suite_name="2", area=D("10000"), space_type="dark")]
    market = {"inline": _market("inline", renewal_probability=D("1"), downtime_months=0,
                                new_free_rent_months=0, renewal_free_rent_months=0)}
    lease = _inline("L1", "I1", end_date=date(2025, 6, 14))
    r = _run([lease], expenses=[_cam(base_amount=D(100000), variable_pct=D("1"))], market=market,
             months=24, suites=suites, total_area=D("20000"), apply_stabilized_gross_up=False)
    assert (-r.annual_cash_flows[0].expense_detail["cam"]).quantize(D("0.01")) == D("50000.00")
    assert _rec(r, "I1", 1).quantize(D("0.01")) == D("25000.00")  # half the area


def test_occupied_area_pool_recovers_the_whole_expense_across_a_mid_month_renewal():
    suites = [*SUITES[:2], SuiteInput(suite_id="I2", suite_name="102", area=D("10000"), space_type="other")]
    market = {"inline": _market("inline", renewal_probability=D("1"), renewal_free_rent_months=0,
                                new_free_rent_months=0)}
    r = _run([_anchor(), _inline("L1", "I1", end_date=date(2025, 6, 14))], [_pool(denominator="occupied_area")],
             market=market, months=12, suites=suites)
    assert sum((_rec(r, s, 1) for s in ("A", "I1", "I2")), D(0)).quantize(D("0.01")) == D("700000.00")


def test_occupied_area_pool_recovers_the_whole_expense_with_mid_month_downtime():
    """I1 ends 6/14 into three months of downtime: the denominator is the day-weighted leased area."""
    market = {"inline": _market("inline", renewal_probability=D("0"), downtime_months=3, new_free_rent_months=0)}
    leases = [_anchor(), _inline("L1", "I1", end_date=date(2025, 6, 14)), _inline("L2", "I2")]
    r = _run(leases, [_pool(denominator="occupied_area")], market=market)
    assert _total_rec(r, 1).quantize(D("0.01")) == D("700000.00")


# --- Pool gross-up over the included suites ---

_GROSSED = dict(is_gross_up_eligible=True, gross_up_vacancy_pct=D("0.95"), variable_pct=D("0.5"))


def test_dark_anchor_in_a_deducting_pool_does_not_gross_up_the_shops_past_the_expense():
    """The anchor goes dark in Year 2. The shops are fully leased, so the pool has no vacancy to gross
    up: they share the 450,000 incurred (700,000 at 28.6% occupancy, 50% variable), not 682,500."""
    market = {"anchor": _market("anchor", renewal_probability=D("0"), downtime_months=12, new_free_rent_months=0)}
    leases = [_anchor(end_date=date(2025, 12, 31)), _inline("L1", "I1"), _inline("L2", "I2")]
    r = _run(leases, [_pool(excluded_suite_ids=("A",), deduct_excluded_recoveries=True)],
             expenses=[_cam(**_GROSSED)], market=market)
    incurred = -r.annual_cash_flows[1].expense_detail["cam"]
    assert incurred.quantize(D("1")) == D("450000")
    assert _rec(r, "I1", 2).quantize(D("0.01")) == D("225000.00")
    assert _rec(r, "I2", 2).quantize(D("0.01")) == D("225000.00")
    assert _total_rec(r, 2) <= incurred


def test_pool_grosses_up_only_the_included_suites_vacancy():
    """Anchor leased, I2 vacant: the shops are 50% occupied and the property 85.7%. Grossing the shops
    to 95% raises the property to (60,000 + 9,000) / 70,000; the expense at that occupancy less what
    the anchor pays is shared over the shop area."""
    leases = [_anchor(), _inline("L1", "I1")]
    r = _run(leases, [_pool(excluded_suite_ids=("A",), deduct_excluded_recoveries=True)],
             expenses=[_cam(**_GROSSED)], months=12)
    # Anchor: its own terms over the whole property, grossed to 95%: 700,000 x (0.5 + 0.5 x 0.95) x 5/7
    anchor = D(700000) * (D("0.5") + D("0.5") * D("0.95")) * 5 / 7
    assert _rec(r, "A", 1).quantize(D("0.01")) == anchor.quantize(D("0.01"))
    grossed = D(700000) * (D("0.5") + D("0.5") * D(69000) / D(70000))
    assert _rec(r, "I1", 1).quantize(D("0.01")) == ((grossed - anchor) / 2).quantize(D("0.01"))
    assert _total_rec(r, 1) <= -r.annual_cash_flows[0].expense_detail["cam"]


def test_fixed_area_pool_grosses_up_at_property_occupancy():
    """A fixed denominator need not be the included area (here the whole property, with the dark
    anchor's space in it), so gross-up stays at property occupancy: Y2 shares 682,500 over 70,000 SF."""
    market = {"anchor": _market("anchor", renewal_probability=D("0"), downtime_months=12, new_free_rent_months=0)}
    leases = [_anchor(end_date=date(2025, 12, 31)), _inline("L1", "I1"), _inline("L2", "I2")]
    pool = _pool(excluded_suite_ids=("A",), deduct_excluded_recoveries=True, denominator="fixed_area",
                 fixed_area=D("70000"))
    r = _run(leases, [pool], expenses=[_cam(**_GROSSED)], market=market)
    assert _rec(r, "I1", 2).quantize(D("0.01")) == D("97500.00")


def test_pool_without_exclusions_grosses_up_as_before():
    leases = [_anchor(), _inline("L1", "I1")]
    base = _run(leases, expenses=[_cam(**_GROSSED)], months=12)
    pooled = _run(leases, [_pool()], expenses=[_cam(**_GROSSED)], months=12)
    assert [_rec(pooled, s, 1) for s in ("A", "I1")] == [_rec(base, s, 1) for s in ("A", "I1")]


# --- Calendar-year recoveries measure each calendar year at its own occupancy ---

def test_calendar_recoveries_bill_nothing_in_a_market_leases_base_year():
    """June fiscal year, calendar recoveries, gross-up off: A renews Jan 2027 on a base-year stop (base
    2027) and B leases up in Apr 2027. The 2027 expense and the stop use 2027's occupancy."""
    suites = [SuiteInput(suite_id=s, suite_name=s, area=D(5000), space_type="office") for s in ("A", "B")]
    a = _flat_lease(lease_id="A", suite_id="A", area=D(5000), start_date=date(2024, 1, 1),
                    end_date=date(2026, 12, 31), recovery_type="base_year_stop", base_year=2024)
    b = _flat_lease(lease_id="B", suite_id="B", area=D(5000), start_date=date(2027, 4, 1),
                    end_date=date(2035, 12, 31), recovery_type="nnn")
    cleaning = _expense(category="cleaning", growth_rate=D(0), is_recoverable=True, variable_pct=D("0.5"))
    params = replace(_make_params(), apply_stabilized_gross_up=False, calendar_year_recoveries=True)
    r = run_valuation(property_start_date=date(2025, 7, 1), analysis_period_months=60, fiscal_year_end_month=6,
                      suites=suites, leases=[a, b], market_assumptions={"office": _rollover_market()},
                      expenses=[cleaning], params=params)
    by_month = defaultdict(D)
    for e in r.recovery_audit:
        if e.suite_id == "A" and e.lease_id.startswith("spec_renew") and e.period_start.year == 2027:
            by_month[e.period_start] += e.monthly_recovery_after_free_rent
            assert e.actual_occupancy_pct == D("0.875")  # 2027: 50% Jan-Mar, 100% Apr-Dec
    assert len(by_month) == 12
    assert sum(by_month.values()) == 0


# --- Pre-analysis base year in a deducting pool ---

def test_pre_analysis_base_year_in_a_deducting_pool_is_net_of_the_anchor():
    """I1's base year 2023 is before the analysis: its stop is Year 1's pool expense net of what the
    anchor paid (700,000 - 500,000) deflated two years at 3%, not the gross building expense."""
    cam = [_cam(growth_rate=D("0.03"))]
    i1 = _flat_lease(lease_id="L1", suite_id="I1", area=D("10000"), recovery_type="base_year_stop",
                     base_year=2023)
    r = _run([_anchor(), i1, _inline("L2", "I2")], [_pool(excluded_suite_ids=("A",), deduct_excluded_recoveries=True)],
             expenses=cam, months=24)
    stop = D(200000) / D("1.03") ** 2
    assert _rec(r, "I1", 1).quantize(D("0.01")) == ((D(200000) - stop) / 2).quantize(D("0.01"))
    assert _rec(r, "I1", 2).quantize(D("0.01")) == ((D(721000) - D(515000) - stop) / 2).quantize(D("0.01"))


def test_pre_analysis_base_year_in_a_deducting_pool_with_calendar_recoveries():
    cam = [_cam(growth_rate=D("0.03"))]
    i1 = _flat_lease(lease_id="L1", suite_id="I1", area=D("10000"), recovery_type="base_year_stop",
                     base_year=2023)
    r = _run([_anchor(), i1, _inline("L2", "I2")], [_pool(excluded_suite_ids=("A",), deduct_excluded_recoveries=True)],
             expenses=cam, months=24, calendar_year_recoveries=True)
    stop = D(200000) / D("1.03") ** 2
    assert _rec(r, "I1", 1).quantize(D("0.01")) == ((D(200000) - stop) / 2).quantize(D("0.01"))


def test_pre_analysis_base_year_outside_a_pool_is_unchanged():
    """Unpooled, the pre-analysis stop is still the Year 1 expense as stated, deflated."""
    cam = [_cam(growth_rate=D("0.03"))]
    i1 = _flat_lease(lease_id="L1", suite_id="I1", area=D("10000"), recovery_type="base_year_stop",
                     base_year=2023)
    r = _run([_anchor(), i1, _inline("L2", "I2")], expenses=cam, months=12)
    stop = D(700000) / D("1.03") ** 2
    assert _rec(r, "I1", 1).quantize(D("0.01")) == ((D(700000) - stop) / 7).quantize(D("0.01"))
