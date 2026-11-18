"""
Parity with a published published DCF software appraisal: 301 E. Colorado Blvd, Pasadena CA, a 117,336 SF multi-tenant office
building with a ground-floor bank, appraised by Cushman & Wakefield as of January 1, 2011 (published DCF software, 10-year
hold). Filed by Wesco Financial with the SEC in 2011, exhibit (c)(11), which prints the rent roll, cash flow
assumptions, expense conclusions and the published DCF software cash flow.

The model: 50 leases (19 month-to-month, rolling to market after Year 1, and CPI leases rising 3% each March
or October), three vacant suites leased in Year 1, office market leases on a base year (the year they start)
and the bank NNN. Blended market leasing: 70% renewal, 9 months vacant, $27 office / $42 bank rising 3% a
year, 3 months free on leases starting in Years 1-3. Cleaning and utilities partly variable, grossed up to
95% occupancy for recoveries; management fee 3% of EGI; 5% general vacancy less modeled vacancy; parking
and storage income.

As the appraiser entered them: market rent growth 0, 0, 5, 6, 6, then 3% (the summary prints 6% through
2016); the vacant suites leased one every four months from April 2011, with no free rent; Citibank's
lease ending October 31, 2013; the March 2011 CPI increase on Flaherty & Crumrine's lease; taxes as 1.125513%
of value growing 2% (reassessed at the Year 11 sale) plus direct assessments growing 3%.

Rent, vacancy, free rent, TI and leasing commissions tie to published DCF software to the dollar. Recoveries are within $8,000
a year of published DCF software's $137,000-$380,000.
"""
import calendar
from datetime import date
from decimal import Decimal as D

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import (
    ExpenseInput,
    FreeRentPeriodInput,
    LeaseInput,
    MarketAssumptions,
    OtherIncomeInput,
    RentStepInput,
    SuiteInput,
    ValuationParams,
)

G3 = D("0.03")

# suite, SF, start, end (None: month-to-month to Dec 2011), monthly rent, first CPI increase
LEASES = [
    ("100", 9590, date(2008, 10, 8), date(2013, 10, 31), 37258, date(2011, 10, 1)),
    ("200A", 9781, date(2010, 3, 1), date(2015, 2, 28), 20220, date(2011, 3, 1)),
    ("204", 1756, None, None, 4220, None),
    ("209", 1200, date(2010, 2, 1), date(2015, 1, 31), 2640, date(2011, 3, 1)),
    ("210", 2450, None, None, 6873, None),
    ("300BC", 2615, date(2008, 5, 1), date(2011, 4, 30), 3944, date(2011, 3, 1)),
    ("304", 490, date(2008, 12, 1), date(2011, 11, 30), 1207, None),
    ("305", 1954, None, None, 3130, None),
    ("315", 1083, None, None, 2764, None),
    ("320", 1590, date(2009, 9, 1), date(2012, 8, 31), 4129, date(2011, 3, 1)),
    ("400", 3736, date(2007, 2, 1), date(2017, 1, 31), 9760, None),
    ("407", 2943, date(2010, 5, 1), date(2015, 4, 30), 7593, date(2011, 3, 1)),
    ("408", 504, None, None, 1286, None),
    ("426", 4578, date(2010, 3, 1), date(2015, 2, 28), 11767, date(2011, 3, 1)),
    ("430", 1907, date(2008, 10, 1), date(2013, 9, 30), 4698, date(2011, 10, 1)),
    ("500", 1435, date(2007, 1, 1), date(2012, 12, 31), 3448, date(2011, 3, 1)),
    ("501", 1741, date(2007, 9, 1), date(2012, 8, 31), 4532, date(2011, 3, 1)),
    ("514", 3610, None, None, 10026, None),
    ("518", 934, None, None, 2610, None),
    ("520", 635, date(2008, 6, 1), date(2013, 5, 31), 1092, None),
    ("522", 512, date(2008, 8, 1), date(2013, 7, 31), 1419, date(2011, 3, 1)),
    ("524", 500, date(2007, 7, 1), date(2012, 6, 30), 866, None),
    ("526", 954, None, None, 2582, None),
    ("527", 318, None, None, 909, None),
    ("528", 930, None, None, 2279, None),
    ("530", 586, date(2007, 7, 1), date(2012, 6, 30), 1698, date(2011, 3, 1)),
    ("600", 1617, date(2008, 11, 1), date(2013, 10, 31), 3844, date(2011, 3, 1)),
    ("610", 1915, date(2010, 4, 1), date(2013, 3, 31), 4557, date(2011, 3, 1)),
    ("611", 750, date(2006, 1, 1), date(2011, 12, 31), 1949, date(2011, 3, 1)),
    ("612", 497, date(2008, 4, 1), date(2011, 3, 31), 1294, None),
    ("614", 2190, date(2010, 6, 1), date(2013, 5, 31), 5804, date(2011, 3, 1)),
    ("616", 1251, None, None, 3375, None),
    ("618", 770, None, None, 1995, None),
    ("620", 820, None, None, 1435, None),
    ("624", 881, None, None, 2247, None),
    ("626", 632, None, None, 1642, None),
    ("628", 1920, None, None, 6326, None),
    ("700", 3756, date(2010, 2, 1), date(2015, 1, 31), 9394, date(2011, 3, 1)),
    ("705", 1537, date(2007, 11, 1), date(2012, 10, 31), 3970, date(2011, 3, 1)),
    ("706", 680, date(2006, 2, 1), date(2011, 1, 31), 1560, None),
    ("709", 675, date(2009, 11, 1), date(2012, 10, 31), 1723, date(2011, 3, 1)),
    ("711", 1435, date(2010, 11, 1), date(2013, 10, 31), 3588, date(2011, 3, 1)),
    ("714", 666, date(2010, 6, 1), date(2013, 5, 31), 1441, date(2011, 3, 1)),
    ("716", 981, date(2007, 4, 1), date(2012, 3, 31), 2702, date(2011, 3, 1)),
    ("720", 3072, date(2009, 1, 1), date(2011, 12, 31), 8355, date(2011, 3, 1)),
    ("800", 3252, None, None, 8254, None),
    ("802", 6725, date(2007, 1, 1), date(2016, 12, 31), 17509, date(2011, 3, 1)),
    ("807", 1517, None, None, 4024, None),
    ("810", 1900, None, None, 4680, None),
    ("900", 14397, date(2005, 3, 1), date(2015, 2, 28), 29386, None),
]
# Vacant suites: leased at $27 rising 3%, five years, $10 TI, 6% commission, no free rent
VACANT = [("202", 935, date(2011, 4, 1)), ("325", 3368, date(2011, 8, 1)), ("707", 865, date(2011, 12, 1))]

