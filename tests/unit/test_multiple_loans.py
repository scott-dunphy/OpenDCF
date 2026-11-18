"""Debt service, balances and fees add up across the first loan and additional loans."""
from decimal import Decimal as D

from src.engine.dcf import build_monthly_debt_detail
from src.engine.returns import compute_investment_returns
from src.engine.types import LoanParams, ValuationParams


def _params(**kw) -> ValuationParams:
    base = dict(
        discount_rate=D("0.08"), exit_cap_rate=D("0.07"), exit_cap_year=-1, exit_costs_pct=D(0),
        capital_reserves_per_unit=D(0), total_property_area=D(1000), use_mid_year_convention=False,
        loan_amount=None, interest_rate=None, amortization_months=None, loan_term_months=None,
        io_period_months=0,
    )
    base.update(kw)
    return ValuationParams(**base)


FIRST = dict(loan_amount=D(6_000_000), interest_rate=D("0.06"), amortization_months=360,
             loan_term_months=None, io_period_months=12)
MEZZ = LoanParams(D(1_000_000), D("0.10"), loan_term_months=60, io_period_months=60, loan_fees_pct=D("0.01"))


def test_service_balance_and_balloon_are_the_sum_of_each_loan():
    both = build_monthly_debt_detail(_params(**FIRST, additional_loans=(MEZZ,)), 120)
    first = build_monthly_debt_detail(_params(**FIRST), 120)
    mezz = build_monthly_debt_detail(_params(
        loan_amount=MEZZ.loan_amount, interest_rate=MEZZ.interest_rate, amortization_months=None,
        loan_term_months=60, io_period_months=60), 120)
    for k in range(3):
        assert both[k] == [a + b for a, b in zip(first[k], mezz[k])]
    # Mezzanine: interest only, repaid at month 60
    assert mezz[0][0] == D(1_000_000) * D("0.10") / 12
    assert mezz[2][59] == D(1_000_000) and mezz[1][59] == 0 and mezz[0][60] == 0


def test_additional_loan_without_first_loan():
    service, balances, _ = build_monthly_debt_detail(_params(additional_loans=(MEZZ,)), 12)
    assert balances[0] == D(1_000_000) and service[0] > 0


def test_returns_use_total_loan_and_fees():
    from src.engine.types import AnnualPropertyCashFlow  # noqa: F401  (shape only)
    params = _params(**FIRST, loan_fees_pct=D("0.005"), additional_loans=(MEZZ,), purchase_price=D(10_000_000))
    service, balances, balloons = build_monthly_debt_detail(params, 12)

    class CF:
        def __init__(self):
            from datetime import date
            self.period_start, self.period_end = date(2026, 1, 1), date(2026, 12, 31)
            self.net_operating_income = D(800_000)
            self.cash_flow_before_debt = D(800_000)
            self.debt_service = -sum(service)
            self.levered_cash_flow = D(800_000) - sum(service)

    r = compute_investment_returns([CF()], D(11_000_000), D(10_500_000), params, [balances[-1]], [balloons[-1]])
    assert r.loan_amount == D(7_000_000)
    assert r.loan_fees == D(30_000) + D(10_000)
    assert r.equity_invested == D(10_000_000) - D(7_000_000) + D(40_000)
    assert r.loan_payoff_at_sale == balances[-1]
    assert r.loan_to_value == D("0.7")
