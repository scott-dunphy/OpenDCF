"""
Single-lease monthly cash flow projection.

Handles all escalation types (flat, pct_annual, cpi, fixed_step) and
free rent abatement. Does NOT compute expense recoveries (handled by
expense_engine.py) or TI/LC for speculative leases (handled by renewal_engine.py).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from src.engine.date_utils import (
    add_months,
    days_in_month,
    iter_months,
    months_between,
    proration_factor,
    year_fraction,
)
from src.engine.growth import rate_for_year, rent_at_date
from src.engine.types import AnalysisPeriod, FreeRentPeriodInput, LeaseInput, MonthlySlice


def _current_rent(
    lease: LeaseInput,
    period_start: date,
    cpi_assumption: Decimal,
    cpi_schedule: tuple[Decimal, ...] = (),
    analysis_start: date | None = None,
) -> Decimal:
    """Determine the effective rent rate for a given month start date."""
    esc = lease.escalation_type

    if esc == "flat":
        return lease.base_rent_per_unit

    elif esc == "pct_annual":
        rate = lease.escalation_pct or Decimal(0)
        return rent_at_date(lease.base_rent_per_unit, rate, lease.start_date, period_start)

    elif esc == "cpi":
        # CPI with floor and cap, steps on each lease anniversary.
        # Count anniversaries the same way rent_at_date does (add_months), so
        # a Jan-1 start escalates exactly on Jan 1 of each subsequent year.
        n = 0
        anniversary = lease.start_date
        while True:
            next_anniversary = add_months(anniversary, 12)
            if next_anniversary > period_start:
                break
            n += 1
            anniversary = next_anniversary
        current = lease.base_rent_per_unit
        for k in range(1, n + 1):
            cpi_adj = cpi_assumption
            if cpi_schedule and analysis_start is not None:
                # CPI for the analysis year containing this anniversary (Year 1 before the analysis)
                bump_date = add_months(lease.start_date, 12 * k)
                year_number = months_between(analysis_start, bump_date) // 12 + 1
                cpi_adj = rate_for_year(cpi_assumption, cpi_schedule, year_number)
            if lease.cpi_floor is not None:
                cpi_adj = max(lease.cpi_floor, cpi_adj)
            if lease.cpi_cap is not None:
                cpi_adj = min(lease.cpi_cap, cpi_adj)
            current = current * (Decimal(1) + cpi_adj)
        return current

    elif esc == "fixed_step":
        # Use the most recent step on or before period_start
        current = lease.base_rent_per_unit
        for step in sorted(lease.rent_steps, key=lambda s: s.effective_date):
            if step.effective_date <= period_start:
                current = step.rent_per_unit
            else:
                break
        return current

    return lease.base_rent_per_unit


def _free_rent_factor(
    free_rent_periods: tuple[FreeRentPeriodInput, ...],
    period_start: date,
    period_end: date,
    for_base_rent: bool,
    lease_start: date | None = None,
    lease_end: date | None = None,
) -> Decimal:
    """
    Returns the fraction of active lease days in the period that are free-rent days.
    1.0 = all active days are free, 0.0 = no free-rent overlap.
    """
    active_window_start = max(period_start, lease_start) if lease_start is not None else period_start
    active_window_end = min(period_end, lease_end) if lease_end is not None else period_end
    if active_window_start > active_window_end:
        return Decimal(0)

    total_days = (active_window_end - active_window_start).days + 1
    free_days = 0

    for frp in free_rent_periods:
        if for_base_rent and not frp.applies_to_base_rent:
            continue
        if not for_base_rent and not frp.applies_to_recoveries:
            continue

        overlap_start = max(active_window_start, frp.start_date)
        overlap_end = min(active_window_end, frp.end_date)
        if overlap_start <= overlap_end:
            free_days += (overlap_end - overlap_start).days + 1

    free_days = min(free_days, total_days)
    return Decimal(str(free_days)) / Decimal(str(total_days))


def _prorated_step_rent(
    lease: LeaseInput,
    period_start: date,
    period_end: date,
) -> tuple[Decimal, Decimal]:
    """
    Fixed-step rent for one month, split at rent-step dates inside the lease's active days.

    Each segment earns its step's monthly rent x segment days / days in month, and free rent
    abates the segment's free days at that segment's rent. Returns (base rent, free rent adjustment).
    """
    active_start = max(period_start, lease.start_date)
    active_end = min(period_end, lease.end_date)
    month_days = Decimal(str((period_end - period_start).days + 1))
    cuts = sorted({s.effective_date for s in lease.rent_steps if active_start < s.effective_date <= active_end})

    rent = Decimal(0)
    free = Decimal(0)
    for seg_start, next_start in zip([active_start, *cuts], [*cuts, active_end + timedelta(days=1)]):
        seg_end = next_start - timedelta(days=1)
        seg_pct = Decimal(str((next_start - seg_start).days)) / month_days
        rate = _current_rent(lease, seg_start, Decimal(0))
        if lease.rent_payment_frequency == "monthly":
            seg_rent = rate * lease.rent_area * seg_pct
        else:
            seg_rent = rate * lease.rent_area / Decimal(12) * seg_pct
        rent += seg_rent
        free += seg_rent * _free_rent_factor(lease.free_rent_periods, seg_start, seg_end, for_base_rent=True)
    return rent, -free


def project_lease_cash_flows(
    lease: LeaseInput,
    analysis: AnalysisPeriod,
    cpi_assumption: Decimal = Decimal("0.025"),
    scenario_label: str = "in_place",
    scenario_weight: Decimal = Decimal(1),
    cpi_schedule: tuple[Decimal, ...] = (),
) -> list[MonthlySlice]:
    """
    Project month-by-month base rent for a single lease over the analysis period.

    Returns one MonthlySlice per month in which the lease is active (or partially active).
    Expense recoveries are initialized to zero — filled in later by the expense engine.
    TI/LC costs are initialized to zero — set by the caller for speculative leases.
    """
    slices: list[MonthlySlice] = []

    for month_idx, period_start, period_end in iter_months(analysis.start_date, analysis.num_months):
        # Is the lease active this month at all?
        if period_start > lease.end_date or period_end < lease.start_date:
            continue

        # Day-count proration for partial first/last months
        pct = proration_factor(period_start, period_end, lease.start_date, lease.end_date)
        if pct == Decimal(0):
            continue

        # Rent rate for this period
        rent_rate = _current_rent(lease, period_start, cpi_assumption, cpi_schedule, analysis.start_date)

        # Monthly rent = annual $/SF * area / 12 * proration
        # For monthly-basis leases (multifamily, storage): base_rent_per_unit is already $/month
        if lease.rent_payment_frequency == "monthly":
            # $/unit/month — area is in units, so total monthly = rate * area * proration
            monthly_rent = rent_rate * lease.rent_area * pct
        else:
            # $/SF/year commercial — convert to monthly
            monthly_rent = rent_rate * lease.rent_area / Decimal(12) * pct

        # Free rent on base rent
        free_base_factor = _free_rent_factor(
            lease.free_rent_periods,
            period_start,
            period_end,
            for_base_rent=True,
            lease_start=lease.start_date,
            lease_end=lease.end_date,
        )
        free_rent_adj = -monthly_rent * free_base_factor

        if lease.prorate_rent_steps and lease.escalation_type == "fixed_step":
            # Mid-month steps: split the month at step dates and prorate rent and free rent by days
            monthly_rent, free_rent_adj = _prorated_step_rent(lease, period_start, period_end)

        effective = monthly_rent + free_rent_adj

        # Percentage rent (retail): overage above the natural/artificial breakpoint
        monthly_pct_rent = Decimal(0)
        if (
            lease.pct_rent_breakpoint is not None
            and lease.pct_rent_rate is not None
            and lease.projected_annual_sales_per_sf is not None
        ):
            annual_sales = lease.projected_annual_sales_per_sf * lease.area
            overage = max(Decimal(0), annual_sales - lease.pct_rent_breakpoint)
            monthly_pct_rent = overage * lease.pct_rent_rate / Decimal(12) * pct

        slices.append(MonthlySlice(
            month_index=month_idx,
            period_start=period_start,
            period_end=period_end,
            suite_id=lease.suite_id,
            lease_id=lease.lease_id,
            tenant_name=lease.tenant_name,
            base_rent=monthly_rent,
            free_rent_adjustment=free_rent_adj,
            effective_rent=effective,
            expense_recovery=Decimal(0),  # filled by expense_engine
            percentage_rent=monthly_pct_rent,
            ti_cost=Decimal(0),
            lc_cost=Decimal(0),
            is_vacant=False,
            scenario_label=scenario_label,
            scenario_weight=scenario_weight,
            month_fraction=pct,
        ))

    return slices


def make_vacant_slices(
    suite_id: str,
    start_date: date,
    end_date: date,
    analysis: AnalysisPeriod,
    scenario_label: str = "vacant",
    scenario_weight: Decimal = Decimal(1),
) -> list[MonthlySlice]:
    """Generate vacancy (zero-rent) slices for a date range."""
    slices: list[MonthlySlice] = []
    if start_date > analysis.end_date or end_date < analysis.start_date:
        return slices

    for month_idx, period_start, period_end in iter_months(analysis.start_date, analysis.num_months):
        if period_start > end_date or period_end < start_date:
            continue
        pct = proration_factor(period_start, period_end, start_date, end_date)
        if pct == Decimal(0):
            continue

        slices.append(MonthlySlice(
            month_index=month_idx,
            period_start=period_start,
            period_end=period_end,
            suite_id=suite_id,
            lease_id=f"vacant_{suite_id}_{month_idx}",
            tenant_name=None,
            base_rent=Decimal(0),
            free_rent_adjustment=Decimal(0),
            effective_rent=Decimal(0),
            expense_recovery=Decimal(0),
            percentage_rent=Decimal(0),
            ti_cost=Decimal(0),
            lc_cost=Decimal(0),
            is_vacant=True,
            scenario_label=scenario_label,
            scenario_weight=scenario_weight,
            month_fraction=pct,
        ))
    return slices
