"""
Parity with two published published DCF software appraisals of one building: the GSA Office at 4211 Cedar Springs Road,
Dallas TX, a 39,329 SF office building leased to the federal government (GSA). Integra Realty Resources
appraised it for Kent International as of March 2, 2011 (PUBLISHED Ver. 14.0.2; SC 13E3/A of 2011-09-29,
accession 0001096906-11-002287, exhibit (e)) and as of November 9, 2012 (PUBLISHED Ver. 15.0.1.26; Kent
Financial's SC 13E3/A of 2013-02-08, accession 0001096906-13-000169, exhibit (e)). Each prints the published DCF software
cash flow; the 2011 report also prints the rent roll and the calendar-year expenses used for recoveries.

Common: fiscal years that do not end in December, recoveries billed on calendar years, the GSA lease
reimbursing taxes over a $70,189 stop, the GSA's CPI operating-cost adjustment as other income (as the
appraiser entered it), expenses growing 3%, a management fee as a percent of EGI, and a market lease
on a base-year stop rising $0.50/SF a year.

Exercises: a market lease's base year is the calendar year it starts, its stops are that calendar
year's expenses, and the management fee's stop is the calendar year's monthly fee (low in the vacant
months); and fixed $/SF market lease escalations, which the leasing commission counts.

2011: fiscal years ending February; the lease runs to January 2023 (rent $15.85 from January 2018);
market leasing 50% renewal, 8 months vacant, $28 new / $12 renewal TI, 6% / 3% commissions, 5-year
term; market rent growth 0, 0, 1.5, 2.5, then 3%; reserves above NOI; 0% general vacancy for 11 years
and 14% after, reduced by downtime. 13-year hold, Year 14 capitalized at 8.25% less 2%, 8.25% discount.

2012: fiscal years ending November; the GSA rent rises with a 3% CPI each January and the GSA leaves
at its December 2017 termination option; 6 months vacant, $30 TI, 6.75% commission on a 10-year term;
4% general vacancy reduced by downtime; reserves below NOI. 10-year hold, Year 11 capitalized at 8.25%
less 1.5%, 9% discount.
"""
from datetime import date
from decimal import Decimal as D

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import (
    ExpenseInput,
    ExpenseRecoveryOverride,
    LeaseInput,
    MarketAssumptions,
    OtherIncomeInput,
    RentStepInput,
    SuiteInput,
    ValuationParams,
)

G3 = D("0.03")
AREA = D(39329)
RENT = D(746464)

PUBLISHED_2011 = {
    "rent": [746464] * 6 + [725948, 623365, 623365, 623365, 623365, 651326, 987665, 1002413],
    "turnover_vacancy": [0] * 11 + [-79908, -246916, 0],
    "recoveries": [0, 278, 2028, 4194, 6426, 8724, 11092, 13530, 16042, 18629, 21293, 21839, 3757, 24519],
    "noi": [457498, 455366, 454399, 454539, 453525, 453262, 433119, 334058, 334111, 332977, 332565, 178969,
            326477, 447824],
    "ti": [0] * 12 + [1121475, 0],
    "lc": [0] * 12 + [231074, 0],
}
VALUE_2011 = 4567684

PUBLISHED_2012 = {
    "rent": [766992, 790002, 813702, 838113, 863256, 866193, 874462, 894127, 913791, 933456, 953120],
    "turnover_vacancy": [0, 0, 0, 0, 0, -433134, 0, 0, 0, 0, 0],
    "recoveries": [47924, 51467, 55117, 58876, 62748, 5256, 22032, 35278, 47864, 60810, 74127],
    "noi": [461543, 482380, 503672, 526367, 549550, 58916, 457577, 476908, 495282, 513644, 531989],
    "ti": [0, 0, 0, 0, 0, 1367793, 0, 0, 0, 0, 0],
    "lc": [0, 0, 0, 0, 0, 644462, 0, 0, 0, 0, 0],
}
VALUE_2012 = 4358875


def _gsa_lease(end, steps):
    """The GSA reimburses taxes over $70,189 and nothing else."""
    no_recovery = tuple(ExpenseRecoveryOverride(c, "none", None, None, None, None)
                        for c in ("insurance", "utilities", "repairs", "cleaning", "grounds", "admin",
                                  "management_fee"))
    return LeaseInput(
        lease_id="GSA", suite_id="100", tenant_name="GSA", area=AREA, start_date=date(2008, 1, 1), end_date=end,
        base_rent_per_unit=RENT / AREA, rent_payment_frequency="annual", escalation_type="fixed_step",
        escalation_pct=None, cpi_floor=None, cpi_cap=None, rent_steps=steps, free_rent_periods=(),
        recovery_type="base_year_stop", pro_rata_share=None, base_year_stop_amount=None, expense_stop_per_sf=None,
        recovery_overrides=(ExpenseRecoveryOverride("real_estate_taxes", "base_year_stop", D(70189), None, None,
                                                    None),) + no_recovery,
        pct_rent_breakpoint=None, pct_rent_rate=None)


def _expense(category, amount, **kw):
    base = dict(expense_id=category, category=category, base_amount=D(amount), growth_rate=G3, is_recoverable=True,
                is_gross_up_eligible=False, gross_up_vacancy_pct=None, is_pct_of_egi=False, pct_of_egi=None)
    return ExpenseInput(**{**base, **kw})