PUBLISHED = {
    "base_rent": [3521018, 3524131, 3549624, 3589591, 3764112, 3883315, 4039463, 4194478, 4344729, 4471199, 4595187],
    "turnover_vacancy": [-26699, -259593, -155765, -45001, -291903, -68764, -388318, -101072, -179685, -338395,
                         -58011],
    "free_rent": [-25596, -266014, -81573, -1210, 0, 0, 0, 0, 0, 0, 0],
    "recoveries": [137480, 164299, 187165, 252370, 258936, 297414, 248375, 270382, 269182, 316011, 380323],
    "noi": [1993285, 1717024, 1939182, 2058841, 2150738, 2291753, 2239149, 2467928, 2562062, 2630083, 2752331],
    "ti": [76329, 248691, 65961, 223849, 268161, 60998, 341926, 107682, 263718, 310872, 14108],
    "lc": [64651, 197883, 53503, 123678, 241762, 54993, 308266, 97081, 151354, 280267, 12719],
}
PUBLISHED_VALUE = 25424056
AREA = D(117336)


def _month_end(y, m):
    return date(y, m, calendar.monthrange(y, m)[1])


def _lease(sid, area, start, end, rent, steps=(), free=(), **kw):
    base = dict(
        lease_id=sid, suite_id=sid, tenant_name=sid, area=D(area), start_date=start, end_date=end,
        base_rent_per_unit=rent, rent_payment_frequency="annual",
        escalation_type="fixed_step" if steps else "flat", escalation_pct=None, cpi_floor=None, cpi_cap=None,
        rent_steps=tuple(steps), free_rent_periods=tuple(free),
        recovery_type="nnn" if sid == "100" else "base_year_stop", base_year=None if sid == "100" else 2011,
        pro_rata_share=None, base_year_stop_amount=None, expense_stop_per_sf=None, recovery_overrides=(),
        pct_rent_breakpoint=None, pct_rent_rate=None)
    return LeaseInput(**{**base, **kw})


def _leases():
    out = []
    for sid, area, start, end, monthly, cpi in LEASES:
        start, end = (start, end) if start else (date(2000, 1, 1), date(2011, 12, 31))
        rent = D(monthly) * 12 / area
        steps, free = [], []
        while cpi and cpi <= end:
            rent_k = rent * (1 + G3) ** (len(steps) + 1)
            steps.append(RentStepInput(cpi, rent_k))
            cpi = date(cpi.year + 1, cpi.month, 1)
        if sid == "400":    # $10,087.20 from February 2012; March, June and September 2012 free
            steps = [RentStepInput(date(2012, 2, 1), D("10087.20") * 12 / area)]
            free = [FreeRentPeriodInput(date(2012, m, 1), _month_end(2012, m), True, False) for m in (3, 6, 9)]
        out.append(_lease(sid, area, start, end, rent, steps, free))
    for sid, area, start in VACANT:
        steps = [RentStepInput(date(start.year + k, start.month, 1), D(27) * (1 + G3) ** k) for k in range(1, 5)]
        lc = D("0.06") * area * (D(27) + sum(s.rent_per_unit for s in steps))
        out.append(_lease(sid, area, start, _month_end(start.year + 5, start.month - 1), D(27), steps,
                          committed_ti_amount=D(10) * area, committed_lc_amount=lc))
    return out


