"""
Expense recovery calculation engine.

Computes the monthly expense recovery amount for each lease based on its
recovery type (NNN, FSG, Modified Gross, Base Year Stop) and attaches it
to the MonthlySlice.expense_recovery field.

Supports:
  - Pro-rata share (explicit override or computed from area / total_area)
  - Expense gross-up for variable expenses
  - Per-lease per-category overrides (caps, floors, admin fees, custom stops)
  - Free rent on recoveries (separate from free rent on base rent)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.engine.growth import expense_at_year
from src.engine.types import (
    AnalysisPeriod,
    ExpenseInput,
    FiscalYear,
    LeaseInput,
    MonthlySlice,
)


def _fiscal_year_number(analysis: AnalysisPeriod, period_start: date) -> int:
    """Return 1-based fiscal year number for a given month start."""
    for fy in analysis.fiscal_years:
        if fy.start_date <= period_start <= fy.end_date:
            return fy.year_number
    return len(analysis.fiscal_years)


def _annual_expense(exp: ExpenseInput, year_number: int) -> Decimal:
    """Expense amount for a given analysis year (1-based), before gross-up."""
    return expense_at_year(exp.base_amount, exp.growth_rate, year_number)


def _grossed_up_expense(
    annual_exp: Decimal,
    exp: ExpenseInput,
    actual_occupancy: Decimal,
) -> Decimal:
    """
    Gross up variable expenses to reference occupancy level.
    Prevents under-recovery when building is partially vacant.
    Formula: grossed_up = actual * (reference_occ / actual_occ)
    """
    if not exp.is_gross_up_eligible or exp.gross_up_vacancy_pct is None:
        return annual_exp
    if actual_occupancy <= Decimal(0):
        return annual_exp
    ref = exp.gross_up_vacancy_pct
    if actual_occupancy >= ref:
        return annual_exp
    return annual_exp * (ref / actual_occupancy)


def _is_free_rent_for_recoveries(lease: LeaseInput, period_start: date, period_end: date) -> bool:
    """
    Return True if any free-rent period overlapping this month applies to recoveries.

    A month is considered "free" if ANY overlap exists between the free rent
    period and the month. This matches the binary monthly recovery
    monthly recovery abatement.
    """
    for frp in lease.free_rent_periods:
        if frp.applies_to_recoveries:
            # Check for any overlap: free rent starts before month ends AND ends after month starts
            if frp.start_date <= period_end and frp.end_date >= period_start:
                return True
    return False


def _recovery_for_expense(
    lease: LeaseInput,
    exp: ExpenseInput,
    annual_expense_grossed: Decimal,
    total_property_area: Decimal,
    year_number: int,
    analysis_start_year: int,
) -> Decimal:
    """
    Compute the annual recovery amount for one expense line item for one lease.
    Applies the lease's recovery_type (or per-category override).
    """
    # Check for per-category override
    override = next(
        (o for o in lease.recovery_overrides if o.expense_category == exp.category),
        None,
    )
    recovery_type = override.recovery_type if override else lease.recovery_type

    if recovery_type in ("full_service_gross", "none"):
        return Decimal(0)

    # Compute pro-rata share
    pro_rata = lease.pro_rata_share
    if pro_rata is None:
        if total_property_area > 0:
            pro_rata = lease.area / total_property_area
        else:
            pro_rata = Decimal(0)

    if recovery_type == "nnn":
        recovery = annual_expense_grossed * pro_rata

    elif recovery_type == "base_year_stop":
        # Tenant pays pro-rata share of expense above the stop.
        # Precedence:
        # 1) per-category override stop
        # 2) lease-level stop
        # 3) lease base_year-derived stop
        # 4) expense base amount (analysis year 1)
        if override and override.base_year_stop_amount is not None:
            base_stop = override.base_year_stop_amount
        elif lease.base_year_stop_amount is not None:
            base_stop = lease.base_year_stop_amount
        elif lease.base_year is not None:
            year_offset = lease.base_year - analysis_start_year
            growth_factor = (Decimal(1) + exp.growth_rate) ** abs(year_offset)
            if year_offset >= 0:
                base_stop = exp.base_amount * growth_factor
            else:
                base_stop = exp.base_amount if growth_factor == Decimal(0) else exp.base_amount / growth_factor
        else:
            base_stop = exp.base_amount
        excess = max(Decimal(0), annual_expense_grossed - base_stop)
        recovery = excess * pro_rata

    elif recovery_type == "modified_gross":
        # Tenant pays pro-rata share of expense/SF above stop/SF
        stop_per_sf = lease.expense_stop_per_sf or Decimal(0)
        if override and override.floor_per_sf_annual is not None:
            stop_per_sf = override.floor_per_sf_annual
        expense_per_sf = annual_expense_grossed / total_property_area if total_property_area > 0 else Decimal(0)
        excess_per_sf = max(Decimal(0), expense_per_sf - stop_per_sf)
        recovery = excess_per_sf * lease.area

    else:
        return Decimal(0)

    # Apply per-category cap, floor, admin fee overrides
    if override:
        if override.cap_per_sf_annual is not None:
            cap = override.cap_per_sf_annual * lease.area
            recovery = min(recovery, cap)
        if override.floor_per_sf_annual is not None and recovery_type != "modified_gross":
            floor_ = override.floor_per_sf_annual * lease.area
            recovery = max(recovery, floor_)
        if override.admin_fee_pct is not None:
            recovery = recovery * (Decimal(1) + override.admin_fee_pct)

    return recovery


def attach_expense_recoveries(
    lease_slices: list[MonthlySlice],
    lease: LeaseInput,
    expenses: list[ExpenseInput],
    analysis: AnalysisPeriod,
    total_property_area: Decimal,
    occupancy_by_month: list[Decimal],
) -> None:
    """
    Compute and attach expense_recovery to each MonthlySlice in-place.

    occupancy_by_month: list of Decimal occupancy rates (0..1) indexed by month_index.
    This is needed for expense gross-up calculations.
    """
    for s in lease_slices:
        if s.is_vacant:
            continue

        # Skip recoveries during free-rent-on-recoveries periods
        if _is_free_rent_for_recoveries(lease, s.period_start, s.period_end):
            continue

        year_number = _fiscal_year_number(analysis, s.period_start)
        actual_occupancy = occupancy_by_month[s.month_index] if s.month_index < len(occupancy_by_month) else Decimal("0.95")

        monthly_recovery = Decimal(0)
        for exp in expenses:
            if not exp.is_recoverable:
                continue
            if exp.is_pct_of_egi:
                continue  # management fees handled in waterfall

            annual_exp = _annual_expense(exp, year_number)
            annual_exp_grossed = _grossed_up_expense(annual_exp, exp, actual_occupancy)

            annual_recovery = _recovery_for_expense(
                lease,
                exp,
                annual_exp_grossed,
                total_property_area,
                year_number,
                analysis.start_date.year,
            )
            # Prorate monthly (annual / 12), adjusted by the slice's proration factor
            # The slice's effective_rent already has proration embedded from lease_projector,
            # but recovery is based on actual lease area regardless of partial months.
            # Use proration factor embedded in the slice via ratio of base_rent to max monthly.
            monthly_recovery += annual_recovery / Decimal(12)

        # Scale by proration factor (partial months) — use same factor as base rent
        # Approximation: if base_rent has proration baked in, scale recoveries proportionally
        if s.base_rent > Decimal(0):
            # Derive proration from base rent
            pass  # monthly_recovery already prorated by dividing annual/12
        # For partial first/last months, we should also prorate recoveries
        # Recovery proration: apply same day-count factor
        # Since we don't store proration separately, we'll scale by checking if
        # period overlaps partially with lease start/end
        from src.engine.date_utils import proration_factor as pf
        pct = pf(s.period_start, s.period_end, lease.start_date, lease.end_date)
        monthly_recovery = monthly_recovery * pct

        s.expense_recovery = monthly_recovery
