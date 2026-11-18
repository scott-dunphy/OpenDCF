"""
Parity with a published published DCF software appraisal: Montague, 2730-60 Junction Ave / 404-410 E. Plumeria Dr,
San Jose (145,951 SF R&D). Cushman & Wakefield, as of July 7, 2004, PUBLISHED Ver. 11.0.04. Filed with
Franklin Street Properties' S-4 (SEC accession 0001171520-04-000315, exhibit montague.txt), which
prints the published DCF software input assumptions, the Schedule of Prospective Cash Flow and the resale matrix.

With the blended rollover (published DCF software market leasing) every year and the value tie to the dollar. With the
probability tree, Years 1-7 still tie; from the 3/2012 rollover on the renewal (Apr 2012) and new
tenant (Oct 2012, after 6 months) are separate weighted branches instead of one lease after
35% x 6 = 2 months vacant, which moves cash between Years 8 and 9 and lifts value about 0.65%.
"""
from datetime import date
from decimal import Decimal as D

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import (
    ExpenseInput,
    LeaseInput,
    MarketAssumptions,
    RentStepInput,
    SuiteInput,
    ValuationParams,
)

# Schedule of Prospective Cash Flow, Years 1-11 (fiscal years ending June)
PUBLISHED_NOI = [4032732, 4229116, 2415683, 1257937, 1295696, 1334591, 1374653, 1137310, 1885091, 1941671, 1900873]
PUBLISHED_CFBD = [4003542, 4199050, 62124, 1226040, 1262842, 1300752, 1339798, -716041, 1848114, 1903584, 1861644]
PUBLISHED_RECOVERIES = [436013, 448481, 315109, 405403, 415281, 425412, 435799]
PUBLISHED_COLLECTION_LOSS = [45139, 47248, 28645, 16801, 17283, 17778, 18287]
PUBLISHED_TI_Y3, PUBLISHED_LC_Y3 = 1548394, 774197
PUBLISHED_TI_Y8, PUBLISHED_LC_Y8 = 1211634, 605817
PUBLISHED_VALUE = 19363627          # resale matrix: 9.00% cap, 10.00% discount
PUBLISHED_NET_SALE = 20698395

INF = D("1.03")


def _lease(lid, sid, area, start, end, rent, **kw):
    base = dict(lease_id=lid, suite_id=sid, tenant_name=lid, area=D(area), start_date=start, end_date=end,
                base_rent_per_unit=D(rent), rent_payment_frequency="annual", escalation_type="flat",
                escalation_pct=None, cpi_floor=None, cpi_cap=None, rent_steps=(), free_rent_periods=(),
                recovery_type="nnn", pro_rata_share=None, base_year_stop_amount=None, expense_stop_per_sf=None,
                recovery_overrides=(), pct_rent_breakpoint=None, pct_rent_rate=None)
    return LeaseInput(**{**base, **kw})


def _leases(sid, area, market_rent):
    steps = tuple(RentStepInput(effective_date=d, rent_per_unit=D(r) * 12)
                  for d, r in ((date(2004, 5, 1), "2.31"), (date(2005, 5, 1), "2.42"), (date(2006, 5, 1), "2.55")))
    novellus = _lease(f"Novellus {sid}", sid, area, date(2002, 7, 1), date(2006, 12, 31), D("27.72"),
                      escalation_type="fixed_step", rent_steps=steps, upon_expiration="reabsorb")
    # Scheduled new lease 4/07-3/12 at 100% of Year 3 market (+5%), 3%/yr; TI $10 and LC $5 per SF grown
    # 3% a year to Year 3
    new = _lease(f"New Tenant {sid}", sid, area, date(2007, 4, 1), date(2012, 3, 31), D(market_rent) * D("1.05"),
                 escalation_type="pct_annual", escalation_pct=D("0.03"),
                 committed_ti_amount=D(area) * 10 * INF ** 2, committed_lc_amount=D(area) * 5 * INF ** 2)
    return [novellus, new]


def _market(space, rent, rollover_method):
    return MarketAssumptions(
        rollover_method=rollover_method,
        space_type=space, market_rent_per_unit=D(rent), rent_growth_rate=D("0.03"),
        rent_growth_schedule=(D(0), D(0), D("0.05"), D("0.10"), D("0.15"), D("0.10"), D("0.05"), D("0.03")),
        new_lease_term_months=60, new_ti_per_sf=D(10), new_lc_pct=D(0), new_lc_per_sf=D(5),
        new_free_rent_months=0, downtime_months=6, renewal_probability=D("0.65"), renewal_term_months=60,
        renewal_ti_per_sf=D(5), renewal_lc_pct=D(0), renewal_lc_per_sf=D("2.5"), renewal_free_rent_months=0,
        renewal_rent_adjustment_pct=D(0), leasing_cost_growth_rate=D("0.03"),
        general_vacancy_pct=D(0), credit_loss_pct=D("0.01"), credit_loss_schedule=(D("0.01"),) * 10 + (D("0.05"),),
    )