def _expenses(taxes, fee_pct):
    return [
        _expense("real_estate_taxes", taxes), _expense("insurance", 7866), _expense("utilities", 81804),
        _expense("repairs", 39329), _expense("cleaning", 58207), _expense("grounds", 5506),
        _expense("admin", 5113),
        _expense("management_fee", 0, growth_rate=D(0), is_pct_of_egi=True, pct_of_egi=D(fee_pct)),
    ]


def _cpi_adjustment(amounts):
    """The GSA's CPI operating-cost adjustment, $000 by year as entered, then none."""
    rates = tuple(D(b) / D(a) - 1 for a, b in zip(amounts, amounts[1:]))
    return OtherIncomeInput("cpi_adjustment", "cpi_adjustment", D(amounts[0]) * 1000, D(0),
                            growth_schedule=(D(0),) + rates + (D(-1),))


def _market(rent, **kw):
    base = dict(
        space_type="office", market_rent_per_unit=D(rent), rent_growth_rate=G3, new_lease_term_months=60,
        new_ti_per_sf=D(30), new_lc_pct=D("0.0675"), new_free_rent_months=0, downtime_months=6,
        renewal_probability=D(0), renewal_term_months=60, renewal_ti_per_sf=D(0), renewal_lc_pct=D("0.03"),
        renewal_free_rent_months=0, renewal_rent_adjustment_pct=D(0), general_vacancy_pct=D(0),
        credit_loss_pct=D(0), rollover_method="blended", leasing_cost_growth_rate=G3,
        lease_escalation_per_unit=D("0.50"), recovery_type="base_year_stop")
    return MarketAssumptions(**{**base, **kw})


def _params(**kw):
    base = dict(
        discount_rate=D("0.0825"), exit_cap_rate=D("0.0825"), exit_cap_year=-1, exit_costs_pct=D("0.02"),
        capital_reserves_per_unit=D(0), capital_reserves_growth_rate=G3, total_property_area=AREA,
        use_mid_year_convention=False, loan_amount=None, interest_rate=None, amortization_months=None,
        loan_term_months=None, io_period_months=0, calendar_year_recoveries=True, vacancy_on_gross_revenue=True,
        reduce_general_vacancy_by_downtime=True)
    return ValuationParams(**{**base, **kw})


def _run_2011(months):
    market = _market(
        "18.50", rent_growth_schedule=(D(0), D(0), D("0.015"), D("0.025"), G3), new_ti_per_sf=D(28),
        new_lc_pct=D("0.06"), downtime_months=8, renewal_probability=D("0.50"), renewal_ti_per_sf=D(12),
        general_vacancy_pct=D("0.14"), general_vacancy_schedule=(D(0),) * 11 + (D("0.14"),))
    expenses = _expenses(68063, "0.041") + [_expense("reserves", 5899, is_recoverable=False)]
    return run_valuation(
        property_start_date=date(2011, 3, 1), analysis_period_months=months, fiscal_year_end_month=2,
        suites=[SuiteInput("100", "100", AREA, "office")],
        leases=[_gsa_lease(date(2023, 1, 31), (RentStepInput(date(2018, 1, 1), D("15.85")),))],
        market_assumptions={"office": market}, expenses=expenses, property_type="office",
        other_income_items=[_cpi_adjustment([14, 20, 26, 33, 39, 46, 53, 60, 68, 75, 83])], params=_params())


def _run_2012(months):
    cpi_steps = tuple(RentStepInput(date(2013 + k, 1, 1), D("1.03") ** (k + 1) * RENT / AREA) for k in range(5))
    market = _market("19", new_lease_term_months=120, renewal_term_months=120, general_vacancy_pct=D("0.04"))
    return run_valuation(
        property_start_date=date(2012, 12, 1), analysis_period_months=months, fiscal_year_end_month=11,
        suites=[SuiteInput("100", "100", AREA, "office")], leases=[_gsa_lease(date(2017, 12, 31), cpi_steps)],
        market_assumptions={"office": market}, expenses=_expenses(118105, "0.03"), property_type="office",
        other_income_items=[_cpi_adjustment([20, 26, 32, 39, 46])],
        params=_params(discount_rate=D("0.09"), exit_costs_pct=D("0.015"), capital_reserves_per_unit=D("0.15")),
    )


def _lines(cfs):
    return {
        "rent": [cf.gross_potential_rent - cf.absorption_vacancy for cf in cfs],   # published DCF software grosses up vacancy
        "turnover_vacancy": [cf.absorption_vacancy for cf in cfs],
        "recoveries": [cf.expense_recoveries for cf in cfs],
        "noi": [cf.net_operating_income for cf in cfs],
        "ti": [-cf.tenant_improvements for cf in cfs],
        "lc": [-cf.leasing_commissions for cf in cfs],
    }


# published DCF software computes the hold year's calendar recoveries knowing the next year, so compare the longer run
@pytest.mark.parametrize("run, months, published", [(_run_2011, 168, PUBLISHED_2011), (_run_2012, 132, PUBLISHED_2012)],
                         ids=["2011", "2012"])
@pytest.mark.parametrize("line, tol", [("rent", 2), ("turnover_vacancy", 2), ("recoveries", 120), ("noi", 100),
                                       ("ti", 2), ("lc", 2)])
def test_cash_flow_matches_published(run, months, published, line, tol):
    got = _lines(run(months).annual_cash_flows)[line]
    assert [float(x) for x in got] == pytest.approx(published[line], abs=tol)


@pytest.mark.parametrize("run, months, value", [(_run_2011, 156, VALUE_2011), (_run_2012, 120, VALUE_2012)],
                         ids=["2011", "2012"])
def test_value_matches_published(run, months, value):
    assert float(run(months).npv) == pytest.approx(value, rel=0.0001)
