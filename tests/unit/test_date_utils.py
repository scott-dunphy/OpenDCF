"""Unit tests for date_utils module."""
from datetime import date

import pytest

from src.engine.date_utils import (
    add_months,
    build_analysis_period,
    end_of_month,
    months_between,
    proration_factor,
    year_fraction,
)
from decimal import Decimal


def test_add_months_simple():
    assert add_months(date(2025, 1, 1), 1) == date(2025, 2, 1)
    assert add_months(date(2025, 1, 1), 12) == date(2026, 1, 1)
    assert add_months(date(2025, 1, 1), 6) == date(2025, 7, 1)


def test_add_months_clamps_to_last_day():
    # Jan 31 + 1 month = Feb 28 (not Feb 31)
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)  # leap year


def test_end_of_month():
    assert end_of_month(date(2025, 1, 15)) == date(2025, 1, 31)
    assert end_of_month(date(2025, 2, 1)) == date(2025, 2, 28)
    assert end_of_month(date(2024, 2, 1)) == date(2024, 2, 29)  # leap year


def test_months_between():
    assert months_between(date(2025, 1, 1), date(2025, 12, 1)) == 11
    assert months_between(date(2025, 1, 1), date(2026, 1, 1)) == 12
    assert months_between(date(2025, 6, 1), date(2025, 9, 1)) == 3


def test_proration_full_month():
    # Full month coverage
    pct = proration_factor(date(2025, 1, 1), date(2025, 1, 31),
                           date(2025, 1, 1), date(2025, 1, 31))
    assert pct == Decimal(1)


def test_proration_half_month():
    # Lease starts mid-month (Jan 16-31 = 16 of 31 days)
    pct = proration_factor(date(2025, 1, 1), date(2025, 1, 31),
                           date(2025, 1, 16), date(2025, 3, 31))
    expected = Decimal("16") / Decimal("31")
    assert abs(pct - expected) < Decimal("0.0001")


def test_proration_no_overlap():
    pct = proration_factor(date(2025, 1, 1), date(2025, 1, 31),
                           date(2025, 2, 1), date(2025, 2, 28))
    assert pct == Decimal(0)


def test_build_analysis_period_10_years():
    period = build_analysis_period(date(2025, 1, 1), 120, 12)
    assert period.num_months == 120
    assert period.start_date == date(2025, 1, 1)
    assert len(period.fiscal_years) == 10
    assert period.fiscal_years[0].year_number == 1
    assert period.fiscal_years[0].start_date == date(2025, 1, 1)
    assert period.fiscal_years[0].end_date == date(2025, 12, 31)
    assert period.fiscal_years[-1].year_number == 10
    assert period.fiscal_years[-1].end_date == date(2034, 12, 31)


def test_year_fraction():
    # 1 year = 365 days / 365.25 ≈ 0.9993...
    frac = year_fraction(date(2025, 1, 1), date(2026, 1, 1))
    assert abs(frac - Decimal("1.0")) < Decimal("0.005")

    # 6 months ≈ 0.5 years
    frac_half = year_fraction(date(2025, 1, 1), date(2025, 7, 1))
    assert abs(frac_half - Decimal("0.5")) < Decimal("0.01")