def _expense(eid, amount, growth, **kw):
    base = dict(expense_id=eid, category=eid, base_amount=D(amount), growth_rate=D(growth), is_recoverable=True,
                is_gross_up_eligible=False, gross_up_vacancy_pct=None, is_pct_of_egi=False, pct_of_egi=None)
    return ExpenseInput(**{**base, **kw})


# Prop 13 taxes: +2%/yr, reassessed at the resale price in Year 11
_TAX_Y11 = D(229520) / (D(210820) * D("1.02") ** 9) - 1
EXPENSES = [
    _expense("real_estate_taxes", "210820", "0.02", growth_schedule=(D(0),) + (D("0.02"),) * 9 + (_TAX_Y11,)),
    _expense("direct_assessments", "13318", "0.03"),
    _expense("insurance", "72500", "0.03"),
    _expense("repairs_maintenance", "50000", "0.03"),
    _expense("management_fee", "0", "0", is_pct_of_egi=True, pct_of_egi=D("0.02")),   # reimbursed by NNN tenants
]


def _run(rollover_method="blended", months=120):
    return run_valuation(
        property_start_date=date(2004, 7, 1), analysis_period_months=months, fiscal_year_end_month=6,
        suites=[SuiteInput(suite_id="2730J", suite_name="2730-60 Junction", area=D(90467), space_type="j"),
                SuiteInput(suite_id="404P", suite_name="404-410 Plumeria", area=D(55484), space_type="p")],
        leases=_leases("2730J", 90467, "7.80") + _leases("404P", 55484, "9.00"),
        market_assumptions={
            # Precision inferred inside the report's $7.80/SF display interval.
            "j": _market("j", "7.799997831705720188756231294", rollover_method),
            "p": _market("p", "9.00", rollover_method),
        },
        expenses=EXPENSES, property_type="industrial",
        params=ValuationParams(
            discount_rate=D("0.10"), exit_cap_rate=D("0.09"), exit_cap_year=-1, exit_costs_pct=D("0.02"),
            capital_reserves_per_unit=D("0.20"), capital_reserves_growth_rate=D("0.03"),
            total_property_area=D(145951), use_mid_year_convention=False, vacancy_on_gross_revenue=True,
            loan_amount=None, interest_rate=None, amortization_months=None, loan_term_months=None,
            io_period_months=0,
        ),
    )


@pytest.fixture(scope="module")
def result():
    return _run()


def test_every_year_matches_published(result):
    fwd = _run(months=132).annual_cash_flows[10]       # Year 11, the reversion year
    cfs = list(result.annual_cash_flows) + [fwd]
    assert [float(cf.net_operating_income) for cf in cfs] == pytest.approx(PUBLISHED_NOI, abs=2)
    assert [float(cf.cash_flow_before_debt) for cf in cfs] == pytest.approx(PUBLISHED_CFBD, abs=3)
    # Management fee reimbursed and collection loss on gross revenue, as published DCF software does
    assert [float(cf.expense_recoveries) for cf in cfs[:7]] == pytest.approx(PUBLISHED_RECOVERIES, abs=2)
    assert [-float(cf.credit_loss) for cf in cfs[:7]] == pytest.approx(PUBLISHED_COLLECTION_LOSS, abs=2)
    y3, y8 = cfs[2], cfs[7]
    assert -float(y3.tenant_improvements) == pytest.approx(PUBLISHED_TI_Y3, abs=1)
    assert -float(y3.leasing_commissions) == pytest.approx(PUBLISHED_LC_Y3, abs=1)
    # One blended lease 6/2012: 65% x $5 + 35% x $10 TI, 65% x $2.50 + 35% x $5 LC, grown 3%/yr to Year 8
    assert -float(y8.tenant_improvements) == pytest.approx(PUBLISHED_TI_Y8, abs=1)
    assert -float(y8.leasing_commissions) == pytest.approx(PUBLISHED_LC_Y8, abs=1)


def test_value_matches_published(result):
    assert float(result.terminal_noi_basis) == pytest.approx(PUBLISHED_NOI[10], abs=2)
    assert float(result.terminal_value) == pytest.approx(PUBLISHED_NET_SALE, abs=5)
    assert float(result.npv) == pytest.approx(PUBLISHED_VALUE, abs=5)


def test_exact_published_value(result):
    assert abs(result.npv - D(PUBLISHED_VALUE)) < D("0.01")


def test_probability_tree_differs_only_from_the_rollover():
    r = _run("probability_tree")
    cfs = r.annual_cash_flows
    assert [float(cf.net_operating_income) for cf in cfs[:7]] == pytest.approx(PUBLISHED_NOI[:7], abs=2)
    # Ares pays the renewal share of TI in Year 8 and the new tenant's in Year 9 (Oct 2012)
    area = 145951
    assert -float(cfs[7].tenant_improvements) == pytest.approx(0.65 * 5 * area * 1.03 ** 7, abs=1)
    assert -float(cfs[8].tenant_improvements) == pytest.approx(0.35 * 10 * area * 1.03 ** 8, abs=1)
    assert float(r.npv) == pytest.approx(PUBLISHED_VALUE, rel=0.0075)
