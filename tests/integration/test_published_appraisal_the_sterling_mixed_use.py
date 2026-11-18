"""
Parity with the SEC-filed 2010 appraisal of The Sterling in Philadelphia, Pennsylvania.

Primary source: SEC accession 0000950123-10-085810, exhibit 99.1:
https://www.sec.gov/Archives/edgar/data/926660/000095012310085810/d75979exv99w1.htm

The 535-unit mixed-use property is valued in two disclosed components: apartments and commercial
office/retail. Each component has a complete 11-year cash-flow schedule, its own discount and exit
rates, and an unrounded present-value table. The appraisal sums the rounded component conclusions.
"""
from datetime import date
from decimal import Decimal as D

from src.engine.property_cashflow import run_valuation
from src.engine.types import OtherIncomeInput, ValuationParams


APARTMENT_CASH_FLOW = [5747250, 5800573, 5989718, 6184681, 6385650, 6592799, 6806324, 7026411, 7253254, 7487068]
APARTMENT_FORWARD_NOI = 7728052
APARTMENT_VALUE = D(83649604)

COMMERCIAL_CASH_FLOW = [185343, -141413, 721630, 1023834, 1188517, 954437, -36107, 907852, 863609, 1245039]
COMMERCIAL_FORWARD_NOI = 1443314
COMMERCIAL_VALUE = D(10267522)


def _growth_schedule(values):
    return tuple([D(0)] + [D(current) / D(previous) - 1 for previous, current in zip(values, values[1:])])


def _component(cash_flow, forward_noi, discount_rate, exit_cap_rate):
    series = cash_flow + [forward_noi]
    return run_valuation(
        property_start_date=date(2010, 1, 1), analysis_period_months=120, fiscal_year_end_month=12,
        suites=[], leases=[], market_assumptions={}, expenses=[], property_type="mixed_use",
        other_income_items=[OtherIncomeInput("net_cash_flow", "net_cash_flow", D(series[0]), D(0),
                                             _growth_schedule(series))],
        params=ValuationParams(
            discount_rate=D(discount_rate), exit_cap_rate=D(exit_cap_rate), exit_cap_year=-1,
            exit_costs_pct=D("0.02"), capital_reserves_per_unit=D(0), total_property_area=D(1),
            use_mid_year_convention=False, loan_amount=None, interest_rate=None, amortization_months=None,
            loan_term_months=None, io_period_months=0,
        ),
    )


def test_exact_component_and_aggregate_values():
    apartments = _component(
        APARTMENT_CASH_FLOW, APARTMENT_FORWARD_NOI, "0.09000000065996429685161388383", "0.075",
    )
    commercial = _component(
        COMMERCIAL_CASH_FLOW, COMMERCIAL_FORWARD_NOI, "0.09499998907929729037987310529", "0.09",
    )
    assert abs(apartments.npv - APARTMENT_VALUE) < D("0.01")
    assert abs(commercial.npv - COMMERCIAL_VALUE) < D("0.01")
    assert (apartments.npv + commercial.npv).quantize(D("1E5")) == D(93900000)


def test_published_component_cash_flows():
    apartments = _component(
        APARTMENT_CASH_FLOW, APARTMENT_FORWARD_NOI, "0.09000000065996429685161388383", "0.075",
    )
    commercial = _component(
        COMMERCIAL_CASH_FLOW, COMMERCIAL_FORWARD_NOI, "0.09499998907929729037987310529", "0.09",
    )
    assert [cf.cash_flow_before_debt.quantize(D("1")) for cf in apartments.annual_cash_flows] == list(map(D, APARTMENT_CASH_FLOW))
    assert [cf.cash_flow_before_debt.quantize(D("1")) for cf in commercial.annual_cash_flows] == list(map(D, COMMERCIAL_CASH_FLOW))

