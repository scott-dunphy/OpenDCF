"""Recovery pools: share denominators, anchor exclusions and deductions, occupied-area basis."""
from datetime import date
from dataclasses import replace
from decimal import Decimal

from src.engine.property_cashflow import run_valuation
from src.engine.types import ExpenseRecoveryOverride, RecoveryPoolInput, SuiteInput
from tests.integration.test_engine_parity import _make_params
from tests.unit.test_growth_schedules import _expense, _flat_lease

D = Decimal
# Anchor 50,000 SF and two 10,000 SF inline suites (I2 vacant, no market): 70,000 SF
SUITES = [
    SuiteInput(suite_id="A", suite_name="Anchor", area=D("50000"), space_type="anchor"),
    SuiteInput(suite_id="I1", suite_name="101", area=D("10000"), space_type="inline"),
    SuiteInput(suite_id="I2", suite_name="102", area=D("10000"), space_type="inline"),
]
CAM = 700_000


def _cam(**kw):
    return _expense(category="cam", base_amount=D(CAM), growth_rate=D("0"), is_recoverable=True, **kw)


def _anchor(**kw):
    return _flat_lease(lease_id="LA", suite_id="A", area=D("50000"), recovery_type="nnn", **kw)


def _run(pools=(), expenses=None, anchor=None, calendar=False, fy_end=12):
    inline = _flat_lease(lease_id="L1", suite_id="I1", area=D("10000"), recovery_type="nnn")
    params = _make_params(total_area=D("70000"))
    if calendar:
        params = replace(params, calendar_year_recoveries=True)
    return run_valuation(
        property_start_date=date(2025, 1, 1), analysis_period_months=24, fiscal_year_end_month=fy_end,
        suites=SUITES, leases=[anchor or _anchor(), inline], market_assumptions={},
        expenses=expenses or [_cam()], params=params, recovery_pools=tuple(pools),
    )


def _year1(result, suite_id):
    return next(d.expense_recovery for d in result.suite_annual_details
                if d.suite_id == suite_id and d.year == 1).quantize(D("0.01"))


def _pool(**kw):
    return RecoveryPoolInput(pool_id="P", name="CAM pool", expense_categories=("cam",), **kw)


def test_no_pool_shares_over_the_whole_property():
    r = _run()
    assert _year1(r, "I1") == D("100000.00")
    assert _year1(r, "A") == D("500000.00")


def test_property_area_pool_without_exclusions_changes_nothing():
    base, pooled = _run(), _run([_pool()])
    assert [cf.net_operating_income for cf in pooled.annual_cash_flows] == \
        [cf.net_operating_income for cf in base.annual_cash_flows]
    assert pooled.terminal_value == base.terminal_value


def test_excluded_anchor_leaves_the_denominator():
    r = _run([_pool(excluded_suite_ids=("A",))])
    assert _year1(r, "I1") == D("350000.00")      # 700,000 x 10,000 / 20,000
    assert _year1(r, "A") == D("500000.00")       # the anchor's own terms


def test_inline_tenants_share_what_the_anchor_does_not_pay():
    capped = ExpenseRecoveryOverride(expense_category="cam", recovery_type="nnn", base_year_stop_amount=None,
                                     cap_per_sf_annual=D("5"), floor_per_sf_annual=None, admin_fee_pct=None)
    r = _run([_pool(excluded_suite_ids=("A",), deduct_excluded_recoveries=True)],
             anchor=_anchor(recovery_overrides=(capped,)))
    assert _year1(r, "A") == D("250000.00")       # capped at $5/SF
    assert _year1(r, "I1") == D("225000.00")      # (700,000 - 250,000) x 10,000 / 20,000
    assert _year1(r, "A") + _year1(r, "I1") <= CAM


def test_fixed_area_denominator():
    r = _run([_pool(denominator="fixed_area", fixed_area=D("40000"))])
    assert _year1(r, "I1") == D("175000.00")


def test_occupied_area_denominator_with_minimum():
    r = _run([_pool(denominator="occupied_area")])
    assert _year1(r, "I1") == D("116666.67")      # 700,000 x 10,000 / 60,000
    r = _run([_pool(denominator="occupied_area", minimum_occupancy_pct=D("0.9"))])
    assert _year1(r, "I1") == D("111111.11")      # floor 63,000 SF


def test_occupied_area_pool_is_not_grossed_up():
    grossed = [_cam(is_gross_up_eligible=True, gross_up_vacancy_pct=D("0.95"))]
    assert _year1(_run(expenses=grossed), "I1") > D("100000")         # grossed up to 95%
    r = _run([_pool(denominator="occupied_area")], expenses=grossed)
    assert _year1(r, "I1") == D("116666.67")


