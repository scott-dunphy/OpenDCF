"""
Parity with a published published DCF software appraisal: Magnolia City Place (Northgate Shopping Center), 655 Fieldstown
Road, Gardendale AL (185,491 SF community center). CBRE, March 2014, PUBLISHED Ver. 15.0.1.26. Filed with
Books-A-Million's SC 13E3/A of 2015-10-21 (SEC accession 0001193125-15-349412, exhibit (c)(7)), which prints
the published DCF software input assumptions, rent roll, cash flow, resale and present value schedules.

As-is analysis from 3/2014 with fiscal years ending February and recoveries billed on calendar years.
Exercises: suites held vacant until signed leases start, two credit tenants excluded from general vacancy
with the exclusion carried past rollover, $/SF caps on CAM and management fee together, 2% growth caps on
CAM (+ insurance or + management fee), admin fees, blended market leasing with a 10% rent step in month
61, leasing costs growing 2.5%, general vacancy reduced by downtime on gross revenue, and the reversion
capitalized on NOI adjusted for full occupancy.

Known residuals: recoveries run up to $3.8k (0.7%) below published DCF software, most in Years 1-5; and published DCF software's
full-occupancy adjustment comes out about $13k (0.6%) below Ares's market fill of the Year 11 downtime,
worth about $65k (0.5%) of value. published DCF software deducts the $7.27M redevelopment cost in Year 1; the test does the same.
"""
import calendar
from datetime import date
from decimal import Decimal as D

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import (
    ExpenseInput,
    ExpenseRecoveryOverride,
    LeaseInput,
    MarketAssumptions,
    RentStepInput,
    SuiteInput,
    ValuationParams,
)

PUBLISHED = {
    "sched_rent": [1006637, 1956900, 1954191, 1967968, 1921548, 2102861, 2122975, 2130246, 2123248, 2165431, 2065360],
    "abs_vac": [0, 0, -4875, -4973, -136802, -26808, 0, 0, -10980, 0, -127676],
    "recoveries": [341354, 575677, 586952, 599402, 551794, 625544, 642789, 657521, 669538, 687726, 675127],
    "gen_vac": [-60780, -132915, -128679, -130504, -113894, -114286, -141417, -142778, -132571, -145742, -16035],
    "credit": [-6078, -13291, -13307, -13498, -13684, -13841, -14142, -14278, -14245, -14574, -13094],
    "mgmt_fee": [51245, 95455, 95966, 96935, 93831, 104011, 104408, 105228, 105839, 107714, 108454],
    "opex": [617394, 675757, 690775, 706615, 718752, 744556, 760968, 778201, 795636, 814757, 833172],
    "noi": [663739, 1710614, 1708382, 1716753, 1627012, 1855722, 1849237, 1852510, 1850334, 1878084, 1878186],
    "ti": [614200, 0, 0, 10500, 387091, 11031, 22382, 0, 11879, 0, 164604],
    "lc": [208900, 0, 0, 9246, 173075, 7348, 23306, 0, 10208, 0, 118038],
    "cfbd": [-7431321, 1710614, 1708382, 1697007, 1066846, 1837343, 1803549, 1852510, 1828247, 1878084, 1595544],
}
PUBLISHED_RECOVERY = {
    "real_estate_taxes": [117671, 190555, 194969, 199853, 185882, 208509, 215595, 220984, 225722, 232176, 226541],
    "property_insurance": [23474, 37976, 38810, 39732, 36893, 41355, 42711, 43729, 44614, 45838, 44644],
    "common_area_maintenance": [170727, 277326, 283379, 290150, 268777, 300741, 309752, 316959, 323250, 331938, 327812],
    "management_fee": [29482, 69820, 69794, 69667, 60242, 74939, 74731, 75849, 75952, 77774, 76130],
}
PUBLISHED_VALUE = 13741401      # PV at 8.75%
PUBLISHED_NET_SALE = 25806186

SIZE = D(185491)
INFL = (D(0),) + (D("0.025"),)
MKT = (D(0), D(0), D(0)) + (D("0.02"),)


