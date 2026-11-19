"""Memo expense lines: recoverable from tenants but not a cash operating expense."""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.schemas.expense import PropertyExpenseCreate
from tests.unit.test_growth_schedules import _expense, _flat_lease, _run

D = Decimal


def _memo(**overrides):
    base = dict(expense_id="M1", category="amortized_capital", base_amount=D("20000"), is_memo=True)
    base.update(overrides)
    return _expense(**base)


def test_default_is_not_memo():
    assert _expense().is_memo is False


def test_memo_line_is_not_an_operating_expense():
    base = _run(_flat_lease(), [_expense()]).annual_cash_flows[0]
    memo = _run(_flat_lease(), [_expense(), _memo(is_recoverable=False)]).annual_cash_flows[0]
    assert memo.operating_expenses == base.operating_expenses
    assert "amortized_capital" not in memo.expense_detail
    assert memo.net_operating_income == base.net_operating_income


def test_memo_line_recovered_under_nnn():
    lease = _flat_lease(recovery_type="nnn")
    base = _run(lease, [_expense(is_recoverable=True)]).annual_cash_flows[0]
    memo = _run(lease, [_expense(is_recoverable=True), _memo(is_recoverable=True)]).annual_cash_flows[0]
    # The single tenant leases the whole building: recovers the full $20,000
    assert (memo.expense_recoveries - base.expense_recoveries).quantize(D("0.01")) == D("20000")
    assert memo.operating_expenses == base.operating_expenses
    assert memo.net_operating_income > base.net_operating_income


def test_memo_line_not_recoverable_has_no_effect():
    lease = _flat_lease(recovery_type="nnn")
    base = _run(lease, [_expense(is_recoverable=True)]).annual_cash_flows
    memo = _run(lease, [_expense(is_recoverable=True), _memo(is_recoverable=False)]).annual_cash_flows
    assert [cf.net_operating_income for cf in memo] == [cf.net_operating_income for cf in base]
    assert [cf.expense_recoveries for cf in memo] == [cf.expense_recoveries for cf in base]


def test_memo_line_not_in_management_fee_base():
    """The % of EGI fee is charged on cash EGI: the memo amount itself adds nothing to it, only
    what tenants pay toward it (cash revenue) does."""
    fee = _expense(expense_id="F1", category="management_fee", base_amount=D(0),
                   is_pct_of_egi=True, pct_of_egi=D("0.04"))
    lease = _flat_lease()  # gross lease: the memo line is not recovered
    base = _run(lease, [_expense(), fee]).annual_cash_flows[0]
    memo = _run(lease, [_expense(), fee, _memo(is_recoverable=True)]).annual_cash_flows[0]
    assert memo.effective_gross_income == base.effective_gross_income
    assert memo.expense_detail["management_fee"] == base.expense_detail["management_fee"]
    assert memo.operating_expenses == base.operating_expenses


def test_memo_cannot_be_a_pct_of_egi_line():
    with pytest.raises(ValidationError):
        PropertyExpenseCreate(category="management_fee", base_year_amount=D(0), is_pct_of_egi=True,
                              pct_of_egi=D("0.04"), is_memo=True)
