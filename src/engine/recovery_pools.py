"""
Recovery pools: expense lines recovered together over a share denominator other than the whole
property area.

A tenant's share of a pooled line is its area over the pool's denominator for the recovery year:
  property_area  property area less the excluded suites (anchors, outparcels)
  fixed_area     a fixed area
  occupied_area  the included suites' leased area (probability weighted, averaged over the
                 recovery year), at least minimum_occupancy_pct of their area

Tenants already bear vacancy through an occupied-area denominator, so such a pool's lines are
not grossed up. A property-area pool with excluded suites grosses up only the included suites'
vacancy (its denominator is their area): the building's expense at the occupancy it would have
with the included suites at the reference occupancy and the excluded suites as they are, so a
dark anchor's space is not grossed back up and billed to the other tenants. A fixed-area pool
grosses up at property occupancy. Leases in excluded suites recover on their own terms over the
whole property area;
with deduct_excluded_recoveries what they pay comes off the pool before the other tenants share it.
A lease's own Pro Rata Share still wins over any pool.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.engine.date_utils import add_months
from src.engine.types import AnalysisPeriod, MonthlySlice, RecoveryPoolInput, SuiteInput


@dataclass(frozen=True)
class PoolShare:
    """How one lease shares one pool's lines, by recovery year."""
    name: str
    denominator_by_year: dict[int, Decimal]
    deduction_by_year: dict[int, dict[str, Decimal]] = field(default_factory=dict)
    gross_up: bool = True
    pool_id: str = ""
    # Pools with excluded suites: the included suites' occupancy by recovery year and their share
    # of the property's suite area (empty: gross up at property occupancy)
    included_occupancy_by_year: dict[int, Decimal] = field(default_factory=dict)
    included_area_share: Decimal = Decimal(1)
    deducts: bool = False
    # Deducting pools: what the excluded suites' net leases pay toward its % of EGI lines (solved in
    # the waterfall), annualized by recovery year, by category
    net_fee_paid_by_year: dict[int, dict[str, Decimal]] = field(default_factory=dict)


def recovery_year_key(analysis: AnalysisPeriod, period_start, calendar_year_recoveries: bool) -> int:
    """The recovery year a month belongs to: its calendar year, or its analysis year number."""
    if calendar_year_recoveries:
        return period_start.year
    for fy in analysis.fiscal_years:
        if fy.start_date <= period_start <= fy.end_date:
            return fy.year_number
    return analysis.fiscal_years[-1].year_number


def _month_keys(analysis: AnalysisPeriod, calendar_year_recoveries: bool) -> list[int]:
    return [recovery_year_key(analysis, add_months(analysis.start_date, i), calendar_year_recoveries)
            for i in range(analysis.num_months)]


def pool_denominators(
    pools: list[RecoveryPoolInput],
    suites: list[SuiteInput],
    suite_slices: dict[str, list[MonthlySlice]],
    analysis: AnalysisPeriod,
    total_property_area: Decimal,
    calendar_year_recoveries: bool,
) -> dict[str, dict[int, Decimal]]:
    """Each pool's share denominator by recovery year."""
    area = {s.suite_id: s.area for s in suites}
    keys = _month_keys(analysis, calendar_year_recoveries)
    result: dict[str, dict[int, Decimal]] = {}
    for pool in pools:
        excluded = set(pool.excluded_suite_ids) & area.keys()
        included_area = max(Decimal(0), total_property_area - sum(area[s] for s in excluded))
        if pool.denominator == "fixed_area" and pool.fixed_area is not None:
            result[pool.pool_id] = {k: pool.fixed_area for k in keys}
        elif pool.denominator == "occupied_area":
            leased = [Decimal(0)] * analysis.num_months
            for suite_id, slices in suite_slices.items():
                if suite_id in excluded or suite_id not in area:
                    continue
                for s in slices:
                    if not s.is_vacant and 0 <= s.month_index < analysis.num_months:
                        leased[s.month_index] += area[suite_id] * s.scenario_weight * s.month_fraction
            by_year: dict[int, list[Decimal]] = defaultdict(list)
            for k, value in zip(keys, leased):
                by_year[k].append(min(value, included_area))
            floor = included_area * (pool.minimum_occupancy_pct or Decimal(0))
            result[pool.pool_id] = {k: max(sum(v) / len(v), floor) for k, v in by_year.items()}
        else:
            result[pool.pool_id] = {k: included_area for k in keys}
    return result


