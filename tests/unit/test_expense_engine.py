"""Unit tests for expense recovery calculations."""
from datetime import date
from decimal import Decimal

import pytest

from src.engine.date_utils import build_analysis_period, end_of_month
from src.engine.expense_engine import attach_expense_recoveries
from src.engine.types import (
    ExpenseInput,
    ExpenseRecoveryOverride,
    FreeRentPeriodInput,
    LeaseInput,
    MonthlySlice,
)


def make_analysis():
    return build_analysis_period(date(2025, 1, 1), 24, 12)


def make_expense(
    category: str = "real_estate_taxes",
    base_amount: float = 120_000,
    growth_rate: float = 0.0,
    is_recoverable: bool = True,
    is_gross_up: bool = False,
    gross_up_pct: float | None = None,
    is_pct_egi: bool = False,
    pct_egi: float | None = None,
) -> ExpenseInput:
    return ExpenseInput(
        expense_id="e1",
        category=category,
        base_amount=Decimal(str(base_amount)),
        growth_rate=Decimal(str(growth_rate)),
        is_recoverable=is_recoverable,
        is_gross_up_eligible=is_gross_up,
        gross_up_vacancy_pct=Decimal(str(gross_up_pct)) if gross_up_pct is not None else None,
        is_pct_of_egi=is_pct_egi,
        pct_of_egi=Decimal(str(pct_egi)) if pct_egi is not None else None,
    )


def make_lease(
    area: float = 5_000,
    total_area: float = 10_000,
    recovery_type: str = "nnn",
    pro_rata: float | None = None,
    base_year: int | None = None,
    base_year_stop: float | None = None,
    expense_stop_per_sf: float | None = None,
    overrides: tuple = (),
    start: date = date(2025, 1, 1),
    end: date = date(2026, 12, 31),
    free_rent_periods: tuple = (),
) -> LeaseInput:
    return LeaseInput(
        lease_id="l1",
        suite_id="s1",
        tenant_name="Tenant",
        area=Decimal(str(area)),
        start_date=start,
        end_date=end,
        base_rent_per_unit=Decimal("30"),
        rent_payment_frequency="annual",
        escalation_type="flat",
        escalation_pct=None,
        cpi_floor=None,
        cpi_cap=None,
        rent_steps=(),
        free_rent_periods=free_rent_periods,
        recovery_type=recovery_type,
        pro_rata_share=Decimal(str(pro_rata)) if pro_rata is not None else None,
        base_year=base_year,
        base_year_stop_amount=Decimal(str(base_year_stop)) if base_year_stop is not None else None,
        expense_stop_per_sf=Decimal(str(expense_stop_per_sf)) if expense_stop_per_sf is not None else None,
        recovery_overrides=overrides,
        pct_rent_breakpoint=None,
        pct_rent_rate=None,
        renewal_probability_override=None,
    )


def make_slice(
    month_index: int = 0,
    period_start: date = date(2025, 1, 1),
    is_vacant: bool = False,
) -> MonthlySlice:
    return MonthlySlice(
        month_index=month_index,
        period_start=period_start,
        period_end=end_of_month(period_start),
        suite_id="s1",
        lease_id="l1",
        tenant_name="Tenant",
        base_rent=Decimal("12500"),
        free_rent_adjustment=Decimal(0),
        effective_rent=Decimal("12500"),
        expense_recovery=Decimal(0),
        percentage_rent=Decimal(0),
        ti_cost=Decimal(0),
        lc_cost=Decimal(0),
        is_vacant=is_vacant,
        scenario_label="in_place",
        scenario_weight=Decimal(1),
    )


