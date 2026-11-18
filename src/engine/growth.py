"""
Growth and inflation helper functions for the DCF engine.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.engine.date_utils import year_fraction


def grow_amount(base: Decimal, annual_rate: Decimal, years: Decimal) -> Decimal:
    """
    Compound `base` at `annual_rate` for `years` (can be fractional).
    Uses continuous compounding: base * (1 + rate) ** years
    For annual steps we floor to integer years (lease anniversary convention).
    """
    if annual_rate == Decimal(0):
        return base
    return base * (Decimal(1) + annual_rate) ** years


def grow_to_date(
    base: Decimal,
    annual_rate: Decimal,
    base_date: date,
    target_date: date,
    anniversary_steps: bool = True,
) -> Decimal:
    """
    Grow `base` from `base_date` to `target_date`.

    If `anniversary_steps=True` (anniversary convention), escalation steps on the anniversary
    of `base_date` — e.g. if base_date is July 1, the first bump is July 1 of next year.
    This means we use integer years (floor of elapsed fraction).

    If `anniversary_steps=False`, use continuous compounding.
    """
    if target_date <= base_date:
        return base
    elapsed = year_fraction(base_date, target_date)
    years = Decimal(str(int(elapsed))) if anniversary_steps else elapsed
    return grow_amount(base, annual_rate, years)


def rent_at_date(
    base_rent: Decimal,
    annual_rate: Decimal,
    lease_start: date,
    as_of_date: date,
) -> Decimal:
    """
    Current rent for a pct_annual lease.
    Escalates on each lease anniversary (not calendar year).
    Counts full years by comparing anniversary dates directly — avoids
    floating-point day-count rounding issues.
    """
    if as_of_date <= lease_start or annual_rate == Decimal(0):
        return base_rent
    # Count how many full lease anniversaries have passed
    full_years = 0
    from src.engine.date_utils import add_months
    while True:
        anniversary = add_months(lease_start, (full_years + 1) * 12)
        if anniversary <= as_of_date:
            full_years += 1
        else:
            break
        if full_years >= 100:  # safety cap
            break
    if full_years == 0:
        return base_rent
    return grow_amount(base_rent, annual_rate, Decimal(str(full_years)))


def rate_for_year(
    annual_rate: Decimal,
    schedule: tuple[Decimal, ...] | list[Decimal] = (),
    year_number: int = 1,
) -> Decimal:
    """
    Growth rate in effect for a 1-based analysis year.

    `schedule[k]` is the rate for Year k+1; the last entry carries forward.
    With no schedule the single `annual_rate` applies to every year.
    """
    if not schedule:
        return annual_rate
    idx = min(max(year_number, 1), len(schedule)) - 1
    return schedule[idx]


def growth_factor_to_year(
    annual_rate: Decimal,
    year_number: int,
    schedule: tuple[Decimal, ...] | list[Decimal] = (),
) -> Decimal:
    """
    Cumulative growth multiplier from Year 1 to `year_number`.

    Year 1 = 1. Year N = product of (1 + rate for year k) for k = 2..N, so a
    one-entry schedule [r] matches the single-rate (1 + r) ** (N - 1).
    """
    if year_number <= 1:
        return Decimal(1)
    if not schedule:
        if annual_rate == Decimal(0):
            return Decimal(1)
        return (Decimal(1) + annual_rate) ** (year_number - 1)
    factor = Decimal(1)
    for year in range(2, year_number + 1):
        factor *= Decimal(1) + rate_for_year(annual_rate, schedule, year)
    return factor


def market_rent_at_year(
    base_rent: Decimal,
    annual_rate: Decimal,
    year_number: int,  # 1-based fiscal year; year 1 = base rent (no growth)
    schedule: tuple[Decimal, ...] | list[Decimal] = (),
) -> Decimal:
    """
    Market rent in a given fiscal year (fiscal-year convention).
    Year 1 = base, Year 2 = base × (1+rate), Year 3 = base × (1+rate)², etc.
    A year-by-year `schedule` replaces the single rate (see growth_factor_to_year).
    """
    if year_number <= 1:
        return base_rent
    if not schedule:
        if annual_rate == Decimal(0):
            return base_rent
        return grow_amount(base_rent, annual_rate, Decimal(str(year_number - 1)))
    return base_rent * growth_factor_to_year(annual_rate, year_number, schedule)


def expense_at_year(
    base_amount: Decimal,
    annual_rate: Decimal,
    year_number: int,  # 1-based; year 1 = base_amount
    schedule: tuple[Decimal, ...] | list[Decimal] = (),
) -> Decimal:
    """Annual operating expense in a given analysis year (1-indexed)."""
    if year_number <= 1:
        return base_amount
    if not schedule:
        return grow_amount(base_amount, annual_rate, Decimal(str(year_number - 1)))
    return base_amount * growth_factor_to_year(annual_rate, year_number, schedule)


def scheduled_amount_at_year(
    base_amount: Decimal,
    annual_rate: Decimal,
    year_number: int,
    growth_schedule: tuple[Decimal, ...] | list[Decimal] = (),
    amount_schedule: tuple[Decimal, ...] | list[Decimal] = (),
) -> Decimal:
    """Use an explicit annual dollar schedule when present; otherwise grow the base amount.

    Years past the end of the schedule (including the reversion year) grow from its last amount at
    the growth rate (or growth schedule), so a short schedule does not hold the line flat.
    """
    if amount_schedule:
        n = len(amount_schedule)
        year = max(year_number, 1)
        if year <= n:
            return amount_schedule[year - 1]
        return (amount_schedule[-1] * growth_factor_to_year(annual_rate, year, growth_schedule)
                / growth_factor_to_year(annual_rate, n, growth_schedule))
    return expense_at_year(base_amount, annual_rate, year_number, growth_schedule)
