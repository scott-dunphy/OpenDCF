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

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from src.engine.date_utils import add_months, proration_factor
from src.engine.growth import rate_for_year, scheduled_amount_at_year
from src.engine.recovery_pools import PoolShare
from src.engine.types import (
    AnalysisPeriod,
    ExpenseInput,
    FeeShare,
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
    return scheduled_amount_at_year(
        exp.base_amount, exp.growth_rate, year_number, exp.growth_schedule, exp.amount_schedule
    )


def _year_number_any(analysis: AnalysisPeriod, d: date) -> int:
    """Analysis year containing d, counting whole years past either end of the analysis."""
    first, last = analysis.fiscal_years[0], analysis.fiscal_years[-1]
    if d < first.start_date:
        return 1 - ((first.start_date.year - d.year) * 12 + first.start_date.month - d.month + 11) // 12
    if d > last.end_date:
        return last.year_number + ((d.year - last.end_date.year) * 12 + d.month - last.end_date.month + 11) // 12
    return _fiscal_year_number(analysis, d)


def _calendar_year_expense(exp: ExpenseInput, analysis: AnalysisPeriod, year: int) -> Decimal:
    """
    Expense for calendar year `year` when analysis years do not run January-December:
    each month at the annual amount of the analysis year it falls in (published DCF software calendar
    reimbursement with fiscal inflation).
    """
    total = Decimal(0)
    for month in range(1, 13):
        total += _expense_any_year(exp, _year_number_any(analysis, date(year, month, 1)))
    return total / Decimal(12)


def _expense_any_year(exp: ExpenseInput, year_number: int) -> Decimal:
    """Expense in an analysis year; years before Year 1 deflate at the first annual growth rate."""
    if year_number >= 1:
        return _annual_expense(exp, year_number)
    rate = rate_for_year(exp.growth_rate, exp.growth_schedule, 2)
    return _annual_expense(exp, 1) / (Decimal(1) + rate) ** (1 - year_number)


def occupancy_adjusted_expense(annual_exp: Decimal, exp: ExpenseInput, occupancy: Decimal) -> Decimal:
    """
    Expense actually incurred at an occupancy level.

    With a variable share v > 0 the entered amount is at 100% occupancy:
    amount x (1 - v + v x occupancy). With v = 0 the amount is used as entered.
    """
    if exp.variable_pct <= Decimal(0):
        return annual_exp
    occ = max(Decimal(0), min(Decimal(1), occupancy))
    return annual_exp * (Decimal(1) - exp.variable_pct + exp.variable_pct * occ)


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
    With a fixed/variable split, `annual_exp` is the amount stated at 100% occupancy
    and only the variable share is evaluated at max(actual, reference) occupancy.
    """
    if exp.variable_pct > Decimal(0):
        # Fixed/variable split: only the variable share grosses up to the reference occupancy
        actual = occupancy_adjusted_expense(annual_exp, exp, actual_occupancy)
        ref = stabilized_occupancy_pct if stabilized_occupancy_pct is not None else exp.gross_up_vacancy_pct
        if not apply_stabilized_gross_up or not exp.is_gross_up_eligible or ref is None:
            return actual
        return occupancy_adjusted_expense(annual_exp, exp, max(actual_occupancy, ref))
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


def _has_stop_reference(lease: LeaseInput, expense_category: str) -> bool:
    """Whether a base-year stop line has a stop to measure against: a base-year date, or an explicit
    stop amount on the lease or on the category's override."""
    if lease.base_year is not None or lease.base_year_stop_amount is not None:
        return True
    override = next((o for o in lease.recovery_overrides if o.expense_category == expense_category), None)
    return override is not None and override.base_year_stop_amount is not None


def _leaves_pool(lease: LeaseInput, override: ExpenseRecoveryOverride | None) -> bool:
    """Whether a per-category override takes its line out of the lease's pooled stop (modified gross
    or base year): it sets its own stop or a different recovery type. An item that only adds an
    admin fee, cap or floor stays in the pool and applies its terms to its allocated share."""
    if override is None:
        return False
    if override.recovery_type != lease.recovery_type:
        return True
    if override.recovery_type == "base_year_stop":
        return override.base_year_stop_amount is not None
    # Older models entered a modified gross category's stop as its floor
    return override.recovery_type == "modified_gross" and (
        override.expense_stop_per_sf is not None or override.floor_per_sf_annual is not None)


def _recovery_for_expense(
    lease: LeaseInput,
    exp: ExpenseInput,
    annual_expense_grossed: Decimal,
    total_property_area: Decimal,
    year_number: int,
    analysis_start_year: int,
    modified_gross_pool_annual: Decimal | None = None,
    modified_gross_pool_share: Decimal | None = None,
    base_year_expense: Callable[[ExpenseInput, int], Decimal | None] | None = None,
) -> tuple[Decimal, dict[str, Decimal | str | None]]:
    """
    Compute the annual recovery amount for one expense line item for one lease.
    Applies the lease's recovery_type (or per-category override).
    base_year_expense(exp, year_number): the expense a base year in the analysis incurred, if known.
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
            incurred = base_year_expense(exp, year_offset + 1) if base_year_expense else None
            if incurred is not None:
                base_stop = incurred
            elif year_offset >= 0:
                base_stop = scheduled_amount_at_year(
                    exp.base_amount, exp.growth_rate, year_offset + 1,
                    exp.growth_schedule, exp.amount_schedule,
                )
            else:
                # Base years before the analysis deflate at the Year 1 rate
                year1_rate = rate_for_year(exp.growth_rate, exp.growth_schedule, 1)
                base_stop = _annual_expense(exp, 1) / (Decimal(1) + year1_rate) ** abs(year_offset)
        else:
            base_stop = _annual_expense(exp, 1)
        base_stop_used = base_stop
        excess = max(Decimal(0), annual_expense_grossed - base_stop)
        recovery = excess * pro_rata

    elif recovery_type == "modified_gross":
        # Tenant pays expense/SF above stop/SF.
        # Apply stop at pooled modified-gross expense level (industry convention),
        # then allocate pooled excess to each category by that category's pool share.
        stop_per_sf = lease.expense_stop_per_sf or Decimal(0)
        if override and override.expense_stop_per_sf is not None:
            stop_per_sf = override.expense_stop_per_sf
        elif override and override.floor_per_sf_annual is not None:
            # Older models entered a modified gross category's stop as its floor
            stop_per_sf = override.floor_per_sf_annual
        expense_stop_per_sf = stop_per_sf
        # The excess $/SF is billed on the tenant's area, or on its typed share of the denominator
        share_area = lease.area if lease.pro_rata_share is None else total_property_area * lease.pro_rata_share
        if (
            modified_gross_pool_annual is not None
            and modified_gross_pool_annual > Decimal(0)
            and modified_gross_pool_share is not None
        ):
            pool_per_sf = (
                modified_gross_pool_annual / total_property_area
                if total_property_area > 0
                else Decimal(0)
            )
            excess_per_sf_total = max(Decimal(0), pool_per_sf - stop_per_sf)
            total_recovery = excess_per_sf_total * share_area
            recovery = total_recovery * modified_gross_pool_share
        else:
            expense_per_sf = annual_expense_grossed / total_property_area if total_property_area > 0 else Decimal(0)
            excess_per_sf = max(Decimal(0), expense_per_sf - stop_per_sf)
            recovery = excess_per_sf * share_area

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

    # Per-category admin fee, then floor, then cap (published DCF software order: the minimum, then
    # the maximum, so the cap wins; a cap group's cap also includes the admin fee)
    if override:
        if override.admin_fee_pct is not None:
            recovery = recovery * (Decimal(1) + override.admin_fee_pct)
        if override.floor_per_sf_annual is not None and recovery_type != "modified_gross":
            floor_ = override.floor_per_sf_annual * lease.area
            recovery = max(recovery, floor_)
        if override.cap_per_sf_annual is not None and not override.cap_group:
            cap = override.cap_per_sf_annual * lease.area
            recovery = min(recovery, cap)

    return recovery, {
        "recovery_type": recovery_type,
        "pro_rata_share_pct": pro_rata,
        "base_year_stop_amount": base_stop_used,
        "expense_stop_per_sf": expense_stop_per_sf,
        "cap_per_sf_annual": cap_per_sf_annual,
        "floor_per_sf_annual": floor_per_sf_annual,
        "admin_fee_pct": admin_fee_pct,
    }


def _pool_base_year_stops(computed, lease: LeaseInput) -> None:
    """
    Apply a base-year stop to pooled expenses: the tenant reimburses its share
    of the pool's excess over the pooled stop, allocated to each line by its size. A lease-level
    `base_year_stop_amount` is the pooled stop; otherwise the lines' own stops are summed.
    A line whose override sets its own stop or type is measured alone; an override that only adds
    a cap, floor or admin fee keeps its line in the pool and applies those to the line's share.
    """
    overrides = {o.expense_category: o for o in lease.recovery_overrides}
    rows = [i for i, (exp, _, _, _, meta) in enumerate(computed)
            if meta["recovery_type"] == "base_year_stop" and not _leaves_pool(lease, overrides.get(exp.category))]
    if len(rows) < 2:
        return
    grand_total = sum((computed[i][2] for i in rows), Decimal(0))
    if grand_total <= 0:
        return
    # Lines in recovery pools with different denominators carry different shares: pool the stop
    # among lines that share one (a lease-level stop is split between them by size)
    by_share: dict[Decimal, list[int]] = {}
    for i in rows:
        by_share.setdefault(computed[i][4]["pro_rata_share_pct"], []).append(i)
    for pro_rata, group in by_share.items():
        total = sum((computed[i][2] for i in group), Decimal(0))
        if total <= 0:
            continue
        stop = (lease.base_year_stop_amount * total / grand_total if lease.base_year_stop_amount is not None
                else sum((computed[i][4]["base_year_stop_amount"] for i in group), Decimal(0)))
        excess = max(Decimal(0), total - stop) * pro_rata
        for i in group:
            exp, annual_exp, grossed, _, meta = computed[i]
            share = grossed / total
            recovery = excess * share
            override = overrides.get(exp.category)
            if override:  # its terms, as _recovery_for_expense applies them to a line measured alone
                # Same order as _recovery_for_expense: admin fee, then floor, then cap (the cap wins)
                if override.admin_fee_pct is not None:
                    recovery = recovery * (Decimal(1) + override.admin_fee_pct)
                if override.floor_per_sf_annual is not None:
                    recovery = max(recovery, override.floor_per_sf_annual * lease.area)
                if override.cap_per_sf_annual is not None and not override.cap_group:
                    recovery = min(recovery, override.cap_per_sf_annual * lease.area)
            computed[i] = (exp, annual_exp, grossed, recovery, {**meta, "base_year_stop_amount": stop * share})


def _cap_groups(lease: LeaseInput) -> dict[str, tuple[set[str], Decimal | None, Decimal | None]]:
    """Cap group -> (member categories, cap $/SF/yr, max annual growth)."""
    groups: dict[str, tuple[set[str], Decimal | None, Decimal | None]] = {}
    for o in lease.recovery_overrides:
        if not o.cap_group:
            continue
        members, cap, growth = groups.get(o.cap_group, (set(), None, None))
        members.add(o.expense_category)
        groups[o.cap_group] = (
            members,
            cap if cap is not None else o.cap_per_sf_annual,
            growth if growth is not None else o.cap_growth_pct,
        )
    return groups


def _apply_group_caps(computed, lease, group_caps, recovery_year, base_recovery_year, recovery_in, expenses,
                      fee_shares: dict[str, Decimal], fee_by_year: dict[str, dict[int, Decimal]] | None,
                      share_now=None, share_in=None):
    """
    Cap each group's combined annual recovery at cap $/SF x area, and limit its growth from the cap
    start year (the lease start; an exercised option keeps the original); members are scaled down
    pro rata.

    Growth cap of a group with base-year-stop or modified gross members: the cap limits the
    tenant's share of the group's expenses (`share_now(computed[i])`, `share_in(row, year)`) to its cap
    start year level grown at the cap rate, and each member's stop comes off its capped share.
    A group of net members caps the recovery itself, which is the same thing without a stop.

    % of EGI lines in a group: under a $/SF cap they get the room the other members leave
    (returned by cap group); under a growth cap each counts at its share (`fee_shares`) x the year's
    fee from `fee_by_year` (known after a first pass of the waterfall) and is scaled with the others
    (returned as a factor by category). A cap start year before the analysis has no fee: it is the
    first analysis year's fee moved with the group's other expenses.
    """
    fee_caps: dict[str, Decimal] = {}
    fee_factors: dict[str, Decimal] = {}
    fee_categories = {e.category for e in expenses if e.is_pct_of_egi}
    for group, (members, cap_psf, growth) in group_caps.items():
        rows = [i for i, row in enumerate(computed) if row[0].category in members]
        total = sum((computed[i][3] for i in rows), Decimal(0))
        fee_in_growth_cap = growth is not None and bool(members & fee_categories) and fee_by_year is not None
        growth_applies = growth is not None and recovery_year > base_recovery_year
        expense_rows = [i for i in rows if not computed[i][0].is_pct_of_egi]
        group_fees = sorted(members & fee_shares.keys())

        def fee_in(category: str, year: int, measure) -> Decimal:
            by_year = fee_by_year.get(category, {})
            if year in by_year:
                return by_year[year]
            first = min(by_year, default=None)
            if first is None:
                return Decimal(0)
            then = sum((measure(i, year) for i in expense_rows), Decimal(0))
            at_first = sum((measure(i, first) for i in expense_rows), Decimal(0))
            return by_year[first] * then / at_first if at_first > 0 else Decimal(0)

        def fee_now() -> Decimal:
            return sum((fee_shares[c] * fee_by_year.get(c, {}).get(recovery_year, Decimal(0)) * fee_factors.get(c, 1)
                        for c in group_fees), Decimal(0))

        def fee_base(measure) -> Decimal:
            return sum((fee_shares[c] * fee_in(c, base_recovery_year, measure) for c in group_fees), Decimal(0))

        with_stop = share_in is not None and any(
            computed[i][4]["recovery_type"] in ("base_year_stop", "modified_gross") for i in rows)
        if growth_applies and with_stop:
            def base_share(i: int, year: int) -> Decimal:
                return share_in(computed[i], year)

            def share_at(i: int, year: int) -> Decimal:
                if computed[i][0].is_pct_of_egi:  # a base-year lease's fee row
                    return computed[i][4]["pro_rata_share_pct"] * fee_in(computed[i][0].category, year, base_share)
                return base_share(i, year)

            now = sum((share_now(computed[i]) for i in rows), Decimal(0))
            base = sum((share_at(i, base_recovery_year) for i in rows), Decimal(0))
            if fee_in_growth_cap:
                now += fee_now()
                base += fee_base(base_share)
            allowed = base * (Decimal(1) + growth) ** (recovery_year - base_recovery_year)
            if now > allowed:
                factor = allowed / now
                for i in rows:
                    exp, annual_exp, grossed, recovery, meta = computed[i]
                    fee = Decimal(1) + (meta.get("admin_fee_pct") or Decimal(0))
                    cut = (Decimal(1) - factor) * share_now(computed[i]) * fee
                    computed[i] = (exp, annual_exp, grossed, max(Decimal(0), recovery - cut), meta)
                if fee_in_growth_cap:
                    fee_factors.update({c: factor for c in group_fees})
            total = sum((computed[i][3] for i in rows), Decimal(0))
            if fee_in_growth_cap:
                total += fee_now()
            if cap_psf is not None and total > cap_psf * lease.area:
                factor = cap_psf * lease.area / total
                for i in rows:
                    exp, annual_exp, grossed, recovery, meta = computed[i]
                    computed[i] = (exp, annual_exp, grossed, recovery * factor, meta)
                if fee_in_growth_cap:
                    fee_factors.update({c: fee_factors.get(c, Decimal(1)) * factor for c in group_fees})
                total = cap_psf * lease.area
            if cap_psf is not None and members & fee_categories and not fee_in_growth_cap:
                fee_caps[group] = max(Decimal(0), cap_psf * lease.area - total)
            continue

        if fee_in_growth_cap:
            total += fee_now()
        caps = []
        if cap_psf is not None:
            caps.append(cap_psf * lease.area)
        if growth_applies:
            base = sum((recovery_in(computed[i][0], base_recovery_year) for i in rows), Decimal(0))
            if fee_in_growth_cap:
                base += fee_base(lambda i, y: recovery_in(computed[i][0], y))
            caps.append(base * (Decimal(1) + growth) ** (recovery_year - base_recovery_year))
        if caps and total > min(caps):
            factor = min(caps) / total
            for i in rows:
                exp, annual_exp, grossed, recovery, meta = computed[i]
                computed[i] = (exp, annual_exp, grossed, recovery * factor, meta)
            if fee_in_growth_cap:
                fee_factors.update({c: factor for c in group_fees})
            total = min(caps)
        if cap_psf is not None and members & fee_categories and not fee_in_growth_cap:
            fee_caps[group] = max(Decimal(0), cap_psf * lease.area - total)
    return computed, fee_caps, fee_factors


def recovery_occupancy_context(
    analysis: AnalysisPeriod, occupancy_by_month: list[Decimal]
) -> tuple[dict[int, Decimal], dict[int, list[Decimal]]]:
    """Precompute occupancy groupings shared by every lease on a property."""
    by_year: dict[int, list[Decimal]] = {}
    by_calendar_year: dict[int, list[Decimal]] = {}
    month = analysis.start_date
    for occ in occupancy_by_month[:analysis.num_months]:
        by_year.setdefault(_fiscal_year_number(analysis, month), []).append(occ)
        by_calendar_year.setdefault(month.year, []).append(occ)
        month = add_months(month, 1)
    return ({y: sum(values) / len(values) for y, values in by_year.items()}, by_calendar_year)


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
    calendar_year_recoveries: bool = False,
    fee_by_year: dict[str, dict[int, Decimal]] | None = None,
    occupancy_context: tuple[dict[int, Decimal], dict[int, list[Decimal]]] | None = None,
    pool_shares: dict[str, PoolShare] | None = None,
    pays_into: dict[str, str] | None = None,
) -> None:
    """
    Compute and attach expense_recovery to each MonthlySlice in-place.

    pool_shares: recovery pool terms by expense category (see recovery_pools): the share
    denominator, what excluded tenants already paid, and whether the line is grossed up.

    calendar_year_recoveries: recover each calendar year's expense rather than the analysis
    year's (differs only when the analysis year does not end in December).

    occupancy_by_month: list of Decimal occupancy rates (0..1) indexed by month_index.
    This is needed for expense gross-up calculations.

    fee_by_year: each recoverable % of EGI line's fee by recovery year, by category (from a previous
    pass of the waterfall): for base-year and modified gross leases and growth caps.

    pays_into: expense category -> the deducting pool that excludes this lease's suite (what the
    lease pays toward a % of EGI line comes off that pool's fee).

    % of EGI lines: a net lease's share of each line is put on the slice (FeeShare) for the waterfall
    to solve, as the fee depends on EGI; base-year and modified gross leases recover each line from
    its fee by year like any other expense.
    """
    group_caps = _cap_groups(lease)
    # Average occupancy by analysis year: a base year's stop is the expense it incurred
    year_occupancy, by_calendar_year = occupancy_context or recovery_occupancy_context(
        analysis, occupancy_by_month
    )

    pools = pool_shares or {}

    def denominator(exp: ExpenseInput, key: int) -> Decimal:
        pool = pools.get(exp.category)
        return pool.denominator_by_year.get(key, total_property_area) if pool else total_property_area

    def deduction(exp: ExpenseInput, key: int) -> Decimal:
        """What the pool's excluded tenants pay toward the line: their dollar recoveries and, for a % of
        EGI line, net leases' fee shares (from the waterfall) - the line's
        part of what they pay toward its category."""
        pool = pools.get(exp.category)
        if not pool:
            return Decimal(0)
        paid = pool.deduction_by_year.get(key, {}).get(exp.category, Decimal(0))
        if exp.is_pct_of_egi:
            paid += pool.net_fee_paid_by_year.get(key, {}).get(exp.category, Decimal(0))
            paid *= line_fraction(exp)
        return paid

    def grossed(exp: ExpenseInput, stated: Decimal, occupancy: Decimal, key: int,
                occupancy_key: int | None = None) -> Decimal:
        """The expense grossed up (unless its pool is on occupied area). `occupancy` is the property's;
        a pool with excluded suites grosses up only its included suites' vacancy, at their occupancy in
        `occupancy_key` (default `key`)."""
        pool = pools.get(exp.category)
        if pool and not pool.gross_up:
            return occupancy_adjusted_expense(stated, exp, occupancy)
        reference = stabilized_occupancy_pct if stabilized_occupancy_pct is not None else exp.gross_up_vacancy_pct
        included = (pool.included_occupancy_by_year.get(key if occupancy_key is None else occupancy_key)
                    if pool else None)
        if included is not None and reference is not None:
            # The property's occupancy with the included suites at the reference and the
            # excluded suites as they are
            reference = occupancy + max(Decimal(0), reference - included) * pool.included_area_share
        return _grossed_up_expense(stated, exp, occupancy, apply_stabilized_gross_up=apply_stabilized_gross_up,
                                   stabilized_occupancy_pct=reference)

    def recoverable(exp: ExpenseInput, stated: Decimal, occupancy: Decimal, key: int,
                    occupancy_key: int | None = None) -> Decimal:
        """The expense tenants share: grossed up, less what excluded tenants paid toward it."""
        return max(Decimal(0), grossed(exp, stated, occupancy, key, occupancy_key) - deduction(exp, key))

    def first_year_net(exp: ExpenseInput, stated: Decimal, first_stated: Decimal, occupancy: Decimal,
                       key: int) -> Decimal:
        """A pre-analysis base year in a deducting pool: the first recovery year's pool expense (net
        of what the excluded tenants paid), moved back as the stated expense moves."""
        if first_stated <= 0:
            return stated
        return recoverable(exp, first_stated, occupancy, key) * stated / first_stated

    def base_year_expense(exp: ExpenseInput, year: int) -> Decimal | None:
        pool = pools.get(exp.category)
        if calendar_year_recoveries:
            # The base calendar year's expense, at its average occupancy within the analysis
            calendar_year = analysis.start_date.year + year - 1
            if calendar_year not in by_calendar_year:
                # Outside the analysis: the calendar year's expense as stated (no occupancy to gross up to)
                stated = _calendar_year_expense(exp, analysis, calendar_year)
                first = analysis.start_date.year
                if pool and pool.deducts and calendar_year < first and first in by_calendar_year:
                    months = by_calendar_year[first]
                    return first_year_net(exp, stated, _calendar_year_expense(exp, analysis, first),
                                          sum(months) / len(months), first)
                return stated
            months = by_calendar_year[calendar_year]
            stated, occupancy = _calendar_year_expense(exp, analysis, calendar_year), sum(months) / len(months)
            key = calendar_year
        elif year in year_occupancy:
            stated, occupancy = _annual_expense(exp, year), year_occupancy[year]
            key = year
        elif pool and pool.deducts and year < 1 and 1 in year_occupancy:
            # Deflated at the Year 1 rate, as _recovery_for_expense does for an unpooled line
            year1_rate = rate_for_year(exp.growth_rate, exp.growth_schedule, 1)
            first_stated = _annual_expense(exp, 1)
            stated = first_stated / (Decimal(1) + year1_rate) ** (1 - year)
            return first_year_net(exp, stated, first_stated, year_occupancy[1], 1)
        else:
            return None
        return recoverable(exp, stated, occupancy, key)

    other_lines = [e for e in expenses if e.is_recoverable and not e.is_pct_of_egi]
    overrides = {o.expense_category: o for o in lease.recovery_overrides}

    category_pct: dict[str, Decimal] = {}
    for e in expenses:
        if e.is_recoverable and e.is_pct_of_egi and e.pct_of_egi is not None:
            category_pct[e.category] = category_pct.get(e.category, Decimal(0)) + e.pct_of_egi

    def line_fraction(exp: ExpenseInput) -> Decimal:
        """This line's part of its category's fee (several % of EGI lines can share a category)."""
        total = category_pct.get(exp.category, Decimal(0))
        return (exp.pct_of_egi or Decimal(0)) / total if total > 0 else Decimal(1)

    def fee_in(exp: ExpenseInput, key: int, occupancy: Decimal) -> Decimal:
        """A % of EGI line's fee tenants share in a recovery year (grossed up and less pool deductions,
        as other lines). Before the analysis: the first year's fee moved with the other recoverable
        expenses (the first year's fee when there are none)."""
        fraction = line_fraction(exp)
        by_year = {y: fee * fraction for y, fee in fee_by_year.get(exp.category, {}).items()}
        if key in by_year:
            return recoverable(exp, by_year[key], occupancy, key)
        first = min(by_year, default=None)
        if first is None:
            return Decimal(0)

        def stated(year: int) -> Decimal:
            return sum(((_calendar_year_expense(e, analysis, year) if calendar_year_recoveries
                         else _expense_any_year(e, year)) for e in other_lines), Decimal(0))
        then, at_first = stated(key), stated(first)
        return by_year[first] * then / at_first if then > 0 and at_first > 0 else by_year[first]

    def occupancy_in(key: int) -> Decimal:
        """Average occupancy of a recovery year inside the analysis."""
        if calendar_year_recoveries:
            months = by_calendar_year.get(key)
            return sum(months) / len(months) if months else Decimal(1)
        return year_occupancy.get(key, Decimal(1))

    cap_start = lease.recovery_cap_start or lease.start_date
    base_recovery_year = cap_start.year if calendar_year_recoveries else _year_number_any(analysis, cap_start)
    def annual_recoveries(year_number: int, calendar_year: int, is_recovery_free_rent: bool):
        """Annual recovery lines for one recovery year; identical for every month in that year."""
        actual_occupancy = year_occupancy.get(year_number, Decimal("0.95"))
        if calendar_year_recoveries and calendar_year in by_calendar_year:
            # One calendar year is billed at one occupancy, the same one its base-year stop uses
            months = by_calendar_year[calendar_year]
            actual_occupancy = sum(months) / len(months)
        key = calendar_year if calendar_year_recoveries else year_number
        fee_shares: dict[str, Decimal] = {}  # net lease's annual share of each % of EGI line

        def leaves_pool(exp: ExpenseInput) -> bool:
            return _leaves_pool(lease, next(
                (o for o in lease.recovery_overrides if o.expense_category == exp.category), None))

        exp_calc_inputs: list[tuple[ExpenseInput, Decimal, Decimal, str]] = []
        fee_rows: list[tuple[ExpenseInput, Decimal, Decimal, Decimal, dict]] = []
        modified_gross_pool_annual = Decimal(0)
        # Pools can give the modified gross lines different denominators: the stop then applies to
        # the sum of their $/SF
        modified_gross_per_sf = Decimal(0)
        modified_gross_denominators: set[Decimal] = set()
        for exp in expenses:
            if not exp.is_recoverable:
                continue
            if exp.is_pct_of_egi:
                fee_type = _effective_recovery_type(lease, exp.category)
                if fee_type == "nnn":
                    # The fee depends on EGI, so the waterfall solves it; record the share here
                    if not is_recovery_free_rent:
                        denom = denominator(exp, key)
                        o = overrides.get(exp.category)
                        admin = o.admin_fee_pct if o and o.admin_fee_pct is not None else Decimal(0)
                        fee_shares[exp.category] = (
                            lease.pro_rata_share if lease.pro_rata_share is not None
                            else lease.area / denom if denom > 0 else Decimal(0)) * (Decimal(1) + admin)
                    continue
                if fee_type == "base_year_stop" and fee_by_year and _has_stop_reference(lease, exp.category):
                    # The fee's increase over the base year, once the fee by year is known. Without a
                    # base-year date the explicit stop amount sets the stop; year 1 is the reference.
                    fee = fee_in(exp, key, actual_occupancy)
                    base_year = lease.base_year if lease.base_year is not None else analysis.start_date.year
                    base_key = (base_year if calendar_year_recoveries
                                else base_year - analysis.start_date.year + 1)
                    base_fee = fee_in(exp, base_key, occupancy_in(base_key))
                    rec, meta = _recovery_for_expense(
                        lease, exp, fee, denominator(exp, key), year_number, analysis.start_date.year,
                        base_year_expense=lambda _e, _y, _b=base_fee: _b)
                    fee_rows.append((exp, fee_by_year.get(exp.category, {}).get(key, Decimal(0)) * line_fraction(exp),
                                     fee, rec, meta))
                    continue
                if fee_type != "modified_gross" or not fee_by_year:
                    continue
                # Modified gross: the fee is in the pool measured against the stop, like the lines below
                fee_grossed = fee_in(exp, key, actual_occupancy)
                exp_calc_inputs.append((
                    exp, fee_by_year.get(exp.category, {}).get(key, Decimal(0)) * line_fraction(exp), fee_grossed,
                    fee_type))
                modified_gross_pool_annual += fee_grossed
                modified_gross_per_sf += (fee_grossed / denominator(exp, key)
                                          if denominator(exp, key) > 0 else Decimal(0))
                modified_gross_denominators.add(denominator(exp, key))
                continue
            if calendar_year_recoveries:
                stated_exp = _calendar_year_expense(exp, analysis, calendar_year)
            else:
                stated_exp = _annual_expense(exp, year_number)
            annual_exp = occupancy_adjusted_expense(stated_exp, exp, actual_occupancy)
            annual_exp_grossed = recoverable(exp, stated_exp, actual_occupancy, key)
            eff_recovery_type = _effective_recovery_type(lease, exp.category)
            exp_calc_inputs.append((exp, annual_exp, annual_exp_grossed, eff_recovery_type))
            if eff_recovery_type == "modified_gross" and not leaves_pool(exp):
                modified_gross_pool_annual += annual_exp_grossed
                modified_gross_per_sf += (annual_exp_grossed / denominator(exp, key)
                                          if denominator(exp, key) > 0 else Decimal(0))
                modified_gross_denominators.add(denominator(exp, key))

        computed: list[tuple[ExpenseInput, Decimal, Decimal, Decimal, dict]] = []
        mixed_mg = len(modified_gross_denominators) > 1
        for exp, annual_exp, annual_exp_grossed, eff_recovery_type in exp_calc_inputs:
            exp_denominator = denominator(exp, key)
            mg_share: Decimal | None = None
            mg_pool = modified_gross_pool_annual
            pooled_mg = eff_recovery_type == "modified_gross" and not leaves_pool(exp)
            if pooled_mg and mixed_mg and modified_gross_per_sf > 0:
                # Expressed over this line's denominator so the stop sees the pooled $/SF
                mg_pool = modified_gross_per_sf * exp_denominator
                mg_share = (annual_exp_grossed / exp_denominator if exp_denominator > 0 else Decimal(0)) \
                    / modified_gross_per_sf
            elif pooled_mg and modified_gross_pool_annual > Decimal(0):
                mg_share = annual_exp_grossed / modified_gross_pool_annual

            annual_recovery, calc_meta = _recovery_for_expense(
                lease,
                exp,
                annual_exp_grossed,
                exp_denominator,
                year_number,
                analysis.start_date.year,
                modified_gross_pool_annual=mg_pool if pooled_mg else None,
                modified_gross_pool_share=mg_share,
                base_year_expense=base_year_expense,
            )
            # The pooled $/SF the stop is tested against (None: measured alone or not modified gross)
            calc_meta["modified_gross_pool_per_sf"] = (
                mg_pool / exp_denominator if pooled_mg and mg_share is not None and exp_denominator > 0 else None)
            computed.append((exp, annual_exp, annual_exp_grossed, annual_recovery, calc_meta))
        computed.extend(fee_rows)
        _pool_base_year_stops(computed, lease)

        fee_caps: dict[str, Decimal] = {}
        if group_caps:
            recovery_year = calendar_year if calendar_year_recoveries else year_number

            def recovery_in(exp: ExpenseInput, year: int) -> Decimal:
                stated = (_calendar_year_expense(exp, analysis, year) if calendar_year_recoveries
                          else _expense_any_year(exp, year))
                grossed = recoverable(exp, stated, actual_occupancy, year, occupancy_key=key)
                return _recovery_for_expense(lease, exp, grossed, denominator(exp, year), year_number,
                                             analysis.start_date.year, base_year_expense=base_year_expense)[0]

            def share_of(exp: ExpenseInput, grossed: Decimal, denom: Decimal, recovery_type: str) -> Decimal:
                """The tenant's share of an expense before any stop (as _recovery_for_expense)."""
                if denom <= 0:
                    return Decimal(0)
                if recovery_type == "modified_gross" and lease.pro_rata_share is None:
                    return grossed * lease.area / denom
                return grossed * (lease.pro_rata_share if lease.pro_rata_share is not None else lease.area / denom)

            def share_now(row) -> Decimal:
                return share_of(row[0], row[2], denominator(row[0], key), row[4]["recovery_type"])

            def share_in(row, year: int) -> Decimal:
                exp = row[0]
                stated = (_calendar_year_expense(exp, analysis, year) if calendar_year_recoveries
                          else _expense_any_year(exp, year))
                return share_of(exp, recoverable(exp, stated, actual_occupancy, year, occupancy_key=key),
                                denominator(exp, year),
                                row[4]["recovery_type"])

            computed, fee_caps, fee_factors = _apply_group_caps(
                computed, lease, group_caps, recovery_year, base_recovery_year, recovery_in, expenses,
                fee_shares, fee_by_year, share_now, share_in,
            )
            fee_shares = {c: share * fee_factors.get(c, Decimal(1)) for c, share in fee_shares.items()}
        return computed, fee_shares, fee_caps, actual_occupancy, key

    def fee_share_terms(category: str, share: Decimal, fee_caps: dict[str, Decimal], proration: Decimal,
                        occupancy: Decimal, key: int) -> FeeShare:
        """A net lease's terms for one % of EGI line in a month (the share includes the admin fee; floor
        and cap in dollars, which the waterfall applies in that order). In a pool with excluded suites
        the line grosses up as the pool's other lines do (at the included suites' occupancy), and a
        deducting pool's fee comes off by what excluded base-year / modified gross leases pay."""
        o = overrides.get(category)
        pool = pools.get(category)
        monthly_area = lease.area / Decimal(12) * proration
        gross_factor = None
        if pool and pool.gross_up and key in pool.included_occupancy_by_year:
            lines = [e for e in expenses if e.is_recoverable and e.is_pct_of_egi and e.category == category]
            gross_factor = sum((line_fraction(e) * grossed(e, Decimal(1), occupancy, key) for e in lines), Decimal(0))
        deducted = (pool.deduction_by_year.get(key, {}).get(category, Decimal(0)) / Decimal(12)
                    if pool and pool.deducts else Decimal(0))
        return FeeShare(
            share=share * proration,
            gross_up=pool.gross_up if pool else True,
            floor=o.floor_per_sf_annual * monthly_area if o and o.floor_per_sf_annual is not None else None,
            cap=(o.cap_per_sf_annual * monthly_area
                 if o and o.cap_per_sf_annual is not None and not o.cap_group else None),
            cap_group=o.cap_group if o and o.cap_group in fee_caps else None,
            pool=pool.pool_id if pool and pool.deducts else None,
            pays_into=(pays_into or {}).get(category),
            gross_factor=gross_factor,
            deduction=deducted,
        )

    by_recovery_year: dict[tuple[int, int, bool], tuple] = {}
    for s in lease_slices:
        if s.is_vacant:
            continue

        is_recovery_free_rent = _is_free_rent_for_recoveries(lease, s.period_start, s.period_end)
        s.expense_recovery_detail = {}
        year_number = _fiscal_year_number(analysis, s.period_start)
        key = (year_number, s.period_start.year, is_recovery_free_rent)
        if key not in by_recovery_year:
            by_recovery_year[key] = annual_recoveries(*key)
        computed, fee_shares, fee_caps, actual_occupancy, recovery_key = by_recovery_year[key]

        # For partial first/last months, prorate recoveries by lease day-count overlap.
        proration = proration_factor(s.period_start, s.period_end, lease.start_date, lease.end_date)
        s.mgmt_fee_shares = {c: fee_share_terms(c, share, fee_caps, proration, actual_occupancy, recovery_key)
                             for c, share in fee_shares.items()}
        s.mgmt_fee_caps = {g: room / Decimal(12) * proration for g, room in fee_caps.items()
                           if any(f.cap_group == g for f in s.mgmt_fee_shares.values())}

        monthly_recovery = Decimal(0)
        for exp, annual_exp, annual_exp_grossed, annual_recovery, calc_meta in computed:
            monthly_recovery_before_proration = annual_recovery / Decimal(12)
            monthly_recovery_prorated = monthly_recovery_before_proration * proration
            monthly_recovery_final = Decimal(0) if is_recovery_free_rent else monthly_recovery_prorated

            monthly_recovery += monthly_recovery_final
            s.expense_recovery_detail[exp.category] = (
                s.expense_recovery_detail.get(exp.category, Decimal(0)) + monthly_recovery_final
            )

            if recovery_audit is not None:
                gross_up_factor = (  # before any pool deduction
                    ((annual_exp_grossed + deduction(exp, recovery_key)) / annual_exp)
                    if annual_exp > Decimal(0) else Decimal(1)
                )
                gross_up_reference = (stabilized_occupancy_pct if stabilized_occupancy_pct is not None
                                      else exp.gross_up_vacancy_pct)
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
                        recovery_pool=pools[exp.category].name if exp.category in pools else None,
                        share_denominator_area=denominator(exp, recovery_key),
                        pool_deduction=deduction(exp, recovery_key),
                        modified_gross_pool_per_sf=calc_meta.get("modified_gross_pool_per_sf"),
                    )
                )

        s.expense_recovery = monthly_recovery
