"""
Portfolio assumption resolution and application.

Assumption profiles are scoped by (portfolio, property type, market); any scope
field left as None matches everything. Profiles are layered from least to most
specific and later layers win field by field.

Overrides are applied to engine inputs (never to stored property data), so a
portfolio run or scenario leaves the underlying models untouched.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal

from src.engine.types import ExpenseInput, MarketAssumptions, OtherIncomeInput, ValuationParams

# Assumption field -> ValuationParams attribute
VALUATION_FIELDS: dict[str, str] = {
    "discount_rate": "discount_rate",
    "exit_cap_rate": "exit_cap_rate",
    "exit_costs_pct": "exit_costs_pct",
    "capital_reserves_per_unit": "capital_reserves_per_unit",
    "direct_cap_rate": "direct_cap_rate",
    "acquisition_costs_pct": "acquisition_costs_pct",
    "stabilized_occupancy_pct": "stabilized_occupancy_pct",
}

# Assumption field -> MarketAssumptions attribute (applied to every space type)
MARKET_FIELDS: dict[str, str] = {
    "market_rent_growth": "rent_growth_rate",
    "general_vacancy_pct": "general_vacancy_pct",
    "credit_loss_pct": "credit_loss_pct",
    "renewal_probability": "renewal_probability",
    "downtime_months": "downtime_months",
    "new_lease_term_months": "new_lease_term_months",
    "renewal_lease_term_months": "renewal_term_months",
    "new_ti_per_sf": "new_ti_per_sf",
    "renewal_ti_per_sf": "renewal_ti_per_sf",
    "new_lc_pct": "new_lc_pct",
    "renewal_lc_pct": "renewal_lc_pct",
    "new_free_rent_months": "new_free_rent_months",
    "renewal_free_rent_months": "renewal_free_rent_months",
}

# Assumption field -> the year-by-year MarketAssumptions schedule it overrides with the single field
MARKET_SCHEDULES: dict[str, str] = {
    "market_rent_growth": "rent_growth_schedule",
    "general_vacancy_pct": "general_vacancy_schedule",
    "credit_loss_pct": "credit_loss_schedule",
    "renewal_probability": "renewal_probability_schedule",
    "downtime_months": "downtime_schedule",
    "new_free_rent_months": "new_free_rent_schedule",
    "renewal_free_rent_months": "renewal_free_rent_schedule",
    # by lease year, not analysis year
    "new_lc_pct": "new_lc_pct_by_lease_year",
    "renewal_lc_pct": "renewal_lc_pct_by_lease_year",
}

INT_FIELDS = {
    "downtime_months",
    "new_lease_term_months",
    "renewal_lease_term_months",
    "new_free_rent_months",
    "renewal_free_rent_months",
}

# Fields handled outside the two maps above
OTHER_FIELDS = {"market_rent_change_pct", "expense_growth", "other_income_growth", "cpi_rate", "management_fee_pct"}

# Reserves set by basis: each becomes capital_reserves_per_unit for properties measured that way
RESERVES_BY_BASIS = {"capital_reserves_per_sf": "sf", "capital_reserves_per_unit_count": "unit"}

ALL_FIELDS = set(VALUATION_FIELDS) | set(MARKET_FIELDS) | OTHER_FIELDS
# Every field a profile can hold
PROFILE_FIELDS = ALL_FIELDS | set(RESERVES_BY_BASIS)

# Which end of a low/high range a better property (quality 5) sits at. Fields not listed (CPI)
# take the base value whatever the quality.
BETTER_IS_HIGH = {
    "stabilized_occupancy_pct", "market_rent_change_pct", "market_rent_growth", "renewal_probability",
    "new_lease_term_months", "renewal_lease_term_months", "other_income_growth",
}
BETTER_IS_LOW = {
    "discount_rate", "exit_cap_rate", "exit_costs_pct", "capital_reserves_per_unit", "capital_reserves_per_sf",
    "capital_reserves_per_unit_count", "management_fee_pct", "direct_cap_rate",
    "acquisition_costs_pct", "general_vacancy_pct", "credit_loss_pct", "downtime_months", "new_ti_per_sf",
    "renewal_ti_per_sf", "new_lc_pct", "renewal_lc_pct", "new_free_rent_months", "renewal_free_rent_months",
    "expense_growth",
}
QUALITY_BASE = Decimal(3)


def default_directions() -> dict[str, str]:
    """Field -> "higher" | "lower": which end of its range a quality-5 property takes. Users can
    change these on the library page (AssumptionSettings); unlisted fields always take base."""
    return {**{k: "higher" for k in BETTER_IS_HIGH}, **{k: "lower" for k in BETTER_IS_LOW}}


def position_in_range(
    key: str, low: Decimal, base: Decimal, high: Decimal, quality: Decimal,
    directions: dict[str, str] | None = None,
) -> Decimal:
    """Value for a 1-5 quality score: 3 = base, 5 = the favourable end, 1 = the unfavourable end,
    linear in between."""
    direction = (directions if directions is not None else default_directions()).get(key)
    if direction == "higher":
        good, bad = high, low
    elif direction == "lower":
        good, bad = low, high
    else:
        return base
    q = min(max(Decimal(quality), Decimal(1)), Decimal(5))
    step = (q - QUALITY_BASE) / 2  # -1 .. +1
    return base + step * ((good - base) if step >= 0 else (base - bad))


@dataclass(frozen=True)
class ScopedValues:
    """One layer of assumption values with its scope."""
    values: dict[str, Decimal]
    portfolio_id: str | None = None
    property_type: str | None = None
    market: str | None = None
    mode: str = "set"        # "set" replaces, "shift" adds to the resolved value
    source: str = ""         # label for audit (profile or scenario name)
    cbsa_code: str | None = None
    state: str | None = None         # two-letter
    quality_score: int | None = None  # profile written for this quality score only
    ranges: dict[str, tuple[Decimal, Decimal]] = field(default_factory=dict)  # field -> (low, high)


def _norm(s: str | None) -> str | None:
    return s.strip().lower() if s and s.strip() else None


def quality_bucket(score: Decimal) -> int:
    """Whole score a quality-specific profile is written for; halves round up (4.5 -> 5)."""
    return int(Decimal(score).quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class PropertyScope:
    """What a property offers for matching profiles."""
    property_type: str
    market: str | None = None
    cbsa_code: str | None = None
    state: str | None = None
    quality_score: Decimal | None = None


def matches(layer: ScopedValues, portfolio_id: str | None, scope: PropertyScope) -> bool:
    if layer.portfolio_id is not None and layer.portfolio_id != portfolio_id:
        return False
    if layer.property_type is not None and _norm(layer.property_type) != _norm(scope.property_type):
        return False
    if layer.cbsa_code is not None and layer.cbsa_code != scope.cbsa_code:
        return False
    if layer.market is not None and _norm(layer.market) != _norm(scope.market):
        return False
    if layer.state is not None and _norm(layer.state) != _norm(scope.state):
        return False
    if layer.quality_score is not None and (
        scope.quality_score is None or quality_bucket(scope.quality_score) != layer.quality_score
    ):
        return False
    return True


def specificity(layer: ScopedValues) -> tuple[int, int, int, int]:
    """Type first, then geography (CBSA > market name > state > none), then a quality-specific
    profile, then portfolio scope. So CBSA + type + quality > CBSA + type > state + type > type >
    market only > default."""
    geo = 3 if layer.cbsa_code else 2 if layer.market else 1 if layer.state else 0
    return (
        1 if layer.property_type is not None else 0,
        geo,
        1 if layer.quality_score is not None else 0,
        1 if layer.portfolio_id is not None else 0,
    )


@dataclass
class ResolvedAssumptions:
    values: dict[str, Decimal] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)  # field -> layer label that set it
    # field -> (low, base, high) of the layer that set it, when that layer gave a range
    ranges: dict[str, tuple[Decimal, Decimal, Decimal]] = field(default_factory=dict)


def resolve(
    layers: list[ScopedValues],
    portfolio_id: str | None,
    property_type: str,
    market: str | None,
    base: ResolvedAssumptions | None = None,
    *,
    cbsa_code: str | None = None,
    state: str | None = None,
    quality_score: Decimal | None = None,
    area_unit: str | None = None,
    directions: dict[str, str] | None = None,
) -> ResolvedAssumptions:
    """
    Merge matching layers from least to most specific. "set" layers replace a
    field; "shift" layers add to whatever value the field has so far (fields
    with no value yet are recorded as a shift to apply to the engine input).
    A "set" value with a low/high range is positioned in it by the property's
    quality score, unless the layer was written for that quality score.
    """
    scope = PropertyScope(property_type, market, cbsa_code, state, quality_score)
    out = ResolvedAssumptions(
        values=dict(base.values) if base else {},
        sources=dict(base.sources) if base else {},
        ranges=dict(base.ranges) if base else {},
    )
    shifts: dict[str, Decimal] = {}
    applicable = [l for l in layers if matches(l, portfolio_id, scope)]
    for layer in sorted(applicable, key=specificity):
        for key, val in layer.values.items():
            if key in RESERVES_BY_BASIS:
                if area_unit != RESERVES_BY_BASIS[key]:
                    continue
                if layer.ranges.get(key):
                    layer = replace(layer, ranges={**layer.ranges, "capital_reserves_per_unit": layer.ranges[key]})
                key = "capital_reserves_per_unit"
            if key not in ALL_FIELDS or val is None:
                continue
            if layer.mode == "shift":
                if key in out.values:
                    out.values[key] = out.values[key] + val
                else:
                    shifts[key] = shifts.get(key, Decimal(0)) + val
                out.sources[key] = f"{out.sources.get(key, 'model')} + {layer.source}".strip()
            else:
                out.values[key] = val
                shifts.pop(key, None)
                out.sources[key] = layer.source
                out.ranges.pop(key, None)
                if key in layer.ranges:
                    low, high = layer.ranges[key]
                    out.ranges[key] = (low, val, high)
                    if quality_score is not None and layer.quality_score is None:
                        out.values[key] = position_in_range(key, low, val, high, quality_score, directions)
                        if key in INT_FIELDS:  # whole months
                            out.values[key] = out.values[key].quantize(Decimal(1), rounding=ROUND_HALF_UP)
                        if out.values[key] != val:
                            out.sources[key] = f"{layer.source} (quality {Decimal(quality_score).normalize():f})"
    for key, val in shifts.items():
        out.values[f"shift:{key}"] = val
    return out


def _coerce(key: str, val: Decimal) -> Decimal | int:
    return int(val) if key in INT_FIELDS else val


def _apply(current, key: str, resolved: dict[str, Decimal]):
    """New value for one field: explicit set wins, else apply any pending shift."""
    if key in resolved:
        return _coerce(key, resolved[key])
    shift = resolved.get(f"shift:{key}")
    if shift is not None and current is not None:
        return _coerce(key, Decimal(str(current)) + shift)
    return current


def _apply_schedule(schedule: tuple[Decimal, ...], key: str, resolved: dict[str, Decimal]) -> tuple[Decimal, ...]:
    """Year-by-year rates under an override: a set replaces the table, a shift moves every year."""
    if not schedule:
        return schedule
    if key in resolved:
        return ()
    shift = resolved.get(f"shift:{key}")
    if shift is not None:
        return tuple(r + shift for r in schedule)
    return schedule


@dataclass
class OverrideTargets:
    params: ValuationParams
    market: dict[str, MarketAssumptions]
    expenses: list[ExpenseInput]
    other_income: list[OtherIncomeInput]
    cpi_assumption: Decimal
    cpi_schedule: tuple[Decimal, ...] = ()


def apply_assumptions(targets: OverrideTargets, resolved: ResolvedAssumptions) -> OverrideTargets:
    """Return new engine inputs with resolved assumptions applied."""
    vals = resolved.values

    param_changes = {}
    for key, attr in VALUATION_FIELDS.items():
        new = _apply(getattr(targets.params, attr), key, vals)
        if new != getattr(targets.params, attr):
            param_changes[attr] = new
    params = replace(targets.params, **param_changes) if param_changes else targets.params

    rent_factor = Decimal(1)
    if "market_rent_change_pct" in vals:
        rent_factor += vals["market_rent_change_pct"]
    if "shift:market_rent_change_pct" in vals:
        rent_factor += vals["shift:market_rent_change_pct"]

    market: dict[str, MarketAssumptions] = {}
    for space_type, m in targets.market.items():
        changes = {}
        for key, attr in MARKET_FIELDS.items():
            new = _apply(getattr(m, attr), key, vals)
            if new != getattr(m, attr):
                changes[attr] = new
        for key, attr in MARKET_SCHEDULES.items():
            current = getattr(m, attr)
            schedule = _apply_schedule(current, key, vals)
            if key == "downtime_months":
                schedule = tuple(max(0, int(v)) for v in schedule)
            if schedule != current:
                changes[attr] = schedule
        if rent_factor != Decimal(1):
            changes["market_rent_per_unit"] = m.market_rent_per_unit * rent_factor
        market[space_type] = replace(m, **changes) if changes else m

    expenses = []
    fee = _apply(None, "management_fee_pct", vals)
    for e in targets.expenses:
        if e.is_pct_of_egi:
            if e.category == "management_fee" and ("management_fee_pct" in vals or "shift:management_fee_pct" in vals):
                e = replace(e, pct_of_egi=_apply(e.pct_of_egi, "management_fee_pct", vals))
            expenses.append(e)
            continue
        g = _apply(e.growth_rate, "expense_growth", vals)
        sched = _apply_schedule(e.growth_schedule, "expense_growth", vals)
        changed = g != e.growth_rate or sched != e.growth_schedule
        expenses.append(replace(e, growth_rate=g, growth_schedule=sched) if changed else e)

    if fee is not None and not any(e.category == "management_fee" for e in targets.expenses):
        # No management fee modeled: the library's fee applies as a % of EGI line, not recovered
        expenses.append(ExpenseInput(
            expense_id="library:management_fee", category="management_fee", base_amount=Decimal(0),
            growth_rate=Decimal(0), is_recoverable=False, is_gross_up_eligible=False,
            gross_up_vacancy_pct=None, is_pct_of_egi=True, pct_of_egi=fee,
        ))

    other_income = []
    for oi in targets.other_income:
        g = _apply(oi.growth_rate, "other_income_growth", vals)
        sched = _apply_schedule(oi.growth_schedule, "other_income_growth", vals)
        changed = g != oi.growth_rate or sched != oi.growth_schedule
        other_income.append(replace(oi, growth_rate=g, growth_schedule=sched) if changed else oi)

    cpi = _apply(targets.cpi_assumption, "cpi_rate", vals)
    cpi_schedule = _apply_schedule(targets.cpi_schedule, "cpi_rate", vals)

    return OverrideTargets(
        params=params,
        market=market,
        expenses=expenses,
        other_income=other_income,
        cpi_assumption=cpi,
        cpi_schedule=cpi_schedule,
    )


# Fields a self storage unit-mix model has no counterpart for: no leases to renew, re-let or
# fit out, and no CPI-indexed rents. General vacancy is written for leased buildings; storage
# occupancy changes only through stabilized_occupancy_pct.
STORAGE_IGNORED_FIELDS = {
    "general_vacancy_pct", "renewal_probability", "downtime_months", "new_lease_term_months", "renewal_lease_term_months",
    "new_ti_per_sf", "renewal_ti_per_sf", "new_lc_pct", "renewal_lc_pct", "new_free_rent_months",
    "renewal_free_rent_months", "cpi_rate",
}


def apply_storage_assumptions(model, resolved: ResolvedAssumptions):
    """Return (a copy of a self storage operating model with the resolved overrides that mean
    something for a unit mix applied, the override fields it ignored).

    Rent growth and level drive street rates, stabilized occupancy sets each unit type's stabilized
    occupancy, other-income growth grows the ancillary lines. Valuation-level fields and expense
    growth reach the engine through apply_assumptions as for any property.
    """
    vals = resolved.values
    data = model.model_dump()
    data["street_rate_growth_pct"] = _apply(data["street_rate_growth_pct"], "market_rent_growth", vals)
    data["street_rate_growth_schedule"] = list(
        _apply_schedule(tuple(data["street_rate_growth_schedule"]), "market_rent_growth", vals)
    )
    data["credit_loss_pct"] = max(_apply(data["credit_loss_pct"], "credit_loss_pct", vals), Decimal(0))
    rent_factor = 1 + vals.get("market_rent_change_pct", 0) + vals.get("shift:market_rent_change_pct", 0)
    occupancy_override = any(k in vals for k in ("stabilized_occupancy_pct", "shift:stabilized_occupancy_pct"))
    for unit in data["unit_types"]:
        unit["street_rate"] = unit["street_rate"] * rent_factor
        if not occupancy_override:
            continue
        occupancy = unit["stabilized_occupancy"]
        if occupancy is None and unit["count"]:
            occupancy = Decimal(str(unit["occupied_units"])) / unit["count"]  # the engine's default
        occupancy = _apply(occupancy, "stabilized_occupancy_pct", vals)
        # A shift can push past full or empty
        unit["stabilized_occupancy"] = None if occupancy is None else min(max(occupancy, Decimal(0)), Decimal(1))
    for line in data["ancillary_lines"]:
        line["growth_pct"] = _apply(line["growth_pct"], "other_income_growth", vals)
    ignored = sorted(k for k in STORAGE_IGNORED_FIELDS if k in vals or f"shift:{k}" in vals)
    return type(model).model_validate(data), ignored