class TestNNNRecovery:
    def test_nnn_pro_rata_from_area(self):
        """NNN: tenant pays area/total_area share.
        Expense=$120K, area=5K, total=10K → 50% → $5K/month."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000)
        lease = make_lease(area=5_000, recovery_type="nnn")
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        assert abs(s.expense_recovery - Decimal("5000")) < Decimal("10")

    def test_nnn_explicit_pro_rata(self):
        """NNN with explicit 60% pro-rata share."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000)
        lease = make_lease(area=5_000, recovery_type="nnn", pro_rata=0.60)
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        expected = Decimal("120000") * Decimal("0.60") / Decimal("12")
        assert abs(s.expense_recovery - expected) < Decimal("10")

    def test_fsg_no_recovery(self):
        """Full service gross: tenant pays nothing."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000)
        lease = make_lease(recovery_type="full_service_gross")
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        assert s.expense_recovery == Decimal(0)

    def test_none_recovery_type_no_recovery(self):
        """Recovery type 'none': no recovery."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000)
        lease = make_lease(recovery_type="none")
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        assert s.expense_recovery == Decimal(0)

    def test_non_recoverable_expense_not_billed(self):
        """Non-recoverable expense: no recovery regardless of lease type."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000, is_recoverable=False)
        lease = make_lease(recovery_type="nnn")
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        assert s.expense_recovery == Decimal(0)

    def test_pct_of_egi_expense_skipped_in_recovery(self):
        """Mgmt fees (is_pct_of_egi=True) handled in waterfall, not here."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000, is_pct_egi=True, pct_egi=0.04)
        lease = make_lease(recovery_type="nnn")
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        assert s.expense_recovery == Decimal(0)

    def test_vacant_slice_skipped(self):
        """Vacant slices get no expense recovery."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000)
        lease = make_lease(recovery_type="nnn")
        s = make_slice(is_vacant=True)
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        assert s.expense_recovery == Decimal(0)

    def test_multiple_expenses_sum(self):
        """Multiple recoverable expenses are summed."""
        analysis = make_analysis()
        expenses = [
            make_expense(base_amount=120_000),  # $5K/mo at 50%
            make_expense(category="insurance", base_amount=24_000),  # $1K/mo at 50%
        ]
        lease = make_lease(area=5_000, recovery_type="nnn")
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, expenses, analysis, Decimal("10000"), occupancy)

        # 50% of (120K + 24K) / 12 = $6K
        assert abs(s.expense_recovery - Decimal("6000")) < Decimal("10")


class TestBaseYearStop:
    def test_above_stop_pays_excess(self):
        """Expense=$120K, stop=$100K, 50% pro-rata → excess=$20K, monthly=50%*20K/12=$833."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000)
        lease = make_lease(recovery_type="base_year_stop", base_year_stop=100_000)
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        expected_monthly = Decimal("10000") / Decimal("12")  # 50% of $20K excess / 12
        assert abs(s.expense_recovery - expected_monthly) < Decimal("5")

    def test_at_stop_no_recovery(self):
        """Expense exactly at stop: no excess, no recovery."""
        analysis = make_analysis()
        expense = make_expense(base_amount=100_000)
        lease = make_lease(recovery_type="base_year_stop", base_year_stop=100_000)
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        assert s.expense_recovery == Decimal(0)

    def test_below_stop_no_recovery(self):
        """Expense below stop: no recovery."""
        analysis = make_analysis()
        expense = make_expense(base_amount=80_000)
        lease = make_lease(recovery_type="base_year_stop", base_year_stop=100_000)
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        assert s.expense_recovery == Decimal(0)

    def test_base_year_derived_stop_used_when_stop_amount_omitted(self):
        """Lease base_year computes stop from the expense growth curve."""
        analysis = build_analysis_period(date(2025, 1, 1), 36, 12)
        expense = make_expense(base_amount=100_000, growth_rate=0.10)
        lease = make_lease(recovery_type="base_year_stop", base_year=2026)
        s = make_slice(month_index=12, period_start=date(2026, 1, 1))
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        # Year 2 expense = 110K; base_year 2026 stop = 110K, so no excess.
        assert s.expense_recovery == Decimal(0)

    def test_explicit_stop_overrides_base_year_derived_stop(self):
        """Lease-level base_year_stop_amount takes priority over derived base_year stop."""
        analysis = build_analysis_period(date(2025, 1, 1), 36, 12)
        expense = make_expense(base_amount=100_000, growth_rate=0.10)
        lease = make_lease(
            recovery_type="base_year_stop",
            base_year=2026,
            base_year_stop=100_000,
        )
        s = make_slice(month_index=12, period_start=date(2026, 1, 1))
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        expected = (Decimal("110000") - Decimal("100000")) * Decimal("0.5") / Decimal("12")
        assert abs(s.expense_recovery - expected) < Decimal("1")

    def test_override_stop_overrides_lease_stop_and_base_year(self):
        """Per-category stop override has highest precedence."""
        analysis = build_analysis_period(date(2025, 1, 1), 36, 12)
        expense = make_expense(base_amount=100_000, growth_rate=0.10)
        override = ExpenseRecoveryOverride(
            expense_category="real_estate_taxes",
            recovery_type="base_year_stop",
            base_year_stop_amount=Decimal("105000"),
            cap_per_sf_annual=None,
            floor_per_sf_annual=None,
            admin_fee_pct=None,
        )
        lease = make_lease(
            recovery_type="base_year_stop",
            base_year=2026,
            base_year_stop=100_000,
            overrides=(override,),
        )
        s = make_slice(month_index=12, period_start=date(2026, 1, 1))
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        expected = (Decimal("110000") - Decimal("105000")) * Decimal("0.5") / Decimal("12")
        assert abs(s.expense_recovery - expected) < Decimal("1")


