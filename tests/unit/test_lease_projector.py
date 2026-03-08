"""Unit tests for the lease projector."""
from datetime import date
from decimal import Decimal

import pytest

from src.engine.date_utils import build_analysis_period
from src.engine.lease_projector import project_lease_cash_flows
from src.engine.types import AnalysisPeriod, FreeRentPeriodInput, LeaseInput, RentStepInput


def make_analysis(
    start: date = date(2025, 1, 1),
    months: int = 120,
    fy_end: int = 12,
) -> AnalysisPeriod:
    return build_analysis_period(start, months, fy_end)


def make_lease(
    start: date = date(2025, 1, 1),
    end: date = date(2029, 12, 31),
    rent: Decimal = Decimal("24.00"),  # $/SF/year
    area: Decimal = Decimal("1000"),
    escalation_type: str = "flat",
    escalation_pct: Decimal | None = None,
    rent_steps: tuple = (),
    free_rent_periods: tuple = (),
    frequency: str = "annual",
) -> LeaseInput:
    return LeaseInput(
        lease_id="test_lease",
        suite_id="suite_1",
        tenant_name="Test Tenant",
        area=area,
        start_date=start,
        end_date=end,
        base_rent_per_unit=rent,
        rent_payment_frequency=frequency,
        escalation_type=escalation_type,
        escalation_pct=escalation_pct,
        cpi_floor=None,
        cpi_cap=None,
        rent_steps=rent_steps,
        free_rent_periods=free_rent_periods,
        recovery_type="nnn",
        pro_rata_share=None,
        base_year_stop_amount=None,
        expense_stop_per_sf=None,
        recovery_overrides=(),
        pct_rent_breakpoint=None,
        pct_rent_rate=None,
        renewal_probability_override=None,
    )


class TestFlatRent:
    def test_12_month_flat_lease(self):
        """$24/SF/year on 1,000 SF = $2,000/month over 12 months."""
        lease = make_lease(
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            rent=Decimal("24.00"),
            area=Decimal("1000"),
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)

        assert len(slices) == 12
        for s in slices:
            assert s.base_rent == Decimal("2000.00")
            assert s.effective_rent == Decimal("2000.00")
            assert s.free_rent_adjustment == Decimal("0")

        total = sum(s.effective_rent for s in slices)
        assert total == Decimal("24000.00")

    def test_lease_outside_analysis_produces_no_slices(self):
        lease = make_lease(
            start=date(2030, 1, 1),
            end=date(2030, 12, 31),
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)
        assert len(slices) == 0

    def test_lease_partially_in_analysis(self):
        """Lease starts mid-analysis-period."""
        lease = make_lease(
            start=date(2025, 7, 1),
            end=date(2026, 6, 30),
            rent=Decimal("24.00"),
            area=Decimal("1000"),
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)  # Jan-Dec 2025
        slices = project_lease_cash_flows(lease, analysis)
        assert len(slices) == 6  # Jul-Dec 2025


class TestPctAnnualEscalation:
    def test_3pct_annual_escalation(self):
        """$20/SF/yr, 3% annual escalation, 3-year lease, 1,000 SF.
        Year 1: $20 * 1000 / 12 = $1,666.67/mo
        Year 2: $20.60 * 1000 / 12 = $1,716.67/mo (rounded)
        Year 3: $21.218 * 1000 / 12 = $1,768.17/mo (approx)
        """
        lease = make_lease(
            start=date(2025, 1, 1),
            end=date(2027, 12, 31),
            rent=Decimal("20.00"),
            area=Decimal("1000"),
            escalation_type="pct_annual",
            escalation_pct=Decimal("0.03"),
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=36)
        slices = project_lease_cash_flows(lease, analysis)
        assert len(slices) == 36

        # Year 1 (months 0-11): $20/SF/yr = $1666.67/mo
        y1_rents = [s.base_rent for s in slices[:12]]
        for r in y1_rents:
            assert abs(r - Decimal("1666.666667")) < Decimal("0.01")

        # Year 2 (months 12-23): escalates on Jan 1, 2026 (lease anniversary)
        y2_rents = [s.base_rent for s in slices[12:24]]
        expected_y2_monthly = Decimal("20.00") * Decimal("1.03") * Decimal("1000") / Decimal("12")
        for r in y2_rents:
            assert abs(r - expected_y2_monthly) < Decimal("0.01")

    def test_escalation_happens_on_anniversary_not_calendar_year(self):
        """Lease starting July 1 should escalate July 1 of next year."""
        lease = make_lease(
            start=date(2025, 7, 1),
            end=date(2027, 6, 30),
            rent=Decimal("20.00"),
            area=Decimal("1000"),
            escalation_type="pct_annual",
            escalation_pct=Decimal("0.03"),
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=36)
        slices = project_lease_cash_flows(lease, analysis)

        # Months Jul 2025 - Jun 2026 should all be at $20/SF
        y1_months = [s for s in slices if s.period_start < date(2026, 7, 1)]
        for s in y1_months:
            expected = Decimal("20.00") * Decimal("1000") / Decimal("12")
            assert abs(s.base_rent - expected) < Decimal("0.01")

        # Months Jul 2026+ should be at $20.60/SF
        y2_months = [s for s in slices if s.period_start >= date(2026, 7, 1)]
        for s in y2_months:
            expected = Decimal("20.60") * Decimal("1000") / Decimal("12")
            assert abs(s.base_rent - expected) < Decimal("0.01")


