"""Recoverable % on a per-category recovery override: weights the eligible expense (after gross-up
and pool deductions) before the stop, pro rata share and cap/floor."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.engine.expense_engine import attach_expense_recoveries
from src.engine.types import ExpenseRecoveryOverride
from tests.unit.test_expense_engine import make_analysis, make_expense, make_lease, make_slice

D = Decimal


def _override(category: str, recovery_type: str = "nnn", **kw) -> ExpenseRecoveryOverride:
    return replace(ExpenseRecoveryOverride(expense_category=category, recovery_type=recovery_type,
                                           base_year_stop_amount=None, cap_per_sf_annual=None,
                                           floor_per_sf_annual=None, admin_fee_pct=None), **kw)


def _monthly(lease, expenses, period_start=date(2025, 1, 1)):
    analysis = make_analysis()
    s = make_slice(period_start=period_start)
    attach_expense_recoveries([s], lease, expenses, analysis, D(10000), [D(1)] * analysis.num_months)
    return s


class TestRecoverablePct:
    def test_default_is_full_recovery(self):
        assert _override("cam").recoverable_pct == D(1)
        s = _monthly(make_lease(overrides=(_override("cam"),)), [make_expense("cam")])
        assert s.expense_recovery == pytest.approx(D(5000))

    def test_nnn_recovers_weighted_share(self):
        # $120K x 60% x 50% share = $36K/yr
        lease = make_lease(overrides=(_override("cam", recoverable_pct=D("0.6")),))
        s = _monthly(lease, [make_expense("cam")])
        assert s.expense_recovery == pytest.approx(D(3000))

    def test_weight_applies_before_the_cap(self):
        # Weighted $72K x 50% = $36K is under a $8/SF x 5,000 SF = $40K cap
        lease = make_lease(overrides=(_override("cam", recoverable_pct=D("0.6"), cap_per_sf_annual=D(8)),))
        assert _monthly(lease, [make_expense("cam")]).expense_recovery == pytest.approx(D(3000))

    def test_base_year_stop_compared_against_weighted_expense(self):
        # ($120K x 60% - $60K stop) x 50% = $6K/yr
        lease = make_lease(recovery_type="base_year_stop", overrides=(_override(
            "cam", "base_year_stop", base_year_stop_amount=D(60000), recoverable_pct=D("0.6")),))
        assert _monthly(lease, [make_expense("cam")]).expense_recovery == pytest.approx(D(500))

    def test_base_year_derived_stop_is_weighted_too(self):
        # Base year 2025 $120K, Year 2 $132K, both at 60%: (79.2K - 72K) x 50% = $3.6K/yr
        lease = make_lease(recovery_type="base_year_stop", base_year=2025,
                           overrides=(_override("cam", "base_year_stop", recoverable_pct=D("0.6")),))
        s = _monthly(lease, [make_expense("cam", growth_rate=0.10)], period_start=date(2026, 1, 1))
        assert s.expense_recovery == pytest.approx(D(300))

    def test_pooled_base_year_stop_takes_the_weighted_line(self):
        # Pool: CAM $120K x 50% + taxes $80K = $140K over a $100K lease stop, x 50% = $20K/yr
        lease = make_lease(recovery_type="base_year_stop", base_year_stop=100_000,
                           overrides=(_override("cam", "base_year_stop", recoverable_pct=D("0.5")),))
        s = _monthly(lease, [make_expense("cam"), make_expense("real_estate_taxes", base_amount=80_000)])
        assert s.expense_recovery == pytest.approx(D(20000) / 12)

    def test_modified_gross_stop_against_weighted_per_sf(self):
        # $12/SF x 50% = $6/SF, $4 stop: $2/SF x 5,000 SF = $10K/yr
        lease = make_lease(recovery_type="modified_gross", expense_stop_per_sf=4,
                           overrides=(_override("cam", "modified_gross", recoverable_pct=D("0.5")),))
        assert _monthly(lease, [make_expense("cam")]).expense_recovery == pytest.approx(D(10000) / 12)

    def test_net_fee_share_is_weighted(self):
        lease = make_lease(overrides=(_override("management_fee", recoverable_pct=D("0.6")),))
        s = _monthly(lease, [make_expense("management_fee", base_amount=0, is_pct_egi=True, pct_egi=0.03)])
        assert s.mgmt_fee_shares["management_fee"].share == pytest.approx(D("0.3"))
