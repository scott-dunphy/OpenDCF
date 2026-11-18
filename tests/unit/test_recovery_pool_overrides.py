"""Which per-category overrides leave a lease's pooled stop, and modified gross with a typed share.

Only an override that sets its own stop or a different recovery type is measured alone; an item
that only adds an admin fee, a cap or a floor stays in the pool and applies its terms to its
allocated share. A typed Pro Rata Share applies to modified gross like any other type.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.engine.date_utils import build_analysis_period
from src.engine.expense_engine import attach_expense_recoveries
from src.engine.property_cashflow import run_valuation
from src.engine.types import ExpenseRecoveryOverride, SuiteInput
from tests.integration.test_engine_parity import _make_params
from tests.unit.test_expense_engine import make_expense, make_lease, make_slice
from tests.unit.test_growth_schedules import _expense, _flat_lease
from tests.unit.test_leasing_costs_and_loss_base import _rollover_market


def item(category: str, recovery_type: str, **kw) -> ExpenseRecoveryOverride:
    terms = dict(base_year_stop_amount=None, cap_per_sf_annual=None, floor_per_sf_annual=None, admin_fee_pct=None)
    terms.update(kw)
    return ExpenseRecoveryOverride(expense_category=category, recovery_type=recovery_type, **terms)


def annual(lease, expenses, months=24, year=1, audit=None) -> tuple[Decimal, dict[str, Decimal]]:
    """Year `year` recovery (one month x 12) and its split by category."""
    analysis = build_analysis_period(date(2025, 1, 1), months, 12)
    s = make_slice(month_index=12 * (year - 1), period_start=date(2024 + year, 1, 1))
    attach_expense_recoveries([s], lease, expenses, analysis, Decimal("10000"), [Decimal(1)] * months,
                              recovery_audit=audit)
    return s.expense_recovery * 12, {k: v * 12 for k, v in s.expense_recovery_detail.items()}


MG_EXPENSES = [make_expense(category="taxes", base_amount=50_000), make_expense(category="cam", base_amount=60_000)]


class TestModifiedGrossPool:
    """5,000 of 10,000 SF, lease stop $8/SF; taxes $5/SF, CAM $6/SF (pooled $11/SF)."""

    def test_no_items_pool_both_lines(self):
        total, _ = annual(make_lease(recovery_type="modified_gross", expense_stop_per_sf=8.0), MG_EXPENSES)
        assert total == pytest.approx(Decimal(15_000))

    def test_line_with_its_own_stop_leaves_the_pool(self):
        # Taxes ($5) vs its $4 stop: 5,000; CAM alone ($6) is under the $8 lease stop: 0
        lease = make_lease(recovery_type="modified_gross", expense_stop_per_sf=8.0,
                           overrides=(item("taxes", "modified_gross", expense_stop_per_sf=Decimal(4)),))
        total, by_cat = annual(lease, MG_EXPENSES)
        assert by_cat["taxes"] == pytest.approx(Decimal(5_000))
        assert by_cat["cam"] == pytest.approx(Decimal(0))
        assert total == pytest.approx(Decimal(5_000))

    def test_audit_reports_the_pool_each_line_is_tested_against(self):
        # Taxes measured alone (no pool $/SF); CAM pooled on its own at $6/SF
        lease = make_lease(recovery_type="modified_gross", expense_stop_per_sf=8.0,
                           overrides=(item("taxes", "modified_gross", expense_stop_per_sf=Decimal(4)),))
        audit = []
        annual(lease, MG_EXPENSES, audit=audit)
        by_cat = {row.expense_category: row.modified_gross_pool_per_sf for row in audit}
        assert by_cat["taxes"] is None
        assert by_cat["cam"] == pytest.approx(Decimal(6))
        audit = []
        annual(make_lease(recovery_type="modified_gross", expense_stop_per_sf=8.0), MG_EXPENSES, audit=audit)
        assert [row.modified_gross_pool_per_sf for row in audit] == pytest.approx([Decimal(11)] * 2)

    def test_high_own_stop_does_not_push_the_other_line_over_the_lease_stop(self):
        lease = make_lease(recovery_type="modified_gross", expense_stop_per_sf=8.0,
                           overrides=(item("cam", "modified_gross", expense_stop_per_sf=Decimal(10)),))
        total, _ = annual(lease, MG_EXPENSES)
        assert total == pytest.approx(Decimal(0))

    def test_legacy_floor_stop_leaves_the_pool(self):
        # Older models entered a modified gross item's stop as its floor
        lease = make_lease(recovery_type="modified_gross", expense_stop_per_sf=8.0,
                           overrides=(item("taxes", "modified_gross", floor_per_sf_annual=Decimal(4)),))
        total, _ = annual(lease, MG_EXPENSES)
        assert total == pytest.approx(Decimal(5_000))

    def test_admin_fee_only_item_stays_in_the_pool(self):
        # Pooled excess $3/SF x 5,000 = 15,000: taxes 5/11 of it plus a 10% fee, CAM 6/11
        lease = make_lease(recovery_type="modified_gross", expense_stop_per_sf=8.0,
                           overrides=(item("taxes", "modified_gross", admin_fee_pct=Decimal("0.10")),))
        total, by_cat = annual(lease, MG_EXPENSES)
        assert by_cat["taxes"] == pytest.approx(Decimal(15_000) * 5 / 11 * Decimal("1.1"))
        assert by_cat["cam"] == pytest.approx(Decimal(15_000) * 6 / 11)

    def test_cap_only_item_stays_in_the_pool_and_caps_its_share(self):
        # CAM's allocated share (8,181.82) is capped at $1/SF x 5,000
        lease = make_lease(recovery_type="modified_gross", expense_stop_per_sf=8.0,
                           overrides=(item("cam", "modified_gross", cap_per_sf_annual=Decimal(1)),))
        _, by_cat = annual(lease, MG_EXPENSES)
        assert by_cat["taxes"] == pytest.approx(Decimal(15_000) * 5 / 11)
        assert by_cat["cam"] == pytest.approx(Decimal(5_000))

    def test_item_of_another_type_leaves_the_pool(self):
        # Taxes billed NNN: 50,000 x 50%; CAM alone ($6) is under the $8 lease stop: 0
        lease = make_lease(recovery_type="modified_gross", expense_stop_per_sf=8.0,
                           overrides=(item("taxes", "nnn"),))
        _, by_cat = annual(lease, MG_EXPENSES)
        assert by_cat["taxes"] == pytest.approx(Decimal(25_000))
        assert by_cat["cam"] == pytest.approx(Decimal(0))


class TestModifiedGrossTypedShare:
    """A typed Pro Rata Share applies to the excess over a modified gross stop."""

    def test_typed_share_with_no_stop(self):
        lease = make_lease(recovery_type="modified_gross", pro_rata=0.6)
        total, _ = annual(lease, [make_expense(category="taxes", base_amount=100_000)])
        assert total == pytest.approx(Decimal(60_000))

    def test_typed_share_applies_to_the_excess_over_the_stop(self):
        # ($10 - $4) x 10,000 SF x 60%
        audit = []
        lease = make_lease(recovery_type="modified_gross", expense_stop_per_sf=4.0, pro_rata=0.6)
        total, _ = annual(lease, [make_expense(category="taxes", base_amount=100_000)], audit=audit)
        assert total == pytest.approx(Decimal(36_000))
        assert audit[0].pro_rata_share_pct == Decimal("0.6")

    def test_typed_share_on_the_pooled_excess(self):
        # Pooled $11 - $8 = $3 x 10,000 SF x 60%
        lease = make_lease(recovery_type="modified_gross", expense_stop_per_sf=8.0, pro_rata=0.6)
        total, _ = annual(lease, MG_EXPENSES)
        assert total == pytest.approx(Decimal(18_000))

    def test_typed_share_on_a_line_with_its_own_stop(self):
        lease = make_lease(recovery_type="modified_gross", expense_stop_per_sf=8.0, pro_rata=0.6,
                           overrides=(item("taxes", "modified_gross", expense_stop_per_sf=Decimal(4)),))
        _, by_cat = annual(lease, MG_EXPENSES)
        assert by_cat["taxes"] == pytest.approx(Decimal(6_000))


BYS_EXPENSES = [make_expense(category="taxes", base_amount=100_000, growth_rate=-0.05),
                make_expense(category="cam", base_amount=100_000, growth_rate=0.05)]


class TestBaseYearPoolItems:
    """Base year 2025: Year 3 taxes 90,250, CAM 110,250, pooled excess 500 x 50% = 250."""

    def run(self, *overrides):
        lease = make_lease(recovery_type="base_year_stop", base_year=2025, overrides=overrides,
                           end=date(2027, 12, 31))
        return annual(lease, BYS_EXPENSES, months=36, year=3)

    def test_item_that_changes_no_term_keeps_the_pool(self):
        total, _ = self.run(item("cam", "base_year_stop", admin_fee_pct=Decimal(0)))
        assert total == pytest.approx(Decimal(250))

    def test_admin_fee_item_applies_its_fee_to_its_pooled_share(self):
        _, by_cat = self.run(item("cam", "base_year_stop", admin_fee_pct=Decimal("0.15")))
        cam_share = Decimal(250) * Decimal(110_250) / Decimal(200_500)
        assert by_cat["cam"] == pytest.approx(cam_share * Decimal("1.15"))
        assert by_cat["taxes"] == pytest.approx(Decimal(250) - cam_share)

    def test_cap_item_caps_its_pooled_share(self):
        _, by_cat = self.run(item("cam", "base_year_stop", cap_per_sf_annual=Decimal("0.01")))
        assert by_cat["cam"] == pytest.approx(Decimal(50))
        # Taxes keep their part of the pooled excess (alone they fell below their base: 0)
        assert by_cat["taxes"] == pytest.approx(Decimal(250) * Decimal(90_250) / Decimal(200_500))

    def test_other_types_stop_field_does_not_take_the_line_out(self):
        # A modified gross stop left on a base-year item is not used, so the line stays pooled
        total, _ = self.run(item("cam", "base_year_stop", expense_stop_per_sf=Decimal(1)))
        assert total == pytest.approx(Decimal(250))

    def test_floor_item_floors_its_pooled_share(self):
        _, by_cat = self.run(item("cam", "base_year_stop", floor_per_sf_annual=Decimal("1")))
        assert by_cat["cam"] == pytest.approx(Decimal(5_000))

    def test_item_with_its_own_stop_leaves_the_pool(self):
        # CAM alone over a $105,000 stop: 5,250 x 50%; taxes alone fell below its base: 0
        total, by_cat = self.run(item("cam", "base_year_stop", base_year_stop_amount=Decimal(105_000)))
        assert by_cat["cam"] == pytest.approx(Decimal(2_625))
        assert by_cat["taxes"] == pytest.approx(Decimal(0))


class TestMarketLeases:
    """Market leases carry every structure item as an override; a blank picker keeps the expiring lease's share."""

    def run(self, market, expenses, months=36, **lease_kw):
        suite = SuiteInput(suite_id="S1", suite_name="1", area=Decimal(5000), space_type="office")
        lease = _flat_lease(**{"area": Decimal(5000), "end_date": date(2025, 12, 31), "recovery_type": "nnn", **lease_kw})
        r = run_valuation(property_start_date=date(2025, 1, 1), analysis_period_months=months,
                          fiscal_year_end_month=12, suites=[suite], leases=[lease],
                          market_assumptions={"office": _rollover_market(**market)}, expenses=expenses,
                          params=_make_params())
        return [cf.expense_recoveries for cf in r.annual_cash_flows]

    @pytest.mark.parametrize("stop, year2", [(Decimal(0), Decimal(60_000)), (Decimal(4), Decimal(36_000))])
    def test_modified_gross_renewal_keeps_the_typed_share(self, stop, year2):
        # Taxes $100,000 = $10/SF of 10,000 SF; the expiring lease's share is 60% (its area is 50%)
        taxes = _expense(growth_rate=Decimal(0), is_recoverable=True)
        # Blank profile Recovery Structure ("same as expiring lease"): the market lease keeps the
        # expiring lease's type, stop and typed share
        rec = self.run(dict(recovery_type=None), [taxes], recovery_type="modified_gross",
                       expense_stop_per_sf=stop, pro_rata_share=Decimal("0.6"))
        assert rec[1] == pytest.approx(year2)

    def test_base_year_item_with_only_an_admin_fee_keeps_the_pool(self):
        expenses = [_expense(category="taxes", base_amount=Decimal(100_000), growth_rate=Decimal("-0.05"),
                             is_recoverable=True),
                    _expense(category="cam", base_amount=Decimal(100_000), growth_rate=Decimal("0.05"),
                             is_recoverable=True)]
        market = dict(recovery_type="base_year_stop", expense_stop_per_sf=None)
        plain = self.run(market, expenses, months=48)
        with_item = self.run({**market, "recovery_overrides": (item("cam", "base_year_stop", admin_fee_pct=Decimal(0)),)},
                             expenses, months=48)
        assert with_item == pytest.approx(plain)
        assert plain[2] > 0
