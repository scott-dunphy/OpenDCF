"""The optional calculation modes added together (memo expenses, recoverable %, credit loss on tenant
revenue, prorated rent steps, rounded market lease starts, terminal-value adjustments) work in one run."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from src.engine.property_cashflow import run_valuation
from src.engine.types import ExpenseRecoveryOverride, FreeRentPeriodInput, RentStepInput, SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_growth_schedules import _expense, _flat_lease

D = Decimal
SUITE = SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office")


def _value(lease, expenses, market, params, other_income=()):
    return run_valuation(
        property_start_date=date(2025, 1, 1), analysis_period_months=60, fiscal_year_end_month=12,
        suites=[SUITE], leases=[lease], market_assumptions={"office": market}, expenses=list(expenses),
        params=params, other_income_items=list(other_income))


def test_memo_line_at_a_recoverable_weight():
    # A $20,000 memo amortization line recovered NNN at 60%: recoveries rise $12,000, expenses do not
    market = _make_market(gen_vacancy=D(0), credit_loss=D(0))
    taxes = _expense(is_recoverable=True, growth_rate=D(0))
    amortization = _expense(expense_id="AM", category="capital_amortization", base_amount=D(20000),
                            growth_rate=D(0), is_recoverable=True, is_memo=True)
    weight = ExpenseRecoveryOverride("capital_amortization", "nnn", None, None, None, None, recoverable_pct=D("0.6"))
    lease = _flat_lease(recovery_type="nnn", recovery_overrides=(weight,))
    without = _value(lease, [taxes], market, _make_params()).annual_cash_flows[0]
    with_memo = _value(lease, [taxes, amortization], market, _make_params()).annual_cash_flows[0]
    assert round(with_memo.expense_recoveries - without.expense_recoveries, 2) == D(12000)
    assert with_memo.operating_expenses == without.operating_expenses


def test_every_option_on_at_once():
    lease = _flat_lease(
        recovery_type="nnn", escalation_type="fixed_step", prorate_rent_steps=True,
        end_date=date(2027, 4, 14),                       # mid-month expiry: market lease after downtime
        rent_steps=(RentStepInput(date(2026, 1, 15), D(33)),),
        free_rent_periods=(FreeRentPeriodInput(date(2025, 1, 1), date(2025, 2, 28), True, False),),
        recovery_overrides=(ExpenseRecoveryOverride("real_estate_taxes", "nnn", None, None, None, None,
                                                    recoverable_pct=D("0.8")),),
    )
    expenses = [_expense(is_recoverable=True),
                _expense(expense_id="AM", category="capital_amortization", base_amount=D(20000),
                         growth_rate=D(0), is_recoverable=True, is_memo=True)]
    base_params = _make_params(exit_costs=D("0.02"))
    all_on = replace(base_params, credit_loss_on_tenant_revenue=True, exit_add_back_free_rent=True,
                     exit_deduct_forward_free_rent=True, exit_deduct_forward_leasing_costs=True,
                     exit_costs_on_adjusted_gross=True)
    market = _make_market()
    off = _value(lease, expenses, market, base_params)
    on = _value(replace(lease), expenses, replace(market, round_start_to_month=True), all_on)
    assert off.npv > 0 and on.npv > 0
    assert on.npv != off.npv