class TestFixedStepEscalation:
    def test_fixed_steps(self):
        """Rent steps: $20 initially, $22 on Jan 1 2026, $24 on Jan 1 2027."""
        rent_steps = (
            RentStepInput(effective_date=date(2026, 1, 1), rent_per_unit=Decimal("22.00")),
            RentStepInput(effective_date=date(2027, 1, 1), rent_per_unit=Decimal("24.00")),
        )
        lease = make_lease(
            start=date(2025, 1, 1),
            end=date(2027, 12, 31),
            rent=Decimal("20.00"),
            area=Decimal("1000"),
            escalation_type="fixed_step",
            rent_steps=rent_steps,
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=36)
        slices = project_lease_cash_flows(lease, analysis)

        y1 = [s.base_rent for s in slices if s.period_start.year == 2025]
        y2 = [s.base_rent for s in slices if s.period_start.year == 2026]
        y3 = [s.base_rent for s in slices if s.period_start.year == 2027]

        for r in y1:
            assert abs(r - Decimal("1666.667")) < Decimal("0.01")
        for r in y2:
            assert abs(r - Decimal("22") * 1000 / 12) < Decimal("0.01")
        for r in y3:
            assert abs(r - Decimal("24") * 1000 / 12) < Decimal("0.01")


class TestFreeRent:
    def test_3_months_free_rent(self):
        """3 months free rent at lease start."""
        free_rent = (FreeRentPeriodInput(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31),
            applies_to_base_rent=True,
            applies_to_recoveries=False,
        ),)
        lease = make_lease(
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            rent=Decimal("24.00"),
            area=Decimal("1000"),
            free_rent_periods=free_rent,
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)

        # Jan-Mar: free rent
        free_months = [s for s in slices if s.period_start.month <= 3]
        for s in free_months:
            assert s.base_rent == Decimal("2000.00")
            assert s.free_rent_adjustment == Decimal("-2000.00")
            assert s.effective_rent == Decimal("0.00")

        # Apr-Dec: paying rent
        paying_months = [s for s in slices if s.period_start.month > 3]
        for s in paying_months:
            assert s.effective_rent == Decimal("2000.00")

    def test_annual_rent_with_free_rent_reduces_income(self):
        """Total annual rent should reflect 3 months free."""
        free_rent = (FreeRentPeriodInput(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31),
            applies_to_base_rent=True,
            applies_to_recoveries=False,
        ),)
        lease = make_lease(
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            rent=Decimal("24.00"),
            area=Decimal("1000"),
            free_rent_periods=free_rent,
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)
        total_effective = sum(s.effective_rent for s in slices)
        # 9 months at $2,000 = $18,000
        assert total_effective == Decimal("18000.00")

    def test_mid_year_partial_start_full_free_month_zeros_effective_rent(self):
        """
        If a lease starts mid-month and all active days are free, effective rent
        for that partial month should be zero (no double-proration).
        """
        free_rent = (FreeRentPeriodInput(
            start_date=date(2025, 7, 15),
            end_date=date(2025, 7, 31),
            applies_to_base_rent=True,
            applies_to_recoveries=False,
        ),)
        lease = make_lease(
            start=date(2025, 7, 15),
            end=date(2025, 12, 31),
            rent=Decimal("24.00"),
            area=Decimal("1000"),
            free_rent_periods=free_rent,
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)

        first = slices[0]  # Jul 2025
        assert first.period_start == date(2025, 7, 1)
        assert abs(first.effective_rent - Decimal("0")) < Decimal("0.01")
        assert abs(first.free_rent_adjustment + first.base_rent) < Decimal("0.01")

    def test_mid_year_partial_start_partial_free_days_apply_to_active_days_only(self):
        """
        Free-rent fraction should be measured against active lease days in the
        month, not total calendar month days.
        """
        free_rent = (FreeRentPeriodInput(
            start_date=date(2025, 7, 15),
            end_date=date(2025, 7, 23),  # 9 free days out of 17 active days
            applies_to_base_rent=True,
            applies_to_recoveries=False,
        ),)
        lease = make_lease(
            start=date(2025, 7, 15),
            end=date(2025, 12, 31),
            rent=Decimal("24.00"),
            area=Decimal("1000"),
            free_rent_periods=free_rent,
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)

        first = slices[0]  # Jul 2025
        expected_effective = first.base_rent * Decimal("8") / Decimal("17")
        assert abs(first.effective_rent - expected_effective) < Decimal("0.01")


