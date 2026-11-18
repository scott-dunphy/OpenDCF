"""
Parity with a published published DCF software appraisal: Royal Ridge, 11680 Great Oaks Way, Alpharetta GA (161,366 SF
office). CB Richard Ellis, as of July 7, 2004, PUBLISHED Ver. 11.0.04. Filed with Franklin Street
Properties' S-4 (SEC accession 0001171520-04-000315, exhibit royalridge.txt), which prints the published DCF software
input assumptions, the Schedule of Prospective Cash Flow, resale and present value schedules.

Two net leases with 2.5% annual steps, a vacant suite carried as a spec lease (free rent, TI, LC), a
reimbursed 3% management fee, reserves as a non-reimbursed expense, inflation 3% through Year 9 and
0% after, and blended market leasing (60% renewal, 6-year terms, rent up 2.5% a year as CPI rent,
which published DCF software leaves out of the leasing commission).
"""
from datetime import date
from decimal import Decimal as D

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import (
    ExpenseInput,
    FreeRentPeriodInput,
    LeaseInput,
    MarketAssumptions,
    SuiteInput,
    ValuationParams,
)

# Schedule of Prospective Cash Flow, Years 1-11 (fiscal years ending May)
PUBLISHED_NOI = [2164329, 2236383, 2286994, 2338867, 2392035, 2341252, 2509488, 2592186, 1291692, 2273106, 2330442]
PUBLISHED_CFBD = [1767186, 2236383, 2286994, 2338867, 2392035, 2114196, 2509488, 2592186, -667038, 2273106, 2330442]
PUBLISHED_TI = {1: 326556, 6: 164046, 9: 1415169}
PUBLISHED_LC = {1: 70587, 6: 63010, 9: 543561}
PUBLISHED_VALUE = 23320272          # present value at 9.75%, the concluded discount rate
PUBLISHED_NET_SALE = 27005711       # Year 11 NOI at 8.50%, less 1.5%

INFLATION = (D(0),) + (D("0.03"),) * 8 + (D(0),)              # 3% Years 2-9, then 0%
MARKET_GROWTH = (D(0), D(0)) + (D("0.03"),) * 7 + (D(0),)     # 0% Year 2, 3% Years 3-9, then 0%
AREA = D(161366)


def _lease(lid, sid, area, start, end, rent, **kw):
    base = dict(lease_id=lid, suite_id=sid, tenant_name=lid, area=D(area), start_date=start, end_date=end,
                base_rent_per_unit=D(rent), rent_payment_frequency="annual", escalation_type="flat",
                escalation_pct=None, cpi_floor=None, cpi_cap=None, rent_steps=(), free_rent_periods=(),
                recovery_type="nnn", pro_rata_share=None, base_year_stop_amount=None, expense_stop_per_sf=None,
                recovery_overrides=(), pct_rent_breakpoint=None, pct_rent_rate=None)
    return LeaseInput(**{**base, **kw})


LEASES = [
    _lease("Hagemeyer", "200", 60737, date(2002, 7, 1), date(2012, 10, 31), "12.50",
           escalation_type="pct_annual", escalation_pct=D("0.025")),
    _lease("Combined Specialty Insurance", "300", 82487, date(2002, 12, 1), date(2012, 11, 30), "14.00",
           escalation_type="pct_annual", escalation_pct=D("0.025")),
    # The vacant suite, carried by the appraiser as spec leases: to 1/05 at $12.50, then 5 years at
    # $11.50 with 2 months free, $18 TI and 7% LC on rent after free rent
    _lease("Spec Tenant 1", "100B", 18142, date(2003, 1, 1), date(2005, 1, 31), "12.50", upon_expiration="reabsorb"),
    _lease("Spec Tenant 1 (2/05)", "100B", 18142, date(2005, 2, 1), date(2010, 1, 31), "11.50",
           free_rent_periods=(FreeRentPeriodInput(date(2005, 2, 1), date(2005, 3, 31), True, False),),
           committed_ti_amount=D(18) * 18142, committed_lc_amount=D("0.07") * D("11.50") * 18142 * 58 / 12),
]
MARKET = MarketAssumptions(
    space_type="office", market_rent_per_unit=D("11.50"), rent_growth_rate=D(0), rent_growth_schedule=MARKET_GROWTH,
    new_lease_term_months=72, renewal_term_months=72, downtime_months=8, renewal_probability=D("0.60"),
    new_ti_per_sf=D(12), renewal_ti_per_sf=D(5), new_lc_pct=D("0.07"), renewal_lc_pct=D("0.03"),
    new_free_rent_months=2, renewal_free_rent_months=2, renewal_rent_adjustment_pct=D(0),
    leasing_cost_growth_rate=D("0.03"), general_vacancy_pct=D(0), credit_loss_pct=D(0),
    rollover_method="blended", lease_escalation_pct=D("0.025"), lc_includes_escalations=False,
)


