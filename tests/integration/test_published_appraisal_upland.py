"""
Parity with a published published DCF software appraisal: Upland Town & Country Center, 152-158 W. Foothill Boulevard,
Upland CA, an 11,763 SF strip center with six tenants, appraised by Cushman & Wakefield as of December
10, 2010 (published DCF software, 10-year hold). Filed by Wesco Financial with the SEC in 2011 (SC 13E3/A of 2011-04-18,
accession 0001193125-11-099914, exhibit (c)(10)), which prints the rent roll, leasing assumptions,
expense conclusions and the published DCF software cash flow.

The model: fiscal years ending November; in-place leases rising 3% on each anniversary (the appraisal's
CPI increases); every lease rolling within four years to blended market leasing (65% renewal, 6 months
vacant, $9 shops / $12 Suite 152 rising 3% a year, $2.50 new TI, 6% new / 3% renewal commissions,
5-year terms, net reimbursement); management fee 4% of EGI; 8% general vacancy and 2% collection loss
on gross revenue, the vacancy reduced by downtime; recoveries billed on calendar years.

As the appraiser entered them: market rent flat through Year 3 and up 3% a year from Year 4 (the
summary prints "0% Yrs. 1-2"); commissions on the whole term at 6% and 3% (the text describes 6% for
years 1-3 and 3% after); taxes reassessed in Year 11.

The gross tenants reimburse nothing. The modified-gross tenants' terms are not given: they are modeled
as reimbursing a flat $2.21/SF a year, the $10,109 published DCF software shows in Year 1 (the history shows $10,108
every year), as caps below their pro-rata share; market leases reimburse their full share.
"""
from datetime import date
from decimal import Decimal as D

import pytest

from src.engine.date_utils import add_months
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

G3 = D("0.03")
AREA = D(11763)
START = date(2010, 12, 1)

# suite, SF, start, end, rent per year, reimbursement, market
LEASES = [
    ("158-C", 2329, date(2007, 9, 1), date(2012, 8, 31), 30900, "gross", "shops"),        # Arigato Sushi
    ("156-A", 2328, date(2009, 7, 1), date(2014, 6, 30), 26532, "modified", "shops"),     # Juan Pollo
    ("158-A", 1148, date(2007, 4, 1), date(2012, 3, 31), 15156, "modified", "shops"),     # Luxor Salon
    ("154-A", 1095, date(2008, 8, 1), date(2013, 7, 31), 11160, "modified", "shops"),     # The UPS Store
    ("154-B", 1499, date(2008, 8, 1), date(2013, 7, 31), 16464, "gross", "shops"),        # Uptown Cleaners
    ("152-A", 3364, date(2009, 5, 1), date(2014, 4, 30), 51048, "gross", "152"),          # Mi Ranchito
]
YEAR_1_EXPENSES = {"insurance": D(4117), "cam": D(47052), "real_estate_taxes": D(11862), "management_fee": D(5883)}
MODIFIED_SHARE = D("0.377")   # of pro-rata share, Year 1: $10,109 / 4,571 SF = $2.21/SF

PUBLISHED = {
    "rent": [153297, 151110, 142426, 129309, 121426, 125069, 128590, 132214, 136796, 140532, 144749],
    "turnover_vacancy": [0, -5216, -3892, -10527, 0, 0, -3904, -6536, -12204, 0, 0],
    "recoveries": [10109, 12999, 30935, 54431, 77569, 79808, 79151, 79878, 79507, 89274, 92777],
    "general_vacancy": [-13072, -7913, -9977, -4172, -15920, -16390, -12715, -10431, -5100, -18384, -19002],
    "noi": [78152, 77086, 83233, 90452, 101501, 104598, 105106, 106817, 108403, 117613, 120931],
    "ti": [0, 3134, 2408, 5442, 0, 0, 1199, 2506, 9185, 0, 0],
    "lc": [0, 6729, 5020, 13580, 0, 0, 2500, 5225, 21737, 0, 0],
}
PUBLISHED_VALUE = 1120031


def _lease(suite, area, start, end, rent, reimbursement):
    # 3% on each anniversary after the analysis starts (rent is the current rent)
    steps, k = [], 1
    while add_months(start, 12 * k) <= end:
        step = add_months(start, 12 * k)
        if step > START:
            steps.append(RentStepInput(step, D(rent) * (1 + G3) ** (len(steps) + 1) / area))
        k += 1
    if reimbursement == "gross":
        overrides = tuple(ExpenseRecoveryOverride(c, "none", None, None, None, None) for c in YEAR_1_EXPENSES)
    else:
        # A cap in its own group, so it also caps the management fee
        overrides = tuple(ExpenseRecoveryOverride(c, "nnn", None, MODIFIED_SHARE * amount / AREA, None, None,
                                                  cap_group=c)
                          for c, amount in YEAR_1_EXPENSES.items())
    return LeaseInput(
        lease_id=suite, suite_id=suite, tenant_name=suite, area=D(area), start_date=start, end_date=end,
        base_rent_per_unit=D(rent) / area, rent_payment_frequency="annual", escalation_type="fixed_step",
        escalation_pct=None, cpi_floor=None, cpi_cap=None, rent_steps=tuple(steps), free_rent_periods=(),
        recovery_type="nnn", pro_rata_share=None, base_year_stop_amount=None, expense_stop_per_sf=None,
        recovery_overrides=overrides, pct_rent_breakpoint=None, pct_rent_rate=None)


