"""
Date arithmetic utilities for the DCF engine.
All operations use only stdlib datetime — no third-party deps.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from src.engine.types import AnalysisPeriod, FiscalYear


def add_months(d: date, months: int) -> date:
    """Add `months` to a date, clamping to the last day of the target month."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return date(year, month, day)


def end_of_month(d: date) -> date:
    """Return the last day of the month containing `d`."""
    last_day = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last_day)


def start_of_month(d: date) -> date:
    return date(d.year, d.month, 1)


def months_between(start: date, end: date) -> int:
    """Number of whole months from start to end (truncated)."""
    return (end.year - start.year) * 12 + (end.month - start.month)


def year_fraction(start: date, current: date) -> Decimal:
    """
    Decimal fraction of years elapsed from start to current.
    Uses actual day count / 365.25.
    """
    delta = (current - start).days
    return Decimal(str(delta)) / Decimal("365.25")


def days_in_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def build_analysis_period(
    start_date: date,
    num_months: int,
    fiscal_year_end_month: int,
) -> AnalysisPeriod:
    """
    Build the AnalysisPeriod with pre-computed 12-month analysis years.
    Year 1 starts on `start_date`, Year 2 starts 12 months later, etc.
    The final year may be partial if `num_months` is not a multiple of 12.

    `fiscal_year_end_month` is retained on AnalysisPeriod for compatibility,
    but annual aggregation is anchored to `start_date`.
    """
    end_date = add_months(start_date, num_months) - timedelta(days=1)

    fiscal_years: list[FiscalYear] = []
    year_start = start_date
    year_num = 1

    while year_start <= end_date:
        year_end = min(add_months(year_start, 12) - timedelta(days=1), end_date)
        fiscal_years.append(FiscalYear(
            year_number=year_num,
            start_date=year_start,
            end_date=year_end,
        ))
        year_num += 1
        year_start = year_end + timedelta(days=1)

    return AnalysisPeriod(
        start_date=start_date,
        end_date=end_date,
        num_months=num_months,
        fiscal_year_end_month=fiscal_year_end_month,
        fiscal_years=tuple(fiscal_years),
    )


def iter_months(start_date: date, num_months: int):
    """Yield (month_index, period_start, period_end) for each month in analysis period."""
    for i in range(num_months):
        period_start = add_months(start_date, i)
        period_end = end_of_month(period_start)
        yield i, period_start, period_end


def proration_factor(
    period_start: date,
    period_end: date,
    lease_start: date,
    lease_end: date,
) -> Decimal:
    """
    Fraction of the month [period_start, period_end] during which the lease is active.
    Returns a Decimal in [0, 1].
    """
    active_start = max(period_start, lease_start)
    active_end = min(period_end, lease_end)
    if active_start > active_end:
        return Decimal(0)
    active_days = (active_end - active_start).days + 1
    total_days = (period_end - period_start).days + 1
    return Decimal(str(active_days)) / Decimal(str(total_days))


def fiscal_year_for_month(analysis: AnalysisPeriod, period_start: date) -> FiscalYear | None:
    """Return the analysis-year bucket that contains period_start."""
    for fy in analysis.fiscal_years:
        if fy.start_date <= period_start <= fy.end_date:
            return fy
    return None