class TestCPIEscalation:
    def _cpi_lease(
        self,
        start: date = date(2025, 1, 1),
        end: date = date(2027, 12, 31),
        rent: Decimal = Decimal("20.00"),
        area: Decimal = Decimal("1000"),
        cpi_floor: Decimal | None = None,
        cpi_cap: Decimal | None = None,
    ) -> LeaseInput:
        return LeaseInput(
            lease_id="cpi_lease",
            suite_id="suite_1",
            tenant_name="CPI Tenant",
            area=area,
            start_date=start,
            end_date=end,
            base_rent_per_unit=rent,
            rent_payment_frequency="annual",
            escalation_type="cpi",
            escalation_pct=None,
            cpi_floor=cpi_floor,
            cpi_cap=cpi_cap,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="nnn",
            pro_rata_share=None,
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
            renewal_probability_override=None,
        )

    def test_cpi_year1_no_escalation(self):
        """Year 1 of a CPI lease uses base rent — no escalation before first anniversary."""
        lease = self._cpi_lease()
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis, cpi_assumption=Decimal("0.025"))

        expected_monthly = Decimal("20.00") * Decimal("1000") / Decimal("12")
        for s in slices:
            assert abs(s.base_rent - expected_monthly) < Decimal("0.01")

    def test_cpi_escalates_on_anniversary(self):
        """First escalation happens on the lease anniversary (Jan 1, 2026 for a Jan 1 start)."""
        lease = self._cpi_lease(end=date(2026, 12, 31))
        analysis = make_analysis(start=date(2025, 1, 1), months=24)
        slices = project_lease_cash_flows(lease, analysis, cpi_assumption=Decimal("0.025"))

        # Year 1 (Jan-Dec 2025): base rent $20/SF
        y1 = [s for s in slices if s.period_start.year == 2025]
        for s in y1:
            expected = Decimal("20.00") * Decimal("1000") / Decimal("12")
            assert abs(s.base_rent - expected) < Decimal("0.01")

        # Year 2 (Jan-Dec 2026): one CPI bump → $20 * 1.025 = $20.50/SF
        y2 = [s for s in slices if s.period_start.year == 2026]
        for s in y2:
            expected = Decimal("20.00") * Decimal("1.025") * Decimal("1000") / Decimal("12")
            assert abs(s.base_rent - expected) < Decimal("0.01")

    def test_cpi_three_years_two_bumps(self):
        """Two anniversaries → rent escalated twice."""
        lease = self._cpi_lease(end=date(2027, 12, 31))
        analysis = make_analysis(start=date(2025, 1, 1), months=36)
        slices = project_lease_cash_flows(lease, analysis, cpi_assumption=Decimal("0.025"))

        y3 = [s for s in slices if s.period_start.year == 2027]
        expected = Decimal("20.00") * Decimal("1.025") ** 2 * Decimal("1000") / Decimal("12")
        for s in y3:
            assert abs(s.base_rent - expected) < Decimal("0.01")

    def test_cpi_floor_raises_low_cpi(self):
        """CPI 1% with floor 2% → applies 2% escalation."""
        lease = self._cpi_lease(end=date(2026, 12, 31), cpi_floor=Decimal("0.02"))
        analysis = make_analysis(start=date(2025, 1, 1), months=24)
        slices = project_lease_cash_flows(lease, analysis, cpi_assumption=Decimal("0.01"))

        y2 = [s for s in slices if s.period_start.year == 2026]
        for s in y2:
            expected = Decimal("20.00") * Decimal("1.02") * Decimal("1000") / Decimal("12")
            assert abs(s.base_rent - expected) < Decimal("0.01")

    def test_cpi_cap_limits_high_cpi(self):
        """CPI 5% with cap 3% → applies 3% escalation."""
        lease = self._cpi_lease(end=date(2026, 12, 31), cpi_cap=Decimal("0.03"))
        analysis = make_analysis(start=date(2025, 1, 1), months=24)
        slices = project_lease_cash_flows(lease, analysis, cpi_assumption=Decimal("0.05"))

        y2 = [s for s in slices if s.period_start.year == 2026]
        for s in y2:
            expected = Decimal("20.00") * Decimal("1.03") * Decimal("1000") / Decimal("12")
            assert abs(s.base_rent - expected) < Decimal("0.01")

    def test_cpi_non_january_start_anniversary(self):
        """Lease starting July 1 escalates on July 1 of the following year."""
        lease = self._cpi_lease(start=date(2025, 7, 1), end=date(2026, 12, 31))
        analysis = make_analysis(start=date(2025, 1, 1), months=24)
        slices = project_lease_cash_flows(lease, analysis, cpi_assumption=Decimal("0.025"))

        # Months before anniversary (Jul 2025 - Jun 2026): base rent
        pre_anniversary = [s for s in slices if s.period_start < date(2026, 7, 1)]
        for s in pre_anniversary:
            expected = Decimal("20.00") * Decimal("1000") / Decimal("12")
            assert abs(s.base_rent - expected) < Decimal("0.01")

        # Months at/after anniversary (Jul 2026+): escalated
        post_anniversary = [s for s in slices if s.period_start >= date(2026, 7, 1)]
        for s in post_anniversary:
            expected = Decimal("20.00") * Decimal("1.025") * Decimal("1000") / Decimal("12")
            assert abs(s.base_rent - expected) < Decimal("0.01")