def _market(space, rent, ti_new, ti_renewal):
    return MarketAssumptions(
        space_type=space, market_rent_per_unit=D(rent), rent_growth_rate=G3,
        rent_growth_schedule=(D(0), D(0), D("0.05"), D("0.06"), D("0.06"), G3),
        new_lease_term_months=60, renewal_term_months=60, downtime_months=9, renewal_probability=D("0.70"),
        new_ti_per_sf=D(ti_new), renewal_ti_per_sf=D(ti_renewal), new_lc_pct=D("0.06"), renewal_lc_pct=D("0.03"),
        new_free_rent_months=3, renewal_free_rent_months=3, renewal_rent_adjustment_pct=D(0),
        general_vacancy_pct=D("0.05"), credit_loss_pct=D(0), rollover_method="blended",
        lease_escalation_pct=G3, leasing_cost_growth_rate=G3,
        new_free_rent_schedule=(D(3), D(3), D(3), D(0)), renewal_free_rent_schedule=(D(3), D(3), D(3), D(0)))


def _expense(category, amount, growth=G3, recoverable=True, **kw):
    base = dict(expense_id=category, category=category, base_amount=D(amount), growth_rate=growth,
                is_recoverable=recoverable, is_gross_up_eligible=False, gross_up_vacancy_pct=None,
                is_pct_of_egi=False, pct_of_egi=None)
    return ExpenseInput(**{**base, **kw})


GROSS_UP = dict(is_gross_up_eligible=True, gross_up_vacancy_pct=D("0.95"))
AD_VALOREM = D(286202)
EXPENSES = [
    _expense("cleaning", 199471, variable_pct=D("0.70"), **GROSS_UP),
    _expense("repair_maintenance", 352008),
    _expense("utilities", 410676, variable_pct=D("0.50"), **GROSS_UP),
    _expense("general_building", 146670),
    _expense("administration", 88002),
    _expense("management_fee", 0, growth=D(0), is_pct_of_egi=True, pct_of_egi=G3),
    _expense("real_estate_taxes", AD_VALOREM, growth=D("0.02"),     # Year 11: 1.125513% x $34,404,138 sale
             growth_schedule=(D(0),) + (D("0.02"),) * 9 + (D(387226) / (AD_VALOREM * D("1.02") ** 9) - 1,)),
    _expense("direct_assessments", 22032),
    _expense("insurance", 70402),
    _expense("garage", 220000, recoverable=False),
    _expense("non_recoverable", 17600, recoverable=False),
]


def _run(months):
    suites = [SuiteInput(suite_id=sid, suite_name=sid, area=D(area), space_type="bank" if sid == "100" else "office")
              for sid, area, *_ in LEASES + VACANT]
    return run_valuation(
        property_start_date=date(2011, 1, 1), analysis_period_months=months, fiscal_year_end_month=12,
        suites=suites, leases=_leases(),
        market_assumptions={"office": _market("office", 27, 10, 5), "bank": _market("bank", 42, 25, 15)},
        expenses=EXPENSES, property_type="office",
        other_income_items=[OtherIncomeInput("parking", "parking", D(450000), G3),
                            OtherIncomeInput("storage", "storage", D(35000), G3)],
        params=ValuationParams(
            discount_rate=D("0.09"), exit_cap_rate=D("0.08"), exit_cap_year=-1, exit_costs_pct=D("0.02"),
            capital_reserves_per_unit=D("0.50"), capital_reserves_growth_rate=G3, total_property_area=AREA,
            use_mid_year_convention=False, loan_amount=None, interest_rate=None, amortization_months=None,
            loan_term_months=None, io_period_months=0, reduce_general_vacancy_by_downtime=True,
            vacancy_on_gross_revenue=True),
    )


@pytest.fixture(scope="module")
def result():
    r = _run(120)
    return r, list(r.annual_cash_flows) + [_run(132).annual_cash_flows[10]]


def test_suites_and_area(result):
    assert sum(area for _, area, *_ in LEASES + VACANT) == AREA


@pytest.mark.parametrize("line, tol", [("base_rent", 20), ("turnover_vacancy", 10), ("free_rent", 10), ("ti", 5),
                                       ("lc", 5), ("recoveries", 8000), ("noi", 7500)])
def test_cash_flow_matches_published(result, line, tol):
    _, cfs = result
    got = {
        "base_rent": [cf.gross_potential_rent - cf.absorption_vacancy for cf in cfs],   # published DCF software grosses up vacancy
        "turnover_vacancy": [cf.absorption_vacancy for cf in cfs],
        "free_rent": [cf.free_rent for cf in cfs],
        "recoveries": [cf.expense_recoveries for cf in cfs],
        "noi": [cf.net_operating_income for cf in cfs],
        "ti": [-cf.tenant_improvements for cf in cfs],
        "lc": [-cf.leasing_commissions for cf in cfs],
    }[line]
    assert [float(x) for x in got] == pytest.approx(PUBLISHED[line], abs=tol)


def test_value_matches_published(result):
    r, _ = result
    assert float(r.npv) == pytest.approx(PUBLISHED_VALUE, rel=0.002)