def market(space, rent, downtime, ti, free, term_years, prob="0.75", step=True):
    return MarketAssumptions(
        space_type=space, market_rent_per_unit=D(rent), rent_growth_rate=D(0), rent_growth_schedule=MKT,
        new_lease_term_months=term_years * 12, renewal_term_months=term_years * 12, downtime_months=downtime,
        renewal_probability=D(prob), new_ti_per_sf=D(ti), renewal_ti_per_sf=D(0), new_lc_pct=D("0.05"),
        renewal_lc_pct=D("0.025"), new_free_rent_months=free, renewal_free_rent_months=0,
        renewal_rent_adjustment_pct=D(0), general_vacancy_pct=D("0.10"), credit_loss_pct=D("0.01"),
        rollover_method="blended", lease_escalation_pct=D(0), leasing_cost_growth_rate=D("0.025"),
        lease_rent_steps=((61, D("0.10")),) if step else (), recovery_type="nnn",
    )


MARKETS = {m.space_type: m for m in [
    market("anchor", "7", 12, 20, 3, 10), market("junior_anchor", "10", 9, 15, 3, 7),
    market("inline_large", "15", 6, 10, 2, 5, step=False), market("inline_small", "18", 6, 10, 2, 5, step=False),
    market("bank", "45000", 12, 0, 6, 10), market("restaurant", "40", 6, 20, 6, 10, prob="0.70"),
    market("demolished", "0", 0, 0, 0, 1),   # space folded into Publix / Shoe Show expansion
]}


def ov(cat, cap=None, admin=None, group=None, growth=None, kind="nnn"):
    return ExpenseRecoveryOverride(cat, kind, None, D(cap) if cap is not None else None, None,
                                   D(admin) if admin is not None else None, cap_group=group,
                                   cap_growth_pct=D(growth) if growth is not None else None)


ADMIN10 = (ov("common_area_maintenance", admin="0.10"), ov("management_fee", admin="0.10"))
ADMIN15 = (ov("common_area_maintenance", admin="0.15"), ov("management_fee", admin="0.15"))


def capped(per_sf):
    """CAM & management fee together at most $/SF/yr"""
    return (ov("common_area_maintenance", cap=per_sf, group="cam_mgmt"), ov("management_fee", group="cam_mgmt"))


PUBLIX = (ov("common_area_maintenance", group="cam_ins", growth="0.02"),
          ov("property_insurance", group="cam_ins"), ov("management_fee", kind="none"))
TJ_MAXX = (ov("common_area_maintenance", group="cam_mgmt", growth="0.02"), ov("management_fee", group="cam_mgmt"))


def lease(lid, sid, area, start, end, rent, overrides=(), steps=(), **kw):
    base = dict(lease_id=lid, suite_id=sid, tenant_name=lid, area=D(area), start_date=start, end_date=end,
                base_rent_per_unit=D(rent), rent_payment_frequency="annual", escalation_type="flat",
                escalation_pct=None, cpi_floor=None, cpi_cap=None,
                rent_steps=tuple(RentStepInput(d, D(r)) for d, r in steps), free_rent_periods=(),
                recovery_type="nnn", pro_rata_share=None, base_year_stop_amount=None, expense_stop_per_sf=None,
                recovery_overrides=tuple(overrides), pct_rent_breakpoint=None, pct_rent_rate=None)
    if steps:
        base["escalation_type"] = "fixed_step"
    return LeaseInput(**{**base, **kw})


def placeholder(sid):
    """Suite vacant from the analysis start until its first signed lease (no spec leasing before it)."""
    return lease(f"pre_{sid}", sid, 0, date(2014, 1, 1), date(2014, 1, 31), "0", upon_expiration="reabsorb")


def ym(y, m, end=False):
    return date(y, m, calendar.monthrange(y, m)[1] if end else 1)


def lc_amt(rent, area, years, pct="0.05"):
    return D(pct) * D(rent) * D(area) * years


# suite, area, MLA category
SUITES = [("301", 61137, "anchor"), ("201", 45600, "anchor"), ("302", 26918, "junior_anchor"),
          ("200", 20731, "demolished"), ("303", 12000, "junior_anchor"), ("207", 12000, "junior_anchor"),
          ("206", 5200, "inline_large"), ("310", 4300, "demolished"), ("304", 4000, "inline_large"),
          ("203", 3900, "inline_large"), ("202", 2920, "inline_small"), ("401", 1816, "restaurant"),
          ("204", 1800, "inline_small"), ("106", 1500, "inline_small"), ("101", 1500, "inline_small"),
          ("102", 1000, "inline_small"), ("205", 1200, "anchor"), ("105", 1000, "inline_small"),
          ("104", 1000, "inline_small"), ("103", 1000, "inline_small"), ("OP", 1, "bank")]

