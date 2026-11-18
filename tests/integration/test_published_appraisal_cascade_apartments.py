"""
Parity with the SEC-filed 2004 appraisal of Cascade Apartments, Topeka, Kansas.

Primary source: SEC accession 0001072761-05-000007, exhibit 4:
https://www.sec.gov/Archives/edgar/data/1072761/000107276105000007/sir1_sctoi041505exh4.txt

The report publishes all eleven years of effective gross revenue, operating expenses, reserves,
capital improvements, NOI, cash flow, forward NOI, reversion assumptions, and its present-value
schedule. Revenue and expense components are entered as the report's annual aggregate schedules;
this avoids inventing a unit-level rent roll that the public exhibit does not disclose.
"""
from datetime import date
from decimal import Decimal as D

from src.engine.property_cashflow import run_valuation
from src.engine.types import CapitalProjectInput, ExpenseInput, OtherIncomeInput, ValuationParams


EFFECTIVE_GROSS_REVENUE = [598097, 605025, 628934, 641637, 654598, 667826, 681320, 695088, 709135, 723469, 738092]
OPERATING_EXPENSES = [312188, 321268, 331193, 340821, 350732, 360932, 371434, 382243, 393371, 404822, 416615]
CAPITAL_COSTS = [87750, 22145, 22809, 23494, 24198, 24924, 25672, 26442, 27236, 28053, 28894]
CASH_FLOW = [198159, 261612, 274932, 277322, 279668, 281970, 284214, 286403, 288528, 290594]
PUBLISHED_VALUE = D(2650076)


def _growth_schedule(values):
    return tuple([D(0)] + [D(current) / D(previous) - 1 for previous, current in zip(values, values[1:])])


def _run():
    income = OtherIncomeInput(
        "effective_gross_revenue", "effective_gross_revenue", D(EFFECTIVE_GROSS_REVENUE[0]), D(0),
        _growth_schedule(EFFECTIVE_GROSS_REVENUE),
    )
    expenses = ExpenseInput(
        expense_id="operating_expenses", category="operating_expenses", base_amount=D(OPERATING_EXPENSES[0]),
        growth_rate=D(0), is_recoverable=False, is_gross_up_eligible=False, gross_up_vacancy_pct=None,
        is_pct_of_egi=False, pct_of_egi=None, growth_schedule=_growth_schedule(OPERATING_EXPENSES),
    )
    capital = [
        CapitalProjectInput(str(year), "reserves and improvements", D(amount), date(2004 + year, 5, 1), 1)
        for year, amount in enumerate(CAPITAL_COSTS)
    ]
    return run_valuation(
        property_start_date=date(2004, 5, 1), analysis_period_months=120, fiscal_year_end_month=4,
        suites=[], leases=[], market_assumptions={}, expenses=[expenses], capital_projects=capital,
        other_income_items=[income], property_type="multifamily",
        params=ValuationParams(
            # Precision inferred inside the report's displayed 11.00% interval.
            discount_rate=D("0.1099999860329680932505273929"), exit_cap_rate=D("0.1025"), exit_cap_year=-1,
            exit_costs_pct=D("0.02"), capital_reserves_per_unit=D(0), total_property_area=D(86),
            use_mid_year_convention=False, loan_amount=None, interest_rate=None, amortization_months=None,
            loan_term_months=None, io_period_months=0,
        ),
    )


def test_published_annual_cash_flow():
    assert [cf.cash_flow_before_debt.quantize(D("1")) for cf in _run().annual_cash_flows] == list(map(D, CASH_FLOW))


def test_exact_published_value():
    assert abs(_run().npv - PUBLISHED_VALUE) < D("0.01")