class TestPercentageRent:
    def _retail_lease(
        self,
        breakpoint: Decimal,
        rate: Decimal,
        sales_per_sf: Decimal,
        rent: Decimal = Decimal("25.00"),
        area: Decimal = Decimal("2000"),
    ) -> LeaseInput:
        return LeaseInput(
            lease_id="retail_lease",
            suite_id="suite_retail",
            tenant_name="Retail Tenant",
            area=area,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            base_rent_per_unit=rent,
            rent_payment_frequency="annual",
            escalation_type="flat",
            escalation_pct=None,
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="nnn",
            pro_rata_share=None,
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=breakpoint,
            pct_rent_rate=rate,
            renewal_probability_override=None,
            projected_annual_sales_per_sf=sales_per_sf,
        )

    def test_no_pct_rent_when_below_breakpoint(self):
        """Sales below breakpoint → no percentage rent."""
        # Breakpoint $400,000, sales = $300/SF * 2000 SF = $600,000 < breakpoint — wait, let me fix
        # Breakpoint $700,000, sales = $300/SF * 2000 SF = $600,000 < $700,000
        lease = self._retail_lease(
            breakpoint=Decimal("700000"),
            rate=Decimal("0.06"),
            sales_per_sf=Decimal("300"),
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)

        for s in slices:
            assert s.percentage_rent == Decimal(0)

    def test_pct_rent_when_above_breakpoint(self):
        """Sales above breakpoint → percentage rent = overage * rate / 12."""
        # Breakpoint $400,000, sales = $300/SF * 2000 SF = $600,000 → overage = $200,000
        # Annual pct rent = $200,000 * 6% = $12,000 → monthly = $1,000
        lease = self._retail_lease(
            breakpoint=Decimal("400000"),
            rate=Decimal("0.06"),
            sales_per_sf=Decimal("300"),  # $300 * 2000 SF = $600,000 annual sales
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)

        expected_monthly = Decimal("1000")  # ($600,000 - $400,000) * 0.06 / 12
        for s in slices:
            assert abs(s.percentage_rent - expected_monthly) < Decimal("0.01")

    def test_pct_rent_at_breakpoint_is_zero(self):
        """Sales exactly at breakpoint → zero overage → zero percentage rent."""
        lease = self._retail_lease(
            breakpoint=Decimal("600000"),
            rate=Decimal("0.06"),
            sales_per_sf=Decimal("300"),  # $300 * 2000 = exactly $600,000
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)

        for s in slices:
            assert s.percentage_rent == Decimal(0)

    def test_no_pct_rent_without_sales_projection(self):
        """LeaseInput without projected_annual_sales_per_sf → no percentage rent."""
        lease = make_lease(
            rent=Decimal("25.00"),
            area=Decimal("2000"),
            escalation_type="flat",
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)

        for s in slices:
            assert s.percentage_rent == Decimal(0)

    def test_pct_rent_included_in_effective_rent_total(self):
        """Verify percentage rent appears as a separate field (not merged into effective_rent)."""
        lease = self._retail_lease(
            breakpoint=Decimal("400000"),
            rate=Decimal("0.06"),
            sales_per_sf=Decimal("300"),
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)

        # effective_rent is base rent only; percentage_rent is separate
        for s in slices:
            base_monthly = Decimal("25.00") * Decimal("2000") / Decimal("12")
            assert abs(s.effective_rent - base_monthly) < Decimal("0.01")
            assert s.percentage_rent > Decimal(0)


