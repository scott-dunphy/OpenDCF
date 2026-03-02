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

from src.engine.date_utils import proration_factor
from src.engine.growth import expense_at_year
from src.engine.types import (
    AnalysisPeriod,
    ExpenseInput,
    FiscalYear,
    LeaseInput,
    MonthlySlice,
    RecoveryAuditEntry,
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
    apply_stabilized_gross_up: bool = True,
    stabilized_occupancy_pct: Decimal | None = None,
) -> Decimal:
    """
    Gross up variable expenses to reference occupancy level.
    Prevents under-recovery when building is partially vacant.
    Formula: grossed_up = actual * (reference_occ / actual_occ)
    """
    if not apply_stabilized_gross_up:
        return annual_exp
    if not exp.is_gross_up_eligible:
        return annual_exp
    if actual_occupancy <= Decimal(0):
        return annual_exp
    ref = stabilized_occupancy_pct if stabilized_occupancy_pct is not None else exp.gross_up_vacancy_pct
    if ref is None:
        return annual_exp
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


def _effective_recovery_type(lease: LeaseInput, expense_category: str) -> str:
    """Return effective recovery type for a category (override first, then lease default)."""
    override = next(
        (o for o in lease.recovery_overrides if o.expense_category == expense_category),
        None,
    )
    return override.recovery_type if override else lease.recovery_type


def _recovery_for_expense(
    lease: LeaseInput,
    exp: ExpenseInput,
    annual_expense_grossed: Decimal,
    total_property_area: Decimal,
    year_number: int,
    analysis_start_year: int,
    modified_gross_pool_annual: Decimal | None = None,
    modified_gross_pool_share: Decimal | None = None,
) -> tuple[Decimal, dict[str, Decimal | str | None]]:
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
        return Decimal(0), {
            "recovery_type": recovery_type,
            "pro_rata_share_pct": Decimal(0),
            "base_year_stop_amount": None,
            "expense_stop_per_sf": None,
            "cap_per_sf_annual": None,
            "floor_per_sf_annual": None,
            "admin_fee_pct": None,
        }

    # Compute pro-rata share
    pro_rata = lease.pro_rata_share
    if pro_rata is None:
        if total_property_area > 0:
            pro_rata = lease.area / total_property_area
        else:
            pro_rata = Decimal(0)

    base_stop_used: Decimal | None = None
    expense_stop_per_sf: Decimal | None = None
    cap_per_sf_annual: Decimal | None = override.cap_per_sf_annual if override else None
    floor_per_sf_annual: Decimal | None = override.floor_per_sf_annual if override else None
    admin_fee_pct: Decimal | None = override.admin_fee_pct if override else None

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
        base_stop_used = base_stop
        excess = max(Decimal(0), annual_expense_grossed - base_stop)
        recovery = excess * pro_rata

    elif recovery_type == "modified_gross":
        # Tenant pays expense/SF above stop/SF.
        # Apply stop at pooled modified-gross expense level (industry convention),
        # then allocate pooled excess to each category by that category's pool share.
        stop_per_sf = lease.expense_stop_per_sf or Decimal(0)
        if override and override.floor_per_sf_annual is not None:
            stop_per_sf = override.floor_per_sf_annual
        expense_stop_per_sf = stop_per_sf
        if (
            modified_gross_pool_annual is not None
            and modified_gross_pool_annual > Decimal(0)
            and modified_gross_pool_share is not None
            and override is None
        ):
            pool_per_sf = (
                modified_gross_pool_annual / total_property_area
                if total_property_area > 0
                else Decimal(0)
            )
            excess_per_sf_total = max(Decimal(0), pool_per_sf - stop_per_sf)
            total_recovery = excess_per_sf_total * lease.area
            recovery = total_recovery * modified_gross_pool_share
        else:
            expense_per_sf = annual_expense_grossed / total_property_area if total_property_area > 0 else Decimal(0)
            excess_per_sf = max(Decimal(0), expense_per_sf - stop_per_sf)
            recovery = excess_per_sf * lease.area

    else:
        return Decimal(0), {
            "recovery_type": recovery_type,
            "pro_rata_share_pct": pro_rata,
            "base_year_stop_amount": base_stop_used,
            "expense_stop_per_sf": expense_stop_per_sf,
            "cap_per_sf_annual": cap_per_sf_annual,
            "floor_per_sf_annual": floor_per_sf_annual,
            "admin_fee_pct": admin_fee_pct,
        }

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

    return recovery, {
        "recovery_type": recovery_type,
        "pro_rata_share_pct": pro_rata,
        "base_year_stop_amount": base_stop_used,
        "expense_stop_per_sf": expense_stop_per_sf,
        "cap_per_sf_annual": cap_per_sf_annual,
        "floor_per_sf_annual": floor_per_sf_annual,
        "admin_fee_pct": admin_fee_pct,
    }


