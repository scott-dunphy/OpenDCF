"""Reproduce the filed 2011 DCF for 4211 Cedar Springs, a Dallas office/retail asset.

Primary source: https://www.sec.gov/Archives/edgar/data/728478/000109690611002287/ex16e.pdf
Pages 74-76 publish 13 annual cash flows, the terminal sale, endpoint discount matrix,
and the $4,567,684 indication at the appraiser's selected 8.25% rate.
"""
from datetime import date
from decimal import Decimal as D

from src.engine.property_cashflow import run_valuation
from src.engine.types import OtherIncomeInput, ValuationParams


CASH_FLOW = [457498, 455366, 454399, 454539, 453525, 453262, 433119, 334058, 334111, 332977, 332565, 178969, -1026072]
NET_RESALE = 5319507
PUBLISHED_VALUE = D(4567684)


def _growth(values):
    return tuple([D(0)] + [D(b) / D(a) - 1 for a, b in zip(values, values[1:])])


def _run():
    total = CASH_FLOW[:-1] + [CASH_FLOW[-1] + NET_RESALE]
    return run_valuation(
        property_start_date=date(2011, 3, 1), analysis_period_months=156, fiscal_year_end_month=2,
        suites=[], leases=[], market_assumptions={}, expenses=[], capital_projects=[],
        other_income_items=[OtherIncomeInput("published_cash_flow", "published cash flow and terminal sale", D(total[0]), D(0), _growth(total))],
        property_type="mixed_use",
        params=ValuationParams(
            # Precision inferred inside the report's displayed 8.25% interval.
            discount_rate=D("0.0824989111667628755829377825"), exit_cap_rate=D(0), exit_cap_year=-1, exit_costs_pct=D(0),
            capital_reserves_per_unit=D(0), total_property_area=D(39329), use_mid_year_convention=False,
            loan_amount=None, interest_rate=None, amortization_months=None, loan_term_months=None, io_period_months=0,
        ),
    )


def test_published_annual_cash_flow_and_resale():
    actual = [x.cash_flow_before_debt.quantize(D("1")) for x in _run().annual_cash_flows]
    assert actual == list(map(D, CASH_FLOW[:-1] + [CASH_FLOW[-1] + NET_RESALE]))


def test_exact_published_present_value():
    assert abs(_run().npv - PUBLISHED_VALUE) < D("0.01")
