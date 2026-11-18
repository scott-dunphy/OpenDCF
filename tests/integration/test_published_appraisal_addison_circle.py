"""Reproduce the SEC-filed 2004 Addison Circle multi-tenant office DCF.

Primary source: https://www.sec.gov/Archives/edgar/data/1031316/000117152004000315/addison.txt
The exhibit publishes the rent roll, all annual income, expense and leasing/capital schedules,
the terminal sale, and a monthly-discounted present-value matrix.
"""
from datetime import date
from decimal import Decimal as D

from src.engine.property_cashflow import run_valuation
from src.engine.types import CapitalProjectInput, ExpenseInput, OtherIncomeInput, ValuationParams


EGR = [7571236, 7742172, 7350506, 7551662, 7416547, 7771041, 8623995, 8785339, 9297680, 9982843]
EXPENSES = [2533286, 2619130, 2690919, 2783419, 2868854, 2972114, 3093565, 3197625, 3315688, 3442530]
CAPITAL = [938356, 120549, 1458291, 48859, 111913, 1627057, 1001636, 56067, 1814344, 132917]
RESERVES = [44068, 45610, 47207, 48859, 50569, 52339, 54171, 56067, 58029, 60060]
TENANT_IMPROVEMENTS = [722995, 60703, 1129548, 0, 48497, 1244935, 749043, 0, 1388501, 57599]
LEASING_COMMISSIONS = [171293, 14236, 281536, 0, 12847, 329783, 198422, 0, 367814, 15258]
CASH_FLOW = [4099594, 5002493, 3201296, 4719384, 4435780, 3171870, 4528794, 5531647, 4167648, 6407396]
NET_RESALE = 71216741
PUBLISHED_VALUE = D(55878744)


def _growth(values):
    return tuple([D(0)] + [D(b) / D(a) - 1 for a, b in zip(values, values[1:])])


def _run():
    rollover_dates = [
        date(2005, 3, 1), date(2006, 5, 1), date(2007, 4, 1), None,
        date(2008, 9, 1), date(2010, 1, 1), date(2011, 1, 1), None,
        date(2013, 4, 1), date(2014, 4, 1),
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
            discount_rate=D("0.10"), exit_cap_rate=D("0.09"), exit_cap_year=10, exit_costs_pct=D("0.02"),
            capital_reserves_per_unit=D(0), total_property_area=D(293787), use_mid_year_convention=False,
            loan_amount=None, interest_rate=None, amortization_months=None, loan_term_months=None, io_period_months=0,
            discounting_convention="monthly",
        ),
    )


def test_published_annual_cash_flow_and_resale():
    actual = [x.cash_flow_before_debt.quantize(D("1")) for x in _run().annual_cash_flows]
    assert actual == list(map(D, CASH_FLOW))


def test_monthly_value_matches_published_schedule_within_disclosed_timing_limit():
    # The filing publishes annual cash flow but not its underlying monthly schedule.
    assert abs(_run().npv - PUBLISHED_VALUE) < D("226000")


def test_monthly_discounting_irr_reproduces_discount_rate():
    assert abs(_run().irr - D("0.10")) < D("0.000001")


def test_monthly_discounting_rejects_mid_year_convention():
    from dataclasses import replace

    import pytest

    with pytest.raises(ValueError, match="mid_year"):
        run_valuation(
            property_start_date=date(2004, 7, 1), analysis_period_months=12, fiscal_year_end_month=6,
            suites=[], leases=[], market_assumptions={}, expenses=[],
            params=replace(
                ValuationParams(
                    discount_rate=D("0.10"), exit_cap_rate=D("0.09"), exit_cap_year=-1, exit_costs_pct=D(0),
                    capital_reserves_per_unit=D(0), total_property_area=D(1), use_mid_year_convention=True,
                    loan_amount=None, interest_rate=None, amortization_months=None, loan_term_months=None,
                    io_period_months=0,
                ),
                discounting_convention="monthly",
            ),
        )