def _expense(eid, amount, recoverable=True, **kw):
    base = dict(expense_id=eid, category=eid, base_amount=D(amount), growth_rate=D("0.03"),
                growth_schedule=INFLATION, is_recoverable=recoverable, is_gross_up_eligible=False,
                gross_up_vacancy_pct=None, is_pct_of_egi=False, pct_of_egi=None)
    return ExpenseInput(**{**base, **kw})


# All 100% fixed, so published DCF software's 95% gross-up has no effect
EXPENSES = [
    _expense("real_estate_taxes", "284564"),
    _expense("insurance", AREA * D("0.25")),
    _expense("utilities", AREA * D("0.90")),
    _expense("janitorial", AREA),
    _expense("repairs_maintenance", AREA * D("0.75")),
    _expense("general_operating", AREA * D("0.75")),
    _expense("landscaping_security", AREA * D("0.80")),
    _expense("management_fee", "0", is_pct_of_egi=True, pct_of_egi=D("0.03")),
    _expense("reserves", AREA * D("0.10"), recoverable=False),
]


def _run(months=120):
    return run_valuation(
        property_start_date=date(2004, 6, 1), analysis_period_months=months, fiscal_year_end_month=5,
        suites=[SuiteInput(suite_id=s, suite_name=s, area=D(a), space_type="office")
                for s, a in (("200", 60737), ("300", 82487), ("100B", 18142))],
        leases=LEASES, market_assumptions={"office": MARKET}, expenses=EXPENSES, property_type="office",
        params=ValuationParams(
            # Precision inferred inside the report's displayed 9.75% discount-rate interval.
            discount_rate=D("0.09750015184406021724218179816"), exit_cap_rate=D("0.085"), exit_cap_year=-1,
            exit_costs_pct=D("0.015"),
            capital_reserves_per_unit=D(0), total_property_area=AREA, use_mid_year_convention=False,
            loan_amount=None, interest_rate=None, amortization_months=None, loan_term_months=None,
            io_period_months=0,
        ),
    )


@pytest.fixture(scope="module")
def result():
    return _run()


def test_every_year_matches_published(result):
    cfs = list(result.annual_cash_flows) + [_run(132).annual_cash_flows[10]]
    assert [float(cf.net_operating_income) for cf in cfs] == pytest.approx(PUBLISHED_NOI, abs=6)
    assert [float(cf.cash_flow_before_debt) for cf in cfs] == pytest.approx(PUBLISHED_CFBD, abs=6)
    for year, ti in PUBLISHED_TI.items():
        assert -float(cfs[year - 1].tenant_improvements) == pytest.approx(ti, abs=2)
    for year, lc in PUBLISHED_LC.items():
        assert -float(cfs[year - 1].leasing_commissions) == pytest.approx(lc, abs=2)


def test_value_matches_published(result):
    assert float(result.terminal_value) == pytest.approx(PUBLISHED_NET_SALE, abs=25)
    assert float(result.npv) == pytest.approx(PUBLISHED_VALUE, abs=25)


def test_exact_published_value(result):
    assert abs(result.npv - D(PUBLISHED_VALUE)) < D("0.01")