class TestModifiedGross:
    def test_expense_above_stop_per_sf(self):
        """Modified gross: pay pro-rata of excess expense/SF above stop.
        Expense/SF = $120K / 10K SF = $12/SF. Stop = $10/SF. Excess = $2/SF.
        Tenant area 5K SF: recovery = 5K * $2 / 12 = $833/month."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000)
        lease = make_lease(
            area=5_000,
            recovery_type="modified_gross",
            expense_stop_per_sf=10.0,
        )
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        expected = Decimal("5000") * Decimal("2") / Decimal("12")
        assert abs(s.expense_recovery - expected) < Decimal("5")

    def test_below_stop_no_recovery(self):
        """Modified gross: expense/SF below stop → no recovery."""
        analysis = make_analysis()
        expense = make_expense(base_amount=80_000)  # $8/SF
        lease = make_lease(
            area=5_000,
            recovery_type="modified_gross",
            expense_stop_per_sf=10.0,  # $10/SF stop
        )
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        assert s.expense_recovery == Decimal(0)


class TestGrossUp:
    def test_grossup_increases_recovery_at_low_occupancy(self):
        """At 50% occupancy, expense grossed up to 95% reference level."""
        analysis = make_analysis()
        expense = make_expense(base_amount=100_000, is_gross_up=True, gross_up_pct=0.95)
        lease = make_lease(area=5_000, recovery_type="nnn")
        s = make_slice()
        occupancy = [Decimal("0.50")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        # Grossed up expense = 100K * (0.95 / 0.50) = 190K
        grossed_up = Decimal("100000") * (Decimal("0.95") / Decimal("0.50"))
        expected = grossed_up * Decimal("0.5") / Decimal("12")
        assert abs(s.expense_recovery - expected) < Decimal("20")

    def test_grossup_no_change_above_reference(self):
        """At or above reference occupancy, gross-up not applied."""
        analysis = make_analysis()
        expense = make_expense(base_amount=100_000, is_gross_up=True, gross_up_pct=0.95)
        lease = make_lease(area=5_000, recovery_type="nnn")
        s = make_slice()
        occupancy = [Decimal("0.95")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        expected = Decimal("100000") * Decimal("0.5") / Decimal("12")
        assert abs(s.expense_recovery - expected) < Decimal("5")

    def test_grossup_not_eligible_uses_actual_expense(self):
        """Expense not eligible for gross-up: actual expense used."""
        analysis = make_analysis()
        expense = make_expense(base_amount=100_000, is_gross_up=False)
        lease = make_lease(area=5_000, recovery_type="nnn")
        s = make_slice()
        occupancy = [Decimal("0.50")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        expected = Decimal("100000") * Decimal("0.5") / Decimal("12")
        assert abs(s.expense_recovery - expected) < Decimal("5")


class TestOverrides:
    def test_cap_limits_recovery(self):
        """Cap per SF limits the annual recovery per SF."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000)
        cap_override = ExpenseRecoveryOverride(
            expense_category="real_estate_taxes",
            recovery_type="nnn",
            base_year_stop_amount=None,
            cap_per_sf_annual=Decimal("8"),  # $8/SF cap → max 5K*8 = $40K/yr → $3333/mo
            floor_per_sf_annual=None,
            admin_fee_pct=None,
        )
        lease = make_lease(area=5_000, recovery_type="nnn", overrides=(cap_override,))
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        # Uncapped would be $5K/mo; cap is $8/SF * 5K SF / 12 = $3333/mo
        max_monthly = Decimal("8") * Decimal("5000") / Decimal("12")
        assert s.expense_recovery <= max_monthly + Decimal("1")

    def test_admin_fee_markup(self):
        """Admin fee markup increases recovery by specified pct."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000)
        admin_override = ExpenseRecoveryOverride(
            expense_category="real_estate_taxes",
            recovery_type="nnn",
            base_year_stop_amount=None,
            cap_per_sf_annual=None,
            floor_per_sf_annual=None,
            admin_fee_pct=Decimal("0.15"),  # 15% markup
        )
        lease = make_lease(area=5_000, recovery_type="nnn", overrides=(admin_override,))
        s = make_slice()
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        base_recovery = Decimal("120000") * Decimal("0.5") / Decimal("12")
        expected = base_recovery * Decimal("1.15")
        assert abs(s.expense_recovery - expected) < Decimal("10")


class TestFreeRentOnRecoveries:
    def test_free_rent_on_recoveries_suppresses_recovery(self):
        """Free rent period that applies_to_recoveries=True: no recovery that month."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000)
        frp = FreeRentPeriodInput(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            applies_to_base_rent=False,
            applies_to_recoveries=True,
        )
        lease = make_lease(recovery_type="nnn", free_rent_periods=(frp,))
        s = make_slice(month_index=0, period_start=date(2025, 1, 1))
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        assert s.expense_recovery == Decimal(0)

    def test_free_rent_only_on_base_rent_does_not_suppress_recovery(self):
        """Free rent that applies only to base rent, not recoveries."""
        analysis = make_analysis()
        expense = make_expense(base_amount=120_000)
        frp = FreeRentPeriodInput(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            applies_to_base_rent=True,
            applies_to_recoveries=False,
        )
        lease = make_lease(recovery_type="nnn", free_rent_periods=(frp,))
        s = make_slice(month_index=0, period_start=date(2025, 1, 1))
        occupancy = [Decimal("1.0")] * analysis.num_months

        attach_expense_recoveries([s], lease, [expense], analysis, Decimal("10000"), occupancy)

        # Recovery should still apply
        assert s.expense_recovery > Decimal(0)