def pool_occupancies(
    pools: list[RecoveryPoolInput],
    suites: list[SuiteInput],
    suite_slices: dict[str, list[MonthlySlice]],
    analysis: AnalysisPeriod,
    calendar_year_recoveries: bool,
) -> dict[str, tuple[dict[int, Decimal], Decimal]]:
    """For each property-area pool with excluded suites: the included suites' occupancy by recovery
    year (day weighted, probability weighted) and their share of the property's suite area."""
    area = {s.suite_id: s.area for s in suites}
    total = sum(area.values(), Decimal(0))
    keys = _month_keys(analysis, calendar_year_recoveries)
    result: dict[str, tuple[dict[int, Decimal], Decimal]] = {}
    for pool in pools:
        excluded = set(pool.excluded_suite_ids) & area.keys()
        included_area = total - sum(area[s] for s in excluded)
        fixed = pool.denominator == "fixed_area" and pool.fixed_area is not None
        if not excluded or fixed or pool.denominator == "occupied_area" or included_area <= 0:
            continue
        leased = [Decimal(0)] * analysis.num_months
        for suite_id, slices in suite_slices.items():
            if suite_id in excluded or suite_id not in area:
                continue
            for s in slices:
                if not s.is_vacant and 0 <= s.month_index < analysis.num_months:
                    leased[s.month_index] += area[suite_id] * s.scenario_weight * s.month_fraction
        by_year: dict[int, list[Decimal]] = defaultdict(list)
        for k, value in zip(keys, leased):
            by_year[k].append(min(Decimal(1), value / included_area))
        result[pool.pool_id] = ({k: sum(v) / len(v) for k, v in by_year.items()}, included_area / total)
    return result


def excluded_recoveries(
    pools: list[RecoveryPoolInput],
    suite_slices: dict[str, list[MonthlySlice]],
    analysis: AnalysisPeriod,
    calendar_year_recoveries: bool,
) -> dict[str, dict[int, dict[str, Decimal]]]:
    """What the excluded suites' leases pay toward each deducting pool's lines, annualized by
    recovery year (probability weighted). Needs their recoveries attached first."""
    result: dict[str, dict[int, dict[str, Decimal]]] = {}
    for pool in pools:
        if not pool.deduct_excluded_recoveries:
            continue
        categories = set(pool.expense_categories)
        paid: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        for suite_id in pool.excluded_suite_ids:
            for s in suite_slices.get(suite_id, []):
                if s.is_vacant or not s.expense_recovery_detail:
                    continue
                key = recovery_year_key(analysis, s.period_start, calendar_year_recoveries)
                for category, monthly in s.expense_recovery_detail.items():
                    if category in categories:
                        paid[key][category] += monthly * s.scenario_weight
        months: dict[int, int] = defaultdict(int)
        for k in _month_keys(analysis, calendar_year_recoveries):
            months[k] += 1
        result[pool.pool_id] = {
            k: {c: v * 12 / months[k] for c, v in by_category.items()} for k, by_category in paid.items()
        }
    return result


def excluded_net_fees(
    paid_by_bucket: dict[date, dict[tuple[str, str], Decimal]],
    analysis: AnalysisPeriod,
    calendar_year_recoveries: bool,
) -> dict[str, dict[int, dict[str, Decimal]]]:
    """What the excluded suites' net leases pay toward each deducting pool's % of EGI lines, from the
    waterfall's fee by bucket ({bucket start: {(pool, category): amount}}; monthly buckets when
    recovering calendar years), annualized by recovery year as excluded_recoveries does."""
    months: dict[int, int] = defaultdict(int)
    for k in _month_keys(analysis, calendar_year_recoveries):
        months[k] += 1
    result: dict[str, dict[int, dict[str, Decimal]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(Decimal)))
    for start, paid in paid_by_bucket.items():
        key = recovery_year_key(analysis, start, calendar_year_recoveries)
        for (pool_id, category), amount in paid.items():
            result[pool_id][key][category] += amount * 12 / months[key]
    return result


def lease_pool_shares(
    suite_id: str,
    pools: list[RecoveryPoolInput],
    denominators: dict[str, dict[int, Decimal]],
    deductions: dict[str, dict[int, dict[str, Decimal]]],
    occupancies: dict[str, tuple[dict[int, Decimal], Decimal]] | None = None,
    net_fees: dict[str, dict[int, dict[str, Decimal]]] | None = None,
) -> dict[str, PoolShare]:
    """Pool terms by expense category for a lease in this suite (none for a pool it is excluded from)."""
    shares: dict[str, PoolShare] = {}
    for pool in pools:
        if suite_id in pool.excluded_suite_ids:
            continue
        occupancy, included_share = (occupancies or {}).get(pool.pool_id, ({}, Decimal(1)))
        share = PoolShare(
            name=pool.name,
            denominator_by_year=denominators.get(pool.pool_id, {}),
            deduction_by_year=deductions.get(pool.pool_id, {}),
            gross_up=pool.denominator != "occupied_area",
            pool_id=pool.pool_id,
            included_occupancy_by_year=occupancy,
            included_area_share=included_share,
            deducts=pool.deduct_excluded_recoveries,
            net_fee_paid_by_year=(net_fees or {}).get(pool.pool_id, {}) if pool.deduct_excluded_recoveries else {},
        )
        for category in pool.expense_categories:
            shares[category] = share
    return shares


def deducting_pools_excluding(suite_id: str, pools: list[RecoveryPoolInput]) -> dict[str, str]:
    """Expense category -> the deducting pool that excludes this suite (what its leases pay toward
    the category comes off that pool before the other tenants share it)."""
    return {category: pool.pool_id for pool in pools
            if pool.deduct_excluded_recoveries and suite_id in pool.excluded_suite_ids
            for category in pool.expense_categories}
