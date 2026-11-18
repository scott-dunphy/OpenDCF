"""Growth caps on base-year-stop and modified gross categories, and a management fee in a growth cap
whose cap start year is before the analysis (docs/recovery-structure-stop-plan.md).

A growth cap limits the tenant's share of the group's expenses to their cap-start-year level grown
at the cap rate; a stop is then taken off the capped amount. One 10,000 SF tenant (100% share).
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.engine.types import ExpenseRecoveryOverride
from tests.unit.test_growth_schedules import _expense, _flat_lease
from tests.unit.test_leasing_costs_and_loss_base import _run

D = Decimal


def _expenses():
    # $80,000 in Year 1, growing 5%
    return [_expense(expense_id="C", category="cam", base_amount=D(50000), growth_rate=D("0.05"), is_recoverable=True),
            _expense(expense_id="I", category="insurance", base_amount=D(30000), growth_rate=D("0.05"),
                     is_recoverable=True)]


def _lease(recovery_type, growth=D("0.02"), categories=("cam", "insurance"), **lease):
    overrides = tuple(ExpenseRecoveryOverride(cat, recovery_type, None, None, None, None, cap_group="ctrl",
                                              cap_growth_pct=growth) for cat in categories)
    return _flat_lease(recovery_type=recovery_type, recovery_overrides=overrides, **lease)


def _recoveries(lease, expenses=None):
    return [cf.expense_recoveries for cf in _run(lease, expenses=expenses or _expenses()).annual_cash_flows]


def test_base_year_stop_group_recovers_the_capped_increase():
    capped = _recoveries(_lease("base_year_stop", base_year=2025))
    uncapped = _recoveries(_lease("base_year_stop", growth=None, base_year=2025))
    assert capped[0] == pytest.approx(D(0))
    assert capped[1] == pytest.approx(D(80000) * D("1.02") - D(80000))       # 1,600, not 0
    assert capped[2] == pytest.approx(D(80000) * D("1.02") ** 2 - D(80000))  # 3,232
    assert uncapped[1] == pytest.approx(D(4000)) and capped[1] < uncapped[1]


def test_modified_gross_group_caps_the_expense_before_the_stop():
    # Cap-group items set no stop of their own, so the categories stay pooled against the lease's
    # $2/SF stop: Year 1 recovers (8 - 2) $/SF on 10,000 SF
    capped = _recoveries(_lease("modified_gross", expense_stop_per_sf=D(2)))
    assert capped[0] == pytest.approx(D(60000))
    assert capped[1] == pytest.approx(D(80000) * D("1.02") - D(20000))


def test_management_fee_counts_in_a_cap_start_year_before_the_analysis():
    # The lease (and its cap) started in 2023. A cap far above expense growth must not bind,
    # which it did when the fee counted as $0 in the cap start year.
    expenses = [*_expenses(), _expense(expense_id="M", category="management_fee", base_amount=D(0),
                                       growth_rate=D(0), is_recoverable=True, is_pct_of_egi=True,
                                       pct_of_egi=D("0.03"))]
    kw = dict(start_date=date(2023, 1, 1), categories=("cam", "insurance", "management_fee"))
    loose = _recoveries(_lease("nnn", growth=D("0.10"), **kw), expenses)
    uncapped = _recoveries(_lease("nnn", growth=None, **kw), expenses)
    assert loose == pytest.approx(uncapped)