def attach_expense_recoveries(
    lease_slices: list[MonthlySlice],
    lease: LeaseInput,
    expenses: list[ExpenseInput],
    analysis: AnalysisPeriod,
    total_property_area: Decimal,
    occupancy_by_month: list[Decimal],
    apply_stabilized_gross_up: bool = True,
    stabilized_occupancy_pct: Decimal | None = None,
    recovery_audit: list[RecoveryAuditEntry] | None = None,
) -> None:
    """
    Compute and attach expense_recovery to each MonthlySlice in-place.

    occupancy_by_month: list of Decimal occupancy rates (0..1) indexed by month_index.
    This is needed for expense gross-up calculations.
    """
    for s in lease_slices:
        if s.is_vacant:
            continue

        is_recovery_free_rent = _is_free_rent_for_recoveries(lease, s.period_start, s.period_end)

        year_number = _fiscal_year_number(analysis, s.period_start)
        actual_occupancy = occupancy_by_month[s.month_index] if s.month_index < len(occupancy_by_month) else Decimal("0.95")

        exp_calc_inputs: list[tuple[ExpenseInput, Decimal, Decimal, str]] = []
        modified_gross_pool_annual = Decimal(0)
        for exp in expenses:
            if not exp.is_recoverable:
                continue
            if exp.is_pct_of_egi:
                continue  # management fees handled in waterfall
            annual_exp = _annual_expense(exp, year_number)
            annual_exp_grossed = _grossed_up_expense(
                annual_exp,
                exp,
                actual_occupancy,
                apply_stabilized_gross_up=apply_stabilized_gross_up,
                stabilized_occupancy_pct=stabilized_occupancy_pct,
            )
            eff_recovery_type = _effective_recovery_type(lease, exp.category)
            exp_calc_inputs.append((exp, annual_exp, annual_exp_grossed, eff_recovery_type))
            if eff_recovery_type == "modified_gross":
                modified_gross_pool_annual += annual_exp_grossed

        monthly_recovery = Decimal(0)
        for exp, annual_exp, annual_exp_grossed, eff_recovery_type in exp_calc_inputs:
            gross_up_factor = (
                (annual_exp_grossed / annual_exp) if annual_exp > Decimal(0) else Decimal(1)
            )
            gross_up_reference = stabilized_occupancy_pct if stabilized_occupancy_pct is not None else exp.gross_up_vacancy_pct
            mg_share: Decimal | None = None
            if eff_recovery_type == "modified_gross" and modified_gross_pool_annual > Decimal(0):
                mg_share = annual_exp_grossed / modified_gross_pool_annual

            annual_recovery, calc_meta = _recovery_for_expense(
                lease,
                exp,
                annual_exp_grossed,
                total_property_area,
                year_number,
                analysis.start_date.year,
                modified_gross_pool_annual=(
                    modified_gross_pool_annual if eff_recovery_type == "modified_gross" else None
                ),
                modified_gross_pool_share=mg_share,
            )
            monthly_recovery_before_proration = annual_recovery / Decimal(12)

            # For partial first/last months, prorate recoveries by lease day-count overlap.
            proration = proration_factor(s.period_start, s.period_end, lease.start_date, lease.end_date)
            monthly_recovery_prorated = monthly_recovery_before_proration * proration
            monthly_recovery_final = Decimal(0) if is_recovery_free_rent else monthly_recovery_prorated

            monthly_recovery += monthly_recovery_final
            s.expense_recovery_detail[exp.category] = (
                s.expense_recovery_detail.get(exp.category, Decimal(0)) + monthly_recovery_final
            )

            if recovery_audit is not None:
                recovery_audit.append(
                    RecoveryAuditEntry(
                        year=year_number,
                        period_start=s.period_start,
                        period_end=s.period_end,
                        suite_id=s.suite_id,
                        lease_id=s.lease_id,
                        tenant_name=s.tenant_name,
                        expense_category=exp.category,
                        recovery_type=str(calc_meta["recovery_type"]),
                        annual_expense_before_gross_up=annual_exp,
                        annual_expense_after_gross_up=annual_exp_grossed,
                        actual_occupancy_pct=actual_occupancy,
                        gross_up_reference_occupancy_pct=gross_up_reference,
                        gross_up_factor=gross_up_factor,
                        pro_rata_share_pct=calc_meta["pro_rata_share_pct"],  # type: ignore[arg-type]
                        base_year_stop_amount=calc_meta["base_year_stop_amount"],  # type: ignore[arg-type]
                        expense_stop_per_sf=calc_meta["expense_stop_per_sf"],  # type: ignore[arg-type]
                        cap_per_sf_annual=calc_meta["cap_per_sf_annual"],  # type: ignore[arg-type]
                        floor_per_sf_annual=calc_meta["floor_per_sf_annual"],  # type: ignore[arg-type]
                        admin_fee_pct=calc_meta["admin_fee_pct"],  # type: ignore[arg-type]
                        annual_recovery_before_proration=annual_recovery,
                        monthly_recovery_before_free_rent=monthly_recovery_prorated,
                        proration_factor=proration,
                        is_recovery_free_rent_abatement=is_recovery_free_rent,
                        monthly_recovery_after_free_rent=monthly_recovery_final,
                        scenario_weight=s.scenario_weight,
                        weighted_monthly_recovery=monthly_recovery_final * s.scenario_weight,
                    )
                )

        s.expense_recovery = monthly_recovery
