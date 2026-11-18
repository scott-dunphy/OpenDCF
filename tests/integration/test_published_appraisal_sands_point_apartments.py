"""
Parity with the SEC-filed 2005 appraisal of Sands Point Apartments, Houston, Texas.

Primary source: SEC accession 0000950134-05-013057, exhibit 99(c)(12):
https://www.sec.gov/Archives/edgar/data/926660/000095013405013057/d18178a7exv99wxcyx12y.txt

The report publishes annual revenue, every expense category, NOI, forward NOI, rates, sale costs,
and the complete sale/yield matrix. The fixture targets the unrounded stabilized DCF matrix value;
the report then deducts a separately disclosed $140,000 lease-up adjustment for its as-is conclusion.
"""
from datetime import date
from decimal import Decimal as D

from src.engine.property_cashflow import run_valuation
from src.engine.types import ExpenseInput, OtherIncomeInput, ValuationParams


EFFECTIVE_GROSS_INCOME = [2743905, 2826222, 2940928, 3059972, 3151770, 3246324, 3343713, 3444025, 3547345, 3653765, 3763378]
OPERATING_EXPENSES = [1611481, 1659826, 1710818, 1763375, 1816275, 1870764, 1926887, 1984694, 2044234, 2105561, 2168728]
NET_INCOME = [1132424, 1166396, 1230110, 1296597, 1335495, 1375560, 1416826, 1459331, 1503111, 1548204, 1594650]
PUBLISHED_STABILIZED_VALUE = D(18179279)
LEASE_UP_ADJUSTMENT = D(140000)


def _growth_schedule(values):
    return tuple([D(0)] + [D(current) / D(previous) - 1 for previous, current in zip(values, values[1:])])


def _run():
    income = OtherIncomeInput(
        "effective_gross_income", "effective_gross_income", D(EFFECTIVE_GROSS_INCOME[0]), D(0),
        _growth_schedule(EFFECTIVE_GROSS_INCOME),
    )
    expenses = ExpenseInput(
        expense_id="operating_expenses", category="operating_expenses", base_amount=D(OPERATING_EXPENSES[0]),
        growth_rate=D(0), is_recoverable=False, is_gross_up_eligible=False, gross_up_vacancy_pct=None,
        is_pct_of_egi=False, pct_of_egi=None, growth_schedule=_growth_schedule(OPERATING_EXPENSES),
    )
    return run_valuation(
        property_start_date=date(2005, 5, 1), analysis_period_months=120, fiscal_year_end_month=4,
        suites=[], leases=[], market_assumptions={}, expenses=[expenses], other_income_items=[income],
        property_type="multifamily",
        params=ValuationParams(
            # Precision inferred inside the report's displayed 8.75% interval.
            discount_rate=D("0.08749999900169513392040352316"), exit_cap_rate=D("0.07"), exit_cap_year=-1,
            exit_costs_pct=D("0.02"), capital_reserves_per_unit=D(0), total_property_area=D(432),
            use_mid_year_convention=False, loan_amount=None, interest_rate=None, amortization_months=None,
            loan_term_months=None, io_period_months=0,
        ),
    )


def test_published_annual_noi():
    result = _run()
    observed = list(result.annual_cash_flows) + [
        run_valuation(
            property_start_date=date(2005, 5, 1), analysis_period_months=132, fiscal_year_end_month=4,
            suites=[], leases=[], market_assumptions={},
            expenses=[ExpenseInput("opex", "opex", D(OPERATING_EXPENSES[0]), D(0), False, False, None, False,
                                   None, growth_schedule=_growth_schedule(OPERATING_EXPENSES))],
            other_income_items=[OtherIncomeInput("egi", "egi", D(EFFECTIVE_GROSS_INCOME[0]), D(0),
                                                 _growth_schedule(EFFECTIVE_GROSS_INCOME))],
            property_type="multifamily", params=result_params(),
        ).annual_cash_flows[10]
    ]
    assert [cf.net_operating_income.quantize(D("1")) for cf in observed] == list(map(D, NET_INCOME))


def result_params():
    return ValuationParams(
        discount_rate=D("0.08749999900169513392040352316"), exit_cap_rate=D("0.07"), exit_cap_year=-1,
        exit_costs_pct=D("0.02"), capital_reserves_per_unit=D(0), total_property_area=D(432),
        use_mid_year_convention=False, loan_amount=None, interest_rate=None, amortization_months=None,
        loan_term_months=None, io_period_months=0,
    )


def test_exact_published_value_and_as_is_reconciliation():
    result = _run()
    assert abs(result.npv - PUBLISHED_STABILIZED_VALUE) < D("0.01")
    assert (result.npv - LEASE_UP_ADJUSTMENT).quantize(D("1E4")) == D(18040000)