HEAD_START_STEPS = [(ym(2014, 11), "19.05")] + [(ym(2015 + k, 11), f"{D('19.05') * D('1.03') ** (k + 1):.4f}")
                                                 for k in range(10)]
LEASES = [
    lease("Hobby Lobby", "301", 61137, ym(2013, 7), ym(2018, 6, True), "5.50", exclude_from_general_vacancy=True,
          vacancy_exclusion_ends_at_rollover=False),
    placeholder("201"),
    lease("Publix", "201", 45600, ym(2014, 11), ym(2034, 10, True), "11.85", PUBLIX,
          exclude_from_general_vacancy=True, vacancy_exclusion_ends_at_rollover=False),
    placeholder("302"),
    lease("TJ Maxx", "302", 26918, ym(2014, 11), ym(2024, 11, True), "7.25", TJ_MAXX, steps=[(ym(2019, 11), "7.75")],
          committed_ti_amount=D(300000)),
    lease("Dollar Tree (08/13)", "200", 20731, ym(2003, 4), ym(2014, 3, True), "5.85", upon_expiration="reabsorb"),
    placeholder("303"),
    lease("Petco", "303", 12000, ym(2015, 1), ym(2024, 12, True), "19", ADMIN10,
          committed_ti_amount=D(180000), committed_lc_amount=lc_amt(19, 12000, 10)),
    placeholder("207"),
    lease("Dollar Tree (04/14)", "207", 12000, ym(2014, 4), ym(2018, 4, True), "5.85"),
    placeholder("206"),
    lease("Shoe Show (04/14)", "206", 5200, ym(2014, 4), ym(2024, 8, True), "9.85", capped("0.46")),
    lease("Shoe Show (08/13)", "310", 4300, ym(1988, 8), ym(2014, 3, True), "9", capped("0.46"),
          upon_expiration="reabsorb"),
    placeholder("304"),
    lease("Aspen Dental", "304", 4000, ym(2015, 1), ym(2024, 12, True), "27.50", ADMIN10,
          committed_ti_amount=D(40000), committed_lc_amount=lc_amt("27.5", 4000, 10)),
    lease("CATO", "203", 3900, ym(2013, 7), ym(2017, 1, True), "11"),
    placeholder("202"),
    lease("Palm Beach Tan", "202", 2920, ym(2015, 1), ym(2019, 12, True), "20", ADMIN10,
          committed_ti_amount=D(29200), committed_lc_amount=lc_amt(20, 2920, 5)),
    placeholder("401"),
    lease("Starbucks", "401", 1816, ym(2014, 9), ym(2024, 8, True), "40", ADMIN10),
    placeholder("204"),
    lease("Firehouse Subs", "204", 1800, ym(2015, 1), ym(2019, 12, True), "20", ADMIN10,
          committed_ti_amount=D(18000), committed_lc_amount=lc_amt(20, 1800, 5)),
    lease("Head Start", "106", 1500, ym(2013, 7), ym(2024, 12, True), "13.84", ADMIN15, steps=HEAD_START_STEPS),
    placeholder("101"),
    lease("Republic Finance (11/14)", "101", 1500, ym(2014, 11), ym(2018, 12, True), "21", capped("0.75"),
          committed_ti_amount=D(15000)),
    lease("H&R Block", "102", 1000, ym(2010, 5), ym(2025, 4, True), "9", ADMIN10, steps=[(ym(2014, 11), "21")]),
    placeholder("205"),
    lease("AccuQuest", "205", 1200, ym(2014, 8), ym(2019, 7, True), "21", ADMIN10,
          committed_ti_amount=D(12000), committed_lc_amount=lc_amt(21, 1200, 5)),
    lease("Nail Model", "105", 1000, ym(2008, 4), ym(2019, 12, True), "21.13", capped("1.6"),
          steps=[(ym(2014, 6), "22.18"), (ym(2014, 11), "23.01")]),
    placeholder("104"),
    lease("Gold Plus", "104", 1000, ym(2015, 1), ym(2019, 12, True), "20", ADMIN10,
          committed_ti_amount=D(10000), committed_lc_amount=lc_amt(20, 1000, 5)),
    lease("Republic Finance (As Is)", "103", 1000, ym(2010, 12), ym(2014, 10, True), "19", capped("0.75"),
          upon_expiration="reabsorb"),
    lease("State Farm", "103", 1000, ym(2015, 1), ym(2019, 12, True), "20", ADMIN10,
          committed_ti_amount=D(10000), committed_lc_amount=lc_amt(20, 1000, 5)),
    lease("Wells Fargo", "OP", 1, ym(2003, 10), ym(2043, 12, True), "3850", recovery_type="none",
          rent_payment_frequency="monthly"),
]