def test_pool_changes_terminal_value():
    assert _run([_pool(excluded_suite_ids=("A",))]).terminal_value > _run().terminal_value


def test_calendar_recoveries_with_a_june_fiscal_year():
    pooled = _run([_pool(excluded_suite_ids=("A",), deduct_excluded_recoveries=True)], calendar=True, fy_end=6)
    # Anchor pays its full share, so inline tenants share the rest over 20,000 SF: same as 10,000 / 70,000
    assert _year1(pooled, "I1") == _year1(_run(calendar=True, fy_end=6), "I1")


def _year(result, suite_id, year):
    return next(d.expense_recovery for d in result.suite_annual_details
                if d.suite_id == suite_id and d.year == year).quantize(D("0.01"))


def _run_inline(inline, pools, expenses, anchor=None, extra_leases=()):
    return run_valuation(
        property_start_date=date(2025, 1, 1), analysis_period_months=24, fiscal_year_end_month=12,
        suites=SUITES, leases=[anchor or _anchor(), inline, *extra_leases], market_assumptions={},
        expenses=expenses, params=_make_params(total_area=D("70000")), recovery_pools=tuple(pools),
    )


def test_base_year_lease_pools_each_denominator_separately():
    inline = _flat_lease(lease_id="L1", suite_id="I1", area=D("10000"), recovery_type="base_year_stop",
                         base_year=2025)
    expenses = [_cam(), _expense(expense_id="E2", category="real_estate_taxes", base_amount=D("70000"),
                                 growth_rate=D("0.1"), is_recoverable=True)]
    expenses[0] = _expense(category="cam", base_amount=D(CAM), growth_rate=D("0.1"), is_recoverable=True)
    r = _run_inline(inline, [_pool(excluded_suite_ids=("A",))], expenses)
    assert _year(r, "I1", 1) == D("0.00")
    # CAM: 70,000 increase x 10,000 / 20,000; taxes: 7,000 increase x 10,000 / 70,000
    assert _year(r, "I1", 2) == D("36000.00")


def test_base_year_in_a_deducting_pool_is_net_of_the_anchor():
    inline = _flat_lease(lease_id="L1", suite_id="I1", area=D("10000"), recovery_type="base_year_stop",
                         base_year=2025)
    cam = [_expense(category="cam", base_amount=D(CAM), growth_rate=D("0.1"), is_recoverable=True)]
    r = _run_inline(inline, [_pool(excluded_suite_ids=("A",), deduct_excluded_recoveries=True)], cam)
    assert _year(r, "I1", 1) == D("0.00")
    # Net pool 770,000 - 550,000 = 220,000 over a 200,000 base: 20,000 x 10,000 / 20,000
    assert _year(r, "I1", 2) == D("10000.00")


def test_modified_gross_stop_applies_to_the_summed_cost_per_sf():
    inline = _flat_lease(lease_id="L1", suite_id="I1", area=D("10000"), recovery_type="modified_gross",
                         expense_stop_per_sf=D("15"))
    expenses = [_cam(), _expense(expense_id="E2", category="real_estate_taxes", base_amount=D("70000"),
                                 growth_rate=D("0"), is_recoverable=True)]
    r = _run_inline(inline, [_pool(denominator="fixed_area", fixed_area=D("35000"))], expenses)
    # CAM $20/SF over 35,000 + taxes $1/SF over 70,000 = $21/SF; $6/SF over the stop x 10,000 SF
    assert _year(r, "I1", 1) == D("60000.00")


def test_a_contributor_to_one_pool_gets_another_pools_deduction():
    # CAM leaves out the anchor; taxes leave out I1. Both deduct. I1 pays CAM net of the anchor.
    taxes = _expense(expense_id="E2", category="real_estate_taxes", base_amount=D("70000"),
                     growth_rate=D("0"), is_recoverable=True)
    inline2 = _flat_lease(lease_id="L2", suite_id="I2", area=D("10000"), recovery_type="nnn")
    inline = _flat_lease(lease_id="L1", suite_id="I1", area=D("10000"), recovery_type="nnn")
    pools = [_pool(excluded_suite_ids=("A",), deduct_excluded_recoveries=True),
             RecoveryPoolInput(pool_id="T", name="Taxes", expense_categories=("real_estate_taxes",),
                               excluded_suite_ids=("I1",), deduct_excluded_recoveries=True)]
    r = _run_inline(inline, pools, [_cam(), taxes], extra_leases=[inline2])
    # CAM: (700,000 - 500,000) x 10,000 / 20,000 = 100,000; taxes over 70,000 SF: 10,000
    assert _year(r, "I1", 1) == D("110000.00")
    total = sum(_year(r, s, 1) for s in ("A", "I1", "I2"))
    assert total <= CAM + 70000