def _market(space, rent):
    return MarketAssumptions(
        space_type=space, market_rent_per_unit=D(rent), rent_growth_rate=G3,
        rent_growth_schedule=(D(0), D(0), D(0), G3), new_lease_term_months=60, renewal_term_months=60,
        downtime_months=6, renewal_probability=D("0.65"), new_ti_per_sf=D("2.50"), renewal_ti_per_sf=D(0),
        new_lc_pct=D("0.06"), renewal_lc_pct=D("0.03"), new_free_rent_months=0, renewal_free_rent_months=0,
        renewal_rent_adjustment_pct=D(0), general_vacancy_pct=D("0.08"), credit_loss_pct=D("0.02"),
        rollover_method="blended", lease_escalation_pct=G3, leasing_cost_growth_rate=G3, recovery_type="nnn")


def _expense(category, amount, growth=G3, **kw):
    base = dict(expense_id=category, category=category, base_amount=D(amount), growth_rate=growth,
                is_recoverable=True, is_gross_up_eligible=False, gross_up_vacancy_pct=None, is_pct_of_egi=False,
                pct_of_egi=None)
    return ExpenseInput(**{**base, **kw})


TAXES = YEAR_1_EXPENSES["real_estate_taxes"]
EXPENSES = [
    _expense("insurance", YEAR_1_EXPENSES["insurance"]),
    _expense("cam", YEAR_1_EXPENSES["cam"]),
    _expense("real_estate_taxes", TAXES, growth=D("0.02"),          # Year 11 reassessed at $15,524
             growth_schedule=(D(0),) + (D("0.02"),) * 9 + (D(15524) / (TAXES * D("1.02") ** 9) - 1,)),
    _expense("management_fee", 0, growth=D(0), is_pct_of_egi=True, pct_of_egi=D("0.04")),
]


def _run(months):
    return run_valuation(
        property_start_date=START, analysis_period_months=months, fiscal_year_end_month=11,
        suites=[SuiteInput(s, s, D(area), market) for s, area, *_, market in LEASES],
        leases=[_lease(*row[:6]) for row in LEASES],
        market_assumptions={"shops": _market("shops", 9), "152": _market("152", 12)}, expenses=EXPENSES,
        property_type="retail",
        params=ValuationParams(
            discount_rate=D("0.0925"), exit_cap_rate=D("0.0825"), exit_cap_year=-1, exit_costs_pct=D("0.03"),
            capital_reserves_per_unit=D("0.20"), capital_reserves_growth_rate=G3, total_property_area=AREA,
            use_mid_year_convention=False, loan_amount=None, interest_rate=None, amortization_months=None,
            loan_term_months=None, io_period_months=0, vacancy_on_gross_revenue=True,
            reduce_general_vacancy_by_downtime=True, calendar_year_recoveries=True),
    )


@pytest.fixture(scope="module")
def result():
    r = _run(120)
    return r, list(r.annual_cash_flows) + [_run(132).annual_cash_flows[10]]


@pytest.mark.parametrize("line, tol", [("rent", 3), ("turnover_vacancy", 2), ("recoveries", 150),
                                       ("general_vacancy", 15), ("noi", 150), ("ti", 2), ("lc", 2)])
def test_cash_flow_matches_published(result, line, tol):
    _, cfs = result
    got = {
        "rent": [cf.gross_potential_rent - cf.absorption_vacancy for cf in cfs],   # published DCF software grosses up vacancy
        "turnover_vacancy": [cf.absorption_vacancy for cf in cfs],
        "recoveries": [cf.expense_recoveries for cf in cfs],
        "general_vacancy": [cf.general_vacancy_loss for cf in cfs],
        "noi": [cf.net_operating_income for cf in cfs],
        "ti": [-cf.tenant_improvements for cf in cfs],
        "lc": [-cf.leasing_commissions for cf in cfs],
    }[line]
    assert [float(x) for x in got] == pytest.approx(PUBLISHED[line], abs=tol)


def test_value_matches_published(result):
    r, _ = result
    assert float(r.npv) == pytest.approx(PUBLISHED_VALUE, rel=0.001)