def expense(eid, amount, recoverable=True, **kw):
    base = dict(expense_id=eid, category=eid, base_amount=D(amount), growth_rate=D("0.025"), growth_schedule=INFL,
                is_recoverable=recoverable, is_gross_up_eligible=False, gross_up_vacancy_pct=None,
                is_pct_of_egi=False, pct_of_egi=None)
    return ExpenseInput(**{**base, **kw})


EXPENSES = [
    expense("real_estate_taxes", "185892"), expense("property_insurance", SIZE * D("0.2")),
    expense("common_area_maintenance", SIZE * D("1.5")),
    expense("management_fee", "0", is_pct_of_egi=True, pct_of_egi=D("0.04")),
    expense("non_reimbursables", SIZE * D("0.2"), recoverable=False),
    expense("replacement_reserve", SIZE * D("0.15"), recoverable=False),
]
REDEVELOPMENT = D(7271960)
PARAMS = ValuationParams(
    discount_rate=D("0.0875"), exit_cap_rate=D("0.0775"), exit_cap_year=-1, exit_costs_pct=D("0.02"),
    capital_reserves_per_unit=D(0), total_property_area=SIZE, use_mid_year_convention=False,
    loan_amount=None, interest_rate=None, amortization_months=None, loan_term_months=None, io_period_months=0,
    apply_stabilized_gross_up=False, reduce_general_vacancy_by_downtime=True, vacancy_on_gross_revenue=True,
    calendar_year_recoveries=True, exit_noi_full_occupancy=True,
)


def _run(months=120, leases=LEASES, markets=MARKETS, params=PARAMS):
    suites = [SuiteInput(suite_id=s, suite_name=s, area=D(a), space_type=t) for s, a, t in SUITES]
    return run_valuation(property_start_date=date(2014, 3, 1), analysis_period_months=months,
                         fiscal_year_end_month=2, suites=suites, leases=leases, market_assumptions=markets,
                         expenses=EXPENSES, params=params, property_type="retail")


@pytest.fixture(scope="module")
def cash_flows():
    return list(_run().annual_cash_flows) + [_run(132).annual_cash_flows[10]]


def test_every_year_matches_published(cash_flows):
    assert [float(cf.gross_potential_rent + cf.free_rent) for cf in cash_flows] == pytest.approx(
        PUBLISHED["sched_rent"], abs=5)
    assert [float(cf.absorption_vacancy) for cf in cash_flows] == pytest.approx(PUBLISHED["abs_vac"], abs=5)
    assert [float(cf.expense_recoveries) for cf in cash_flows] == pytest.approx(PUBLISHED["recoveries"], abs=4000)
    assert [float(cf.net_operating_income) for cf in cash_flows] == pytest.approx(PUBLISHED["noi"], abs=3500)
    assert [-float(cf.tenant_improvements) for cf in cash_flows] == pytest.approx(PUBLISHED["ti"], abs=5)
    assert [-float(cf.leasing_commissions) for cf in cash_flows] == pytest.approx(PUBLISHED["lc"], abs=5)


def test_value_matches_published():
    r = _run()
    assert float(r.npv) - float(REDEVELOPMENT) / 1.0875 == pytest.approx(PUBLISHED_VALUE, rel=0.006)
    assert float(r.terminal_value) == pytest.approx(PUBLISHED_NET_SALE, rel=0.007)
