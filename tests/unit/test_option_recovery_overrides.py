"""An exercised renewal option continues the lease's per-category recovery terms."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.engine.date_utils import build_analysis_period
from src.engine.renewal_engine import generate_option_lease
from src.engine.types import ExpenseRecoveryOverride, SuiteInput
from tests.integration.test_engine_parity import _make_market
from tests.unit.test_growth_schedules import _expense, _flat_lease, _run

D = Decimal
SUITE = SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office")


def _override(category: str, **kw) -> ExpenseRecoveryOverride:
    return replace(ExpenseRecoveryOverride(expense_category=category, recovery_type="nnn",
                                           base_year_stop_amount=None, cap_per_sf_annual=None,
                                           floor_per_sf_annual=None, admin_fee_pct=None), **kw)


def _option_source(overrides, **kw):
    # Expires end of Year 2 (2026); a 36-month option runs through the end of the analysis
    return _flat_lease(end_date=date(2026, 12, 31), recovery_type="nnn", recovery_overrides=overrides,
                       upon_expiration="option", option_rent_per_unit=D("30"), option_term_months=36, **kw)


def _option_lease(source):
    analysis = build_analysis_period(date(2025, 1, 1), 60, 12)
    _, leases, _ = generate_option_lease(SUITE, source, date(2027, 1, 1), analysis, _make_market())
    return leases[0]


def _expenses():
    return [_expense(expense_id="C", category="cam", base_amount=D(50000), growth_rate=D("0.05"),
                     is_recoverable=True),
            _expense(expense_id="I", category="insurance", base_amount=D(30000), growth_rate=D("0.05"),
                     is_recoverable=True)]


class TestOptionCarriesOverrides:
    def test_admin_fee_and_cap_carried(self):
        overrides = (_override("cam", admin_fee_pct=D("0.15"), cap_group="cam", cap_growth_pct=D("0.05")),
                     _override("insurance", cap_per_sf_annual=D("4")))
        option = _option_lease(_option_source(overrides))
        assert option.recovery_overrides == overrides
        assert option.recovery_cap_start == date(2025, 1, 1)

    def test_admin_fee_raises_option_recoveries(self):
        plain = _run(_option_source(()), expenses=_expenses()).annual_cash_flows
        fee = _run(_option_source((_override("cam", admin_fee_pct=D("0.15")),)),
                   expenses=_expenses()).annual_cash_flows
        # Option years: CAM recovered with a 15% admin fee
        cam_y3 = D(50000) * D("1.05") ** 2
        assert fee[2].expense_recoveries - plain[2].expense_recoveries == pytest.approx(cam_y3 * D("0.15"))

    def test_base_year_override_resets_to_option_start(self):
        overrides = (_override("cam", recovery_type="base_year_stop", base_year_stop_amount=D(40000)),
                     _override("insurance", recovery_type="modified_gross", base_year_stop_amount=D(20000)),
                     _override("taxes", recovery_type="modified_gross", expense_stop_per_sf=D("3")))
        option = _option_lease(_option_source(overrides))
        cam, insurance, taxes = option.recovery_overrides
        # The fixed stops would beat the reset: the stop comes from the option's base year
        assert (cam.recovery_type, cam.base_year_stop_amount) == ("base_year_stop", None)
        assert (insurance.recovery_type, insurance.base_year_stop_amount) == ("base_year_stop", None)
        # A modified gross stop that is set is kept
        assert taxes == overrides[2]
        assert option.base_year == 2027


class TestOptionCapGrowth:
    def _overrides(self):
        return tuple(_override(cat, cap_group="cam_ins", cap_growth_pct=D("0.02")) for cat in ("cam", "insurance"))

    def test_growth_cap_continues_from_original_lease_start(self):
        # Expenses grow 5%, recoveries at most 2% a year from 2025: the option years match one long lease
        option = _run(_option_source(self._overrides()), expenses=_expenses()).annual_cash_flows
        long = _run(_flat_lease(end_date=date(2029, 12, 31), recovery_type="nnn",
                                recovery_overrides=self._overrides()), expenses=_expenses()).annual_cash_flows
        for year in (2, 3, 4):
            assert option[year].expense_recoveries == pytest.approx(D(80000) * D("1.02") ** year)
            assert option[year].expense_recoveries == pytest.approx(long[year].expense_recoveries)
