"""Unit tests for growth and escalation utilities."""
from datetime import date
from decimal import Decimal

import pytest

from src.engine.growth import expense_at_year, grow_amount, grow_to_date, rent_at_date


class TestGrowAmount:
    def test_zero_rate_returns_base(self):
        assert grow_amount(Decimal("1000"), Decimal("0"), Decimal("5")) == Decimal("1000")

    def test_3pct_5years(self):
        result = grow_amount(Decimal("1000"), Decimal("0.03"), Decimal("5"))
        expected = Decimal("1000") * (Decimal("1.03") ** 5)
        assert abs(result - expected) < Decimal("0.01")

    def test_10pct_1year(self):
        result = grow_amount(Decimal("1000"), Decimal("0.10"), Decimal("1"))
        assert abs(result - Decimal("1100")) < Decimal("0.01")

    def test_fractional_years(self):
        result = grow_amount(Decimal("1000"), Decimal("0.10"), Decimal("0.5"))
        expected = Decimal("1000") * (Decimal("1.10") ** Decimal("0.5"))
        assert abs(result - expected) < Decimal("0.01")


class TestGrowToDate:
    def test_target_before_base_returns_base(self):
        result = grow_to_date(
            Decimal("1000"), Decimal("0.10"),
            date(2025, 6, 1), date(2025, 1, 1),
        )
        assert result == Decimal("1000")

    def test_same_date_returns_base(self):
        result = grow_to_date(
            Decimal("1000"), Decimal("0.10"),
            date(2025, 1, 1), date(2025, 1, 1),
        )
        assert result == Decimal("1000")

    def test_anniversary_steps_one_year(self):
        """13+ months → floor(year_fraction) = 1 → one 10% bump.
        grow_to_date uses 365.25-day year; exactly 365 days gives 0.9993
        which floors to 0. Use 14 months to guarantee floor == 1."""
        result = grow_to_date(
            Decimal("1000"), Decimal("0.10"),
            date(2025, 1, 1), date(2026, 3, 1),
            anniversary_steps=True,
        )
        assert abs(result - Decimal("1100")) < Decimal("0.01")

    def test_anniversary_steps_before_first_anniversary(self):
        """11 months later: floor(year_fraction) = 0 → no bump."""
        result = grow_to_date(
            Decimal("1000"), Decimal("0.10"),
            date(2025, 1, 1), date(2025, 11, 30),
            anniversary_steps=True,
        )
        assert result == Decimal("1000")

    def test_anniversary_steps_two_years(self):
        """26+ months → floor(year_fraction) = 2 → two 10% bumps."""
        result = grow_to_date(
            Decimal("1000"), Decimal("0.10"),
            date(2025, 1, 1), date(2027, 3, 1),
            anniversary_steps=True,
        )
        assert abs(result - Decimal("1210")) < Decimal("0.01")

    def test_continuous_compounding(self):
        """anniversary_steps=False uses fractional year (continuous)."""
        result = grow_to_date(
            Decimal("1000"), Decimal("0.10"),
            date(2025, 1, 1), date(2025, 7, 1),
            anniversary_steps=False,
        )
        # Should be between 1000 and 1100 (partial year)
        assert Decimal("1000") < result < Decimal("1100")


class TestRentAtDate:
    def test_year1_before_anniversary_no_escalation(self):
        """Rent does not escalate before first anniversary."""
        result = rent_at_date(
            Decimal("100"), Decimal("0.03"),
            date(2025, 1, 1), date(2025, 12, 31),
        )
        assert result == Decimal("100")

    def test_on_first_anniversary_one_escalation(self):
        """On first anniversary, rent bumps by 3%."""
        result = rent_at_date(
            Decimal("100"), Decimal("0.03"),
            date(2025, 1, 1), date(2026, 1, 1),
        )
        assert abs(result - Decimal("103")) < Decimal("0.01")

    def test_on_second_anniversary_two_escalations(self):
        """Two anniversaries = 3% compounded twice."""
        result = rent_at_date(
            Decimal("100"), Decimal("0.03"),
            date(2025, 1, 1), date(2027, 1, 1),
        )
        expected = Decimal("100") * Decimal("1.03") ** 2
        assert abs(result - expected) < Decimal("0.01")

    def test_mid_lease_year_uses_floor_anniversary(self):
        """July 2026 = 1 full anniversary passed since Jan 2025 start."""
        result = rent_at_date(
            Decimal("100"), Decimal("0.03"),
            date(2025, 1, 1), date(2026, 6, 30),
        )
        # Only 1 anniversary (Jan 2026) has passed
        assert abs(result - Decimal("103")) < Decimal("0.01")

    def test_zero_rate_never_escalates(self):
        result = rent_at_date(
            Decimal("100"), Decimal("0"),
            date(2025, 1, 1), date(2035, 1, 1),
        )
        assert result == Decimal("100")

    def test_on_or_before_start_returns_base(self):
        result = rent_at_date(
            Decimal("100"), Decimal("0.05"),
            date(2025, 1, 1), date(2025, 1, 1),
        )
        assert result == Decimal("100")

    def test_mid_month_anniversary(self):
        """Lease starting July 15 — anniversary is July 15 of next year."""
        result = rent_at_date(
            Decimal("100"), Decimal("0.10"),
            date(2025, 7, 15), date(2026, 7, 15),
        )
        assert abs(result - Decimal("110")) < Decimal("0.01")


class TestExpenseAtYear:
    def test_year1_returns_base(self):
        assert expense_at_year(Decimal("100000"), Decimal("0.03"), 1) == Decimal("100000")

    def test_year0_or_negative_returns_base(self):
        assert expense_at_year(Decimal("100000"), Decimal("0.03"), 0) == Decimal("100000")

    def test_year2_one_growth(self):
        result = expense_at_year(Decimal("100000"), Decimal("0.03"), 2)
        assert abs(result - Decimal("103000")) < Decimal("0.01")

    def test_year5_four_growths(self):
        result = expense_at_year(Decimal("100000"), Decimal("0.03"), 5)
        expected = Decimal("100000") * Decimal("1.03") ** 4
        assert abs(result - expected) < Decimal("0.01")

    def test_zero_rate_no_growth(self):
        result = expense_at_year(Decimal("100000"), Decimal("0"), 10)
        assert result == Decimal("100000")
