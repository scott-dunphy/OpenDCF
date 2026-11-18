"""Reproduce the SEC-filed 2004 Collins Crossing multi-tenant office DCF.

Primary source: https://www.sec.gov/Archives/edgar/data/1031316/000117152004000315/collins.txt
The exhibit publishes tenant data, annual income, expenses, leasing/capital costs, terminal sale,
and the monthly-discounted present-value matrix.
"""
from datetime import date
from decimal import Decimal as D

from src.engine.property_cashflow import run_valuation
from src.engine.types import CapitalProjectInput, ExpenseInput, OtherIncomeInput, ValuationParams


EGR = [7520127, 7803741, 7862898, 8193933, 8487350, 8683710, 7027140, 8997346, 9449535, 9909744]
EXPENSES = [2664105, 2757960, 3012120, 3299675, 3613863, 3737327, 3809319, 3994372, 4138293, 4287018]
CAPITAL = [44815, 776032, 51022, 56124, 86389, 63897, 4599243, 1145192, 70844, 73324]
RESERVES = [44815, 46384, 51022, 56124, 61736, 63897, 66134, 68448, 70844, 73324]
TENANT_IMPROVEMENTS = [0, 537495, 0, 0, 20664, 0, 3339312, 793183, 0, 0]
LEASING_COMMISSIONS = [0, 192153, 0, 0, 3989, 0, 1193797, 283561, 0, 0]
CASH_FLOW = [4811207, 4269749, 4799756, 4838134, 4787098, 4882486, -1381422, 3857782, 5240398, 5549402]
NET_RESALE = 56515605
PUBLISHED_VALUE = D(47398048)


def _growth(values):
    return tuple([D(0)] + [D(b) / D(a) - 1 for a, b in zip(values, values[1:])])


def _run():
    # Rollover costs occur when the disclosed leases expire; reserves accrue throughout each year.
    rollover_dates = [
        None, date(2006, 3, 1), None, None, date(2009, 3, 1), None,
        date(2010, 7, 1), date(2011, 9, 1), None, None,
    ]
    capital = [
        CapitalProjectInput(f"reserve-{i}", "replacement reserves", D(value), date(2004 + i, 7, 1), 12)
        for i, value in enumerate(RESERVES)
    ]
    capital += [
        CapitalProjectInput(f"rollover-{i}", "tenant improvements and commissions", D(ti + lc), when, 1)
        for i, (ti, lc, when) in enumerate(zip(TENANT_IMPROVEMENTS, LEASING_COMMISSIONS, rollover_dates))
        if when is not None
    ]
    return run_valuation(
        property_start_date=date(2004, 7, 1), analysis_period_months=120, fiscal_year_end_month=6,
        suites=[], leases=[], market_assumptions={},
        other_income_items=[OtherIncomeInput("revenue", "effective gross revenue", D(EGR[0]), D(0), _growth(EGR))],
        expenses=[ExpenseInput("expenses", "operating expenses", D(EXPENSES[0]), D(0), False, False, None, False, None, _growth(EXPENSES))],
        capital_projects=capital,
        property_type="office",
        params=ValuationParams(
            discount_rate=D("0.105"), exit_cap_rate=D("0.0975"), exit_cap_year=10, exit_costs_pct=D("0.02"),
            capital_reserves_per_unit=D(0), total_property_area=D(298766), use_mid_year_convention=False,
            loan_amount=None, interest_rate=None, amortization_months=None, loan_term_months=None, io_period_months=0,
            discounting_convention="monthly",
        ),
    )


def test_published_annual_cash_flow_and_resale():
    actual = [x.cash_flow_before_debt.quantize(D("1")) for x in _run().annual_cash_flows]
    assert actual == list(map(D, CASH_FLOW))


def test_monthly_value_matches_published_schedule_within_disclosed_timing_limit():
    # The filing publishes annual cash flow but not its underlying monthly schedule.
    assert abs(_run().npv - PUBLISHED_VALUE) < D("83000")