class TestMonthlyLeases:
    def test_monthly_basis_multifamily(self):
        """$1,500/unit/month on 1 unit = $1,500/month."""
        lease = LeaseInput(
            lease_id="mf_lease",
            suite_id="unit_1A",
            tenant_name="Resident",
            area=Decimal("1"),  # 1 unit
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            base_rent_per_unit=Decimal("1500.00"),
            rent_payment_frequency="monthly",
            escalation_type="flat",
            escalation_pct=None,
            cpi_floor=None,
            cpi_cap=None,
            rent_steps=(),
            free_rent_periods=(),
            recovery_type="none",
            pro_rata_share=None,
            base_year_stop_amount=None,
            expense_stop_per_sf=None,
            recovery_overrides=(),
            pct_rent_breakpoint=None,
            pct_rent_rate=None,
            renewal_probability_override=None,
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)
        assert len(slices) == 12
        for s in slices:
            assert s.base_rent == Decimal("1500.00")


class TestEdgeCases:
    """Boundary scenarios: pre-analysis leases, clipping, partial months."""

    def test_pre_analysis_lease_escalation_from_original_start(self):
        """
        Lease that started before the analysis period must escalate from its
        actual start date, not the analysis start.

        Lease: Jan 1 2023, $20/SF/yr, 3% pct_annual, 1,000 SF.
        Analysis: Jan 1 2025 (2 full years have elapsed).
        Expected rent at Jan 2025: $20 * 1.03^2 = $21.218/SF/yr
        Monthly: $21.218 * 1000 / 12 = $1,768.17
        """
        lease = make_lease(
            start=date(2023, 1, 1),
            end=date(2027, 12, 31),
            rent=Decimal("20.00"),
            area=Decimal("1000"),
            escalation_type="pct_annual",
            escalation_pct=Decimal("0.03"),
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)

        assert len(slices) == 12
        expected_rent = Decimal("20.00") * Decimal("1.03") ** 2
        expected_monthly = expected_rent * Decimal("1000") / Decimal("12")
        for s in slices:
            assert abs(s.base_rent - expected_monthly) < Decimal("0.01"), (
                f"Expected {expected_monthly:.4f}, got {s.base_rent:.4f}"
            )

    def test_pre_analysis_lease_escalates_again_on_anniversary_in_period(self):
        """
        Pre-analysis lease: anniversaries from the original start date matter.
        Lease started Jul 1 2023, 3% annual escalation.

        Anniversary schedule:
          Jul 1 2024 (1st)  →  rent = $20 * 1.03^1
          Jul 1 2025 (2nd)  →  rent = $20 * 1.03^2
          Jul 1 2026 (3rd)  →  rent = $20 * 1.03^3

        In the analysis window Jan 2025 – Dec 2026:
          Jan–Jun 2025: 1 anniversary elapsed (Jul 2024) → 1.03^1
          Jul 2025–Jun 2026: 2 anniversaries elapsed      → 1.03^2
          Jul–Dec 2026: 3 anniversaries elapsed            → 1.03^3
        """
        lease = make_lease(
            start=date(2023, 7, 1),
            end=date(2028, 6, 30),
            rent=Decimal("20.00"),
            area=Decimal("1000"),
            escalation_type="pct_annual",
            escalation_pct=Decimal("0.03"),
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=24)
        slices = project_lease_cash_flows(lease, analysis)

        # Jan–Jun 2025: 1 full anniversary → $20 * 1.03^1
        seg1 = [s for s in slices if s.period_start < date(2025, 7, 1)]
        exp1 = Decimal("20.00") * Decimal("1.03") ** 1 * Decimal("1000") / Decimal("12")
        for s in seg1:
            assert abs(s.base_rent - exp1) < Decimal("0.01")

        # Jul 2025–Jun 2026: 2nd anniversary passed → $20 * 1.03^2
        seg2 = [s for s in slices if date(2025, 7, 1) <= s.period_start < date(2026, 7, 1)]
        exp2 = Decimal("20.00") * Decimal("1.03") ** 2 * Decimal("1000") / Decimal("12")
        for s in seg2:
            assert abs(s.base_rent - exp2) < Decimal("0.01")

        # Jul–Dec 2026: 3rd anniversary passed → $20 * 1.03^3
        seg3 = [s for s in slices if s.period_start >= date(2026, 7, 1)]
        exp3 = Decimal("20.00") * Decimal("1.03") ** 3 * Decimal("1000") / Decimal("12")
        for s in seg3:
            assert abs(s.base_rent - exp3) < Decimal("0.01")

    def test_beyond_analysis_lease_clips_to_analysis_end(self):
        """
        Lease ending Dec 2040 in a 10-year analysis (end Dec 2034).
        Only 120 months of slices should be produced — the lease is clipped.
        """
        lease = make_lease(
            start=date(2025, 1, 1),
            end=date(2040, 12, 31),
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=120)
        slices = project_lease_cash_flows(lease, analysis)

        assert len(slices) == 120
        # Last slice should be within analysis period
        assert slices[-1].period_end <= date(2034, 12, 31)

    def test_lease_spanning_analysis_start_partial_first_month(self):
        """
        Lease starts Jan 15, analysis starts Jan 1.
        The first month (Jan) should be prorated to 17/31 of a full month.
        """
        lease = make_lease(
            start=date(2025, 1, 15),
            end=date(2025, 12, 31),
            rent=Decimal("24.00"),
            area=Decimal("1000"),
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=12)
        slices = project_lease_cash_flows(lease, analysis)

        # First slice: Jan 2025, rent should be prorated 17/31
        first = slices[0]
        full_month = Decimal("24.00") * Decimal("1000") / Decimal("12")
        expected = full_month * Decimal("17") / Decimal("31")
        assert abs(first.base_rent - expected) < Decimal("0.01")

        # Remaining months: full rent
        for s in slices[1:]:
            assert abs(s.base_rent - full_month) < Decimal("0.01")

    def test_fixed_step_pre_analysis_step_applies(self):
        """
        Fixed step escalation where one step effective date is before analysis start.
        The step should still apply (it's the rate in effect at analysis start).
        """
        rent_steps = (
            RentStepInput(effective_date=date(2024, 1, 1), rent_per_unit=Decimal("22.00")),
            RentStepInput(effective_date=date(2026, 1, 1), rent_per_unit=Decimal("24.00")),
        )
        lease = make_lease(
            start=date(2023, 1, 1),
            end=date(2027, 12, 31),
            rent=Decimal("20.00"),
            area=Decimal("1000"),
            escalation_type="fixed_step",
            rent_steps=rent_steps,
        )
        analysis = make_analysis(start=date(2025, 1, 1), months=24)
        slices = project_lease_cash_flows(lease, analysis)

        # Jan 2025 - Dec 2025: step at 2024-01-01 is active → $22/SF
        y2025 = [s for s in slices if s.period_start.year == 2025]
        for s in y2025:
            assert abs(s.base_rent - Decimal("22") * 1000 / 12) < Decimal("0.01")

        # Jan 2026+: step at 2026-01-01 kicks in → $24/SF
        y2026 = [s for s in slices if s.period_start.year == 2026]
        for s in y2026:
            assert abs(s.base_rent - Decimal("24") * 1000 / 12) < Decimal("0.01")
