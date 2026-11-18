"""
Probability-weighted renewal and new-tenant speculative lease generation.

When an in-place lease expires, this engine generates two scenarios:
  1. RENEWAL: tenant renews with probability P
  2. NEW TENANT: tenant vacates with probability (1 - P), new lease after downtime

If either speculative lease expires within the analysis period, the engine
recurses to generate the next generation of renewal/new pairs, with cumulative
probability weights (e.g. gen-2 renewal weight = P_renew^2).

The MonthlySlices returned have scenario_weight set to reflect the probability
of that outcome. The waterfall aggregates by summing (value * weight), producing
probability-weighted blended cash flows.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from src.engine.date_utils import add_months, end_of_month, months_between
from src.engine.growth import growth_factor_to_year, market_rent_at_year, rate_for_year
from src.engine.lease_projector import _current_rent, make_vacant_slices, project_lease_cash_flows
from src.engine.types import (
    AnalysisPeriod,
    FreeRentPeriodInput,
    LeaseInput,
    MarketAssumptions,
    MonthlySlice,
    RentStepInput,
    SuiteInput,
    ExpenseRecoveryOverride,
)

_MAX_GENERATIONS = 20  # prevent runaway recursion


def _make_free_rent_periods(start_date: date, months: int) -> tuple[FreeRentPeriodInput, ...]:
    if months <= 0:
        return ()
    end_date = add_months(start_date, months) - timedelta(days=1)
    return (FreeRentPeriodInput(
        start_date=start_date,
        end_date=end_date,
        applies_to_base_rent=True,
        applies_to_recoveries=False,
    ),)


def _market_rent_at(
    market: MarketAssumptions,
    analysis: AnalysisPeriod,
    target_date: date,
) -> Decimal:
    """Market rent grown by fiscal year number (fiscal-year convention).
    Year 1 = base, Year 2 = base × (1+rate), etc.; dates before the analysis use Year 1."""
    return market_rent_at_year(
        market.market_rent_per_unit,
        market.rent_growth_rate,
        _year_number_at(analysis, target_date),
        market.rent_growth_schedule,
    )


def _lease_escalation_at(market: MarketAssumptions, analysis: AnalysisPeriod, target_date: date) -> Decimal:
    """
    Annual increase on a market lease starting at target_date: the profile's lease escalation,
    else the market rent growth rate in effect for the analysis year containing target_date.
    """
    if market.lease_escalation_pct is not None:
        return market.lease_escalation_pct
    return rate_for_year(market.rent_growth_rate, market.rent_growth_schedule, _year_number_at(analysis, target_date))


def _year_number_at(analysis: AnalysisPeriod, target_date: date) -> int:
    """1-based analysis year containing target_date: last year + 1 beyond the analysis, and Year 0, -1, ...
    (whole years back) before it. Rates and market rent read years before Year 1 as Year 1."""
    for fy in analysis.fiscal_years:
        if fy.start_date <= target_date <= fy.end_date:
            return fy.year_number
    first = analysis.fiscal_years[0].start_date
    if target_date < first:
        return 1 - ((first.year - target_date.year) * 12 + first.month - target_date.month + 11) // 12
    return len(analysis.fiscal_years) + 1


def _free_rent_months(market: MarketAssumptions, analysis: AnalysisPeriod, start: date) -> tuple[Decimal, Decimal]:
    """(renewal, new tenant) free rent months for a market lease starting at `start`."""
    year = _year_number_at(analysis, start)
    return (rate_for_year(Decimal(market.renewal_free_rent_months), market.renewal_free_rent_schedule, year),
            rate_for_year(Decimal(market.new_free_rent_months), market.new_free_rent_schedule, year))


def _base_year(
    analysis: AnalysisPeriod, start: date, recovery_type: str,
    overrides: tuple[ExpenseRecoveryOverride, ...] = (),
) -> int | None:
    """A base-year lease's base year is the analysis year it starts in (as a calendar year)."""
    if recovery_type != "base_year_stop" and all(o.recovery_type != "base_year_stop" for o in overrides):
        return None
    return analysis.start_date.year + _year_number_at(analysis, start) - 1


def _market_recovery(
    market: MarketAssumptions,
    original_recovery_type: str,
    original_overrides: tuple[ExpenseRecoveryOverride, ...] = (),
    original_stop_per_sf: Decimal | None = None,
    original_pro_rata_share: Decimal | None = None,
) -> tuple[str, tuple[ExpenseRecoveryOverride, ...], Decimal | None, Decimal | None]:
    """
    (recovery type, per-category rules, $/SF stop, typed pro rata share) of a market lease: the
    profile's recovery structure with the area share, else ("same as expiring lease") the expiring
    lease's type, overrides, stop and share. Either way the base year resets to the lease start.
    """
    if market.recovery_type is None:
        rtype, overrides = _reset_stop(original_recovery_type, original_overrides, original_stop_per_sf)
        return rtype, _rebase(overrides), original_stop_per_sf, original_pro_rata_share
    rtype, overrides = _reset_stop(market.recovery_type, market.recovery_overrides, market.expense_stop_per_sf)
    return rtype, _rebase(overrides), market.expense_stop_per_sf, None


def _rebase(overrides: tuple[ExpenseRecoveryOverride, ...]) -> tuple[ExpenseRecoveryOverride, ...]:
    """A new lease term's base-year stop comes from its own base year: fixed base-year amounts are dropped."""
    return tuple(
        replace(o, base_year_stop_amount=None) if o.recovery_type == "base_year_stop" else o
        for o in overrides
    )


def _reset_stop(
    recovery_type: str, overrides: tuple[ExpenseRecoveryOverride, ...], stop_per_sf: Decimal | None,
) -> tuple[str, tuple[ExpenseRecoveryOverride, ...]]:
    """A market lease's base year resets to the year it starts: modified gross with no stop set
    recovers expenses above their level in that year, i.e. a base-year stop (the caller sets the
    base year from the lease start). A stop that is set is kept."""
    def reset(rtype: str, stop: Decimal | None) -> str:
        return "base_year_stop" if rtype == "modified_gross" and stop is None else rtype

    def override_stop(o: ExpenseRecoveryOverride) -> Decimal | None:
        # As the expense engine reads it: the override's stop, a legacy floor, else the lease's stop
        return next((s for s in (o.expense_stop_per_sf, o.floor_per_sf_annual, stop_per_sf) if s is not None), None)

    return reset(recovery_type, stop_per_sf), tuple(
        replace(o, recovery_type=reset(o.recovery_type, override_stop(o))) for o in overrides
    )


def _build_speculative_lease(
    suite: SuiteInput,
    lease_id: str,
    tenant_label: str,
    start_date: date,
    end_date: date,
    rent: Decimal,
    growth_rate: Decimal,
    ti_per_sf: Decimal,
    lc_pct: Decimal,
    free_rent_months: int | Decimal,
    recovery_type: str = "nnn",
    pro_rata_share: Decimal | None = None,
    rent_payment_frequency: str = "annual",
    rent_step_pcts: tuple[tuple[int, Decimal], ...] = (),
    term_months: int | None = None,
    base_year: int | None = None,
    escalation_per_unit: Decimal | None = None,
    rent_basis: str = "per_area",
    recovery_overrides: tuple[ExpenseRecoveryOverride, ...] = (),
    expense_stop_per_sf: Decimal | None = None,
) -> LeaseInput:
    """
    A market lease; with rent steps or a fixed $ escalation the rent becomes a step schedule.
    """
    steps = (
        _market_rent_steps(start_date, rent, growth_rate, rent_step_pcts, term_months, escalation_per_unit)
        if (rent_step_pcts or escalation_per_unit is not None) and term_months else ()
    )
    return LeaseInput(
        lease_id=lease_id,
        suite_id=suite.suite_id,
        tenant_name=tenant_label,
        area=suite.area,
        start_date=start_date,
        end_date=end_date,
        base_rent_per_unit=rent,
        rent_payment_frequency=rent_payment_frequency,
        rent_basis=rent_basis,
        escalation_type="fixed_step" if steps or escalation_per_unit is not None else "pct_annual",
        escalation_pct=growth_rate,
        cpi_floor=None,
        cpi_cap=None,
        rent_steps=steps,
        free_rent_periods=_make_free_rent_periods(start_date, int(free_rent_months)),
        recovery_type=recovery_type,
        pro_rata_share=pro_rata_share,
        base_year_stop_amount=None,
        expense_stop_per_sf=expense_stop_per_sf,
        recovery_overrides=recovery_overrides,
        pct_rent_breakpoint=None,
        pct_rent_rate=None,
        base_year=base_year,
        renewal_probability_override=None,
    )


def _step_factor(step_pcts: tuple[tuple[int, Decimal], ...], month_index: int) -> Decimal:
    """Cumulative rent step factor in lease month `month_index` (0-based)."""
    factor = Decimal(1)
    for month, pct in step_pcts:
        if month_index >= month - 1:
            factor *= Decimal(1) + pct
    return factor


def _escalated_rent(
    rent: Decimal, growth_rate: Decimal, step_pcts: tuple[tuple[int, Decimal], ...], month_index: int,
    escalation_per_unit: Decimal | None = None,
) -> Decimal:
    """Rent in lease month `month_index` (0-based): annual escalation, % or fixed $, then rent steps."""
    years = month_index // 12
    escalated = rent + escalation_per_unit * years if escalation_per_unit is not None else rent * (1 + growth_rate) ** years
    return escalated * _step_factor(step_pcts, month_index)


def _market_rent_steps(
    start_date: date, rent: Decimal, growth_rate: Decimal,
    step_pcts: tuple[tuple[int, Decimal], ...], term_months: int,
    escalation_per_unit: Decimal | None = None,
) -> tuple[RentStepInput, ...]:
    """Rent schedule of a market lease with annual escalation and rent steps."""
    steps: list[RentStepInput] = []
    current = rent
    for m in range(1, term_months):
        r = _escalated_rent(rent, growth_rate, step_pcts, m, escalation_per_unit)
        if r != current:
            steps.append(RentStepInput(add_months(start_date, m), r))
            current = r
    return tuple(steps)


def _full_term_rent(
    lease: LeaseInput, term_months: int, free_rent_months: int | Decimal, include_escalations: bool = True,
    step_pcts: tuple[tuple[int, Decimal], ...] = (),
    escalation_per_unit: Decimal | None = None,
    lease_year_rates: tuple[Decimal, ...] = (),
) -> Decimal:
    """
    Effective rent over the whole lease term, including months after the analysis ends.
    Free rent may be a fraction of a month; rent steps always count. With `lease_year_rates`
    each lease year's rent is multiplied by its rate (the last rate carries forward).
    """
    monthly = lease.rent_area
    if lease.rent_payment_frequency != "monthly":
        monthly /= Decimal(12)
    growth = (lease.escalation_pct or Decimal(0)) if include_escalations else Decimal(0)
    per_unit = escalation_per_unit if include_escalations else None
    free = Decimal(free_rent_months)
    return monthly * sum(
        _escalated_rent(lease.base_rent_per_unit, growth, step_pcts, m, per_unit)
        * (Decimal(1) - min(Decimal(1), max(Decimal(0), free - m)))
        * (_lease_year_rate(lease_year_rates, m) if lease_year_rates else Decimal(1))
        for m in range(term_months)
    )


def _lease_year_rate(rates: tuple[Decimal, ...], month_index: int) -> Decimal:
    """Rate of the lease year containing lease month `month_index` (0-based); the last rate carries forward."""
    return rates[min(month_index // 12, len(rates) - 1)]


def _apply_fractional_free_rent(slices: list[MonthlySlice], start_date: date, free_months: Decimal) -> None:
    """Abate the fraction of a month left after whole free-rent months (blended published DCF software leasing)."""
    whole = int(free_months)
    fraction = free_months - whole
    if fraction <= 0:
        return
    month_start = add_months(start_date, whole)
    for s in slices:
        if s.period_start == month_start:
            adjustment = -(s.base_rent * fraction)
            s.free_rent_adjustment += adjustment
            s.effective_rent += adjustment
            return


def _add_ti_lc_to_first_slice(
    slices: list[MonthlySlice],
    lease: LeaseInput,
    term_months: int,
    free_rent_months: int | Decimal,
    ti_per_sf: Decimal,
    lc_pct: Decimal,
    lc_per_sf: Decimal = Decimal(0),
    cost_factor: Decimal = Decimal(1),
    lc_includes_escalations: bool = True,
    step_pcts: tuple[tuple[int, Decimal], ...] = (),
    escalation_per_unit: Decimal | None = None,
    lc_pct_by_lease_year: tuple[Decimal, ...] = (),
) -> None:
    """
    Attach TI cost and LC cost to the first slice of a speculative lease.
    TI = $/SF * area (one-time at commencement).
    LC = pct * total rent over the full lease term + $/SF * area (paid at lease signing,
    i.e. first month). With `lc_pct_by_lease_year` each lease year's rent takes that year's
    rate instead. `cost_factor` grows the $/SF amounts to the year the lease starts.
    """
    if not slices:
        return
    first = slices[0]
    if lease.start_date < first.period_start:
        return  # the lease began before the analysis: its TI and LC were spent before Year 1
    first.ti_cost = -(ti_per_sf * cost_factor * lease.rent_area)
    if lc_pct_by_lease_year:
        pct_lc = _full_term_rent(lease, term_months, free_rent_months, lc_includes_escalations,
                                 step_pcts, escalation_per_unit, lc_pct_by_lease_year)
    else:
        pct_lc = _full_term_rent(lease, term_months, free_rent_months, lc_includes_escalations,
                                 step_pcts, escalation_per_unit) * lc_pct
    first.lc_cost = -(pct_lc + lc_per_sf * cost_factor * lease.rent_area)


def prior_rent_in_market_units(
    lease: LeaseInput, rent: Decimal, market: MarketAssumptions, area: Decimal,
) -> Decimal | None:
    """An expiring lease's rent rate restated in the market profile's rent basis and frequency
    (None when the market rent is per area and the space has no area)."""
    annual = rent * lease.rent_area * (Decimal(12) if lease.rent_payment_frequency == "monthly" else Decimal(1))
    if market.rent_basis != "total":
        if area <= 0:
            return None
        annual /= area
    return annual / Decimal(12) if market.rent_payment_frequency == "monthly" else annual


def last_contract_rent(lease: LeaseInput, end_date: date, cpi_assumption: Decimal,
                       cpi_schedule: tuple[Decimal, ...] = (), analysis_start: date | None = None) -> Decimal:
    """Rent rate in the lease's last month (steps and escalations included, free rent ignored)."""
    return _current_rent(lease, date(end_date.year, end_date.month, 1), cpi_assumption, cpi_schedule, analysis_start)


def _renewal_rent(market: MarketAssumptions, rent: Decimal, prior_rent: Decimal | None) -> Decimal:
    """Renewal rent under the profile's rule: market, or the greater / lesser of market and prior rent."""
    if prior_rent is None or market.renewal_rent_rule == "market":
        return rent
    return max(rent, prior_rent) if market.renewal_rent_rule == "greater_of_prior" else min(rent, prior_rent)


def _next_prior(lease: LeaseInput, end_raw: date, market: MarketAssumptions, area: Decimal,
                cpi_assumption: Decimal) -> Decimal | None:
    """Prior rent for the rollover after a speculative or option lease, in the next profile's units."""
    if market.renewal_rent_rule == "market":
        return None
    return prior_rent_in_market_units(lease, last_contract_rent(lease, end_raw, cpi_assumption), market, area)


def _leasing_cost_factor(market: MarketAssumptions, analysis: AnalysisPeriod, start_date: date) -> Decimal:
    """Growth of TI and LC $/SF from Year 1 to the analysis year the lease starts."""
    return growth_factor_to_year(
        market.leasing_cost_growth_rate,
        _year_number_at(analysis, start_date),
        market.leasing_cost_growth_schedule,
    )


def generate_speculative_leases(
    suite: SuiteInput,
    vacancy_start_date: date,
    analysis: AnalysisPeriod,
    market: MarketAssumptions,
    original_recovery_type: str = "nnn",
    original_pro_rata_share: Decimal | None = None,
    renewal_probability_override: Decimal | None = None,
    renewal_rent_spread_override: Decimal | None = None,
    cpi_assumption: Decimal = Decimal("0.025"),
    generation: int = 0,
    cumulative_weight: Decimal = Decimal(1),
    branch_path: str = "",
    market_map: dict[str, MarketAssumptions] | None = None,
    downtime_months_override: int | None = None,
    prior_rent: Decimal | None = None,
    original_recovery_overrides: tuple[ExpenseRecoveryOverride, ...] = (),
    original_expense_stop_per_sf: Decimal | None = None,
) -> tuple[list[MonthlySlice], list[LeaseInput]]:
    """
    Recursively generate probability-weighted speculative lease cash flows
    from a vacancy date through the end of the analysis period.

    Each call generates:
      - RENEWAL scenario (weight = cumulative_weight * renewal_probability)
      - NEW TENANT scenario (weight = cumulative_weight * (1 - renewal_probability))
      - Vacancy downtime slices for the new tenant scenario

    Then recurses when either speculative lease expires within the analysis period.
    With `market_map`, later generations follow the MLA's `next_space_type` chain.
    `downtime_months_override` replaces the MLA downtime for this generation only (lease-up).
    `prior_rent` is the expiring lease's last rent in `market`'s units, for the renewal rent rule.

    Returns:
        (slices, lease_inputs) — all generated MonthlySlices and the LeaseInput
        objects used to generate them, so the caller can attach expense recoveries.
    """
    if generation >= _MAX_GENERATIONS:
        return [], []
    if vacancy_start_date >= analysis.end_date:
        return [], []

    # Lease-level renewal overrides apply to the first rollover only.
    expiry_year = _year_number_at(analysis, vacancy_start_date)
    renewal_prob = (
        renewal_probability_override
        if generation == 0 and renewal_probability_override is not None
        else rate_for_year(market.renewal_probability, market.renewal_probability_schedule, expiry_year)
    )
    new_prob = Decimal(1) - renewal_prob

    all_slices: list[MonthlySlice] = []
    all_lease_inputs: list[LeaseInput] = []
    next_market = market
    if market_map and market.next_space_type:
        next_market = market_map.get(market.next_space_type, market)
    recovery_type, recovery_overrides, stop_per_sf, pro_rata_share = _market_recovery(
        market, original_recovery_type, original_recovery_overrides, original_expense_stop_per_sf,
        original_pro_rata_share)

    if market.rollover_method == "blended":
        return _blended_rollover(
            suite, vacancy_start_date, analysis, market, next_market, renewal_prob, expiry_year,
            (recovery_type, recovery_overrides, stop_per_sf, pro_rata_share),
            renewal_rent_spread_override if generation == 0 else None,
            cpi_assumption, generation, cumulative_weight, branch_path, market_map, downtime_months_override,
            prior_rent,
        )

    # ===== RENEWAL SCENARIO =====
    renewal_weight = cumulative_weight * renewal_prob
    if renewal_weight > Decimal("0.0001"):  # skip negligible probabilities
        renewal_rent = _market_rent_at(market, analysis, vacancy_start_date)
        renewal_spread = (
            renewal_rent_spread_override
            if generation == 0 and renewal_rent_spread_override is not None
            else market.renewal_rent_adjustment_pct
        )
        renewal_rent = renewal_rent * (Decimal(1) + renewal_spread)
        renewal_rent = _renewal_rent(market, max(renewal_rent, Decimal(0)), prior_rent)

        renewal_start = vacancy_start_date
        renewal_end_raw = add_months(renewal_start, market.renewal_term_months) - timedelta(days=1)
        renewal_end = min(renewal_end_raw, analysis.end_date)
        renewal_free = _free_rent_months(market, analysis, renewal_start)[0]

        renewal_lease = _build_speculative_lease(
            suite=suite,
            lease_id=f"spec_renew_{suite.suite_id}_g{generation}_{branch_path}R",
            tenant_label=f"Renewal Tenant (Gen {generation + 1})",
            start_date=renewal_start,
            end_date=renewal_end,
            rent=renewal_rent,
            growth_rate=_lease_escalation_at(market, analysis, renewal_start),
            ti_per_sf=market.renewal_ti_per_sf,
            lc_pct=market.renewal_lc_pct,
            free_rent_months=renewal_free,
            recovery_type=recovery_type,
            recovery_overrides=recovery_overrides,
            expense_stop_per_sf=stop_per_sf,
            pro_rata_share=pro_rata_share,
            rent_payment_frequency=market.rent_payment_frequency,
            rent_basis=market.rent_basis,
            rent_step_pcts=market.lease_rent_steps,
            term_months=market.renewal_term_months,
            base_year=_base_year(analysis, renewal_start, recovery_type, recovery_overrides),
            escalation_per_unit=market.lease_escalation_per_unit,
        )
        all_lease_inputs.append(renewal_lease)

        renewal_slices = project_lease_cash_flows(
            renewal_lease, analysis,
            cpi_assumption=cpi_assumption,
            scenario_label="renewal",
            scenario_weight=renewal_weight,
        )
        _apply_fractional_free_rent(renewal_slices, renewal_start, renewal_free)
        _add_ti_lc_to_first_slice(
            renewal_slices, renewal_lease, market.renewal_term_months, renewal_free,
            market.renewal_ti_per_sf, market.renewal_lc_pct, market.renewal_lc_per_sf,
            _leasing_cost_factor(market, analysis, renewal_start), market.lc_includes_escalations,
            market.lease_rent_steps, market.lease_escalation_per_unit, market.renewal_lc_pct_by_lease_year,
        )
        all_slices.extend(renewal_slices)

        # Recurse when renewal lease expires within analysis period
        if renewal_end_raw < analysis.end_date:
            next_vacancy = renewal_end_raw + timedelta(days=1)
            rec_slices, rec_leases = generate_speculative_leases(
                suite=suite,
                vacancy_start_date=next_vacancy,
                analysis=analysis,
                market=next_market,
                original_recovery_type=recovery_type,
                original_pro_rata_share=pro_rata_share,
                original_recovery_overrides=recovery_overrides,
                original_expense_stop_per_sf=stop_per_sf,
                cpi_assumption=cpi_assumption,
                generation=generation + 1,
                cumulative_weight=renewal_weight,
                branch_path=f"{branch_path}R",
                market_map=market_map,
                prior_rent=_next_prior(renewal_lease, renewal_end_raw, next_market, suite.area, cpi_assumption),
            )
            all_slices.extend(rec_slices)
            all_lease_inputs.extend(rec_leases)

    # ===== NEW TENANT SCENARIO =====
    new_weight = cumulative_weight * new_prob
    if new_weight > Decimal("0.0001"):
        # Downtime: vacant period before new tenant commences
        downtime = (
            int(rate_for_year(market.downtime_months, market.downtime_schedule, expiry_year))
            if downtime_months_override is None else downtime_months_override
        )
        new_tenant_start = add_months(vacancy_start_date, downtime)

        # Vacancy slices during downtime
        if downtime > 0 and vacancy_start_date < new_tenant_start:
            downtime_end = min(new_tenant_start - timedelta(days=1), analysis.end_date)
            vacancy_slices = make_vacant_slices(
                suite_id=suite.suite_id,
                start_date=vacancy_start_date,
                end_date=downtime_end,
                analysis=analysis,
                scenario_label="vacant",
                scenario_weight=new_weight,
            )
            all_slices.extend(vacancy_slices)

        if new_tenant_start <= analysis.end_date:
            new_rent = _market_rent_at(market, analysis, new_tenant_start)
            new_rent = max(new_rent, Decimal(0))

            new_end_raw = add_months(new_tenant_start, market.new_lease_term_months) - timedelta(days=1)
            new_end = min(new_end_raw, analysis.end_date)

            new_free = _free_rent_months(market, analysis, new_tenant_start)[1]
            new_lease = _build_speculative_lease(
                suite=suite,
                lease_id=f"spec_new_{suite.suite_id}_g{generation}_{branch_path}N",
                tenant_label=f"New Tenant (Gen {generation + 1})",
                start_date=new_tenant_start,
                end_date=new_end,
                rent=new_rent,
                growth_rate=_lease_escalation_at(market, analysis, new_tenant_start),
                ti_per_sf=market.new_ti_per_sf,
                lc_pct=market.new_lc_pct,
                free_rent_months=new_free,
                recovery_type=recovery_type,
                recovery_overrides=recovery_overrides,
                expense_stop_per_sf=stop_per_sf,
                pro_rata_share=pro_rata_share,
                rent_payment_frequency=market.rent_payment_frequency,
                rent_basis=market.rent_basis,
                rent_step_pcts=market.lease_rent_steps,
                term_months=market.new_lease_term_months,
                base_year=_base_year(analysis, new_tenant_start, recovery_type, recovery_overrides),
                escalation_per_unit=market.lease_escalation_per_unit,
            )
            all_lease_inputs.append(new_lease)

            new_slices = project_lease_cash_flows(
                new_lease, analysis,
                cpi_assumption=cpi_assumption,
                scenario_label="new_tenant",
                scenario_weight=new_weight,
            )
            _apply_fractional_free_rent(new_slices, new_tenant_start, new_free)
            _add_ti_lc_to_first_slice(
                new_slices, new_lease, market.new_lease_term_months, new_free,
                market.new_ti_per_sf, market.new_lc_pct, market.new_lc_per_sf,
                _leasing_cost_factor(market, analysis, new_tenant_start), market.lc_includes_escalations,
                market.lease_rent_steps, market.lease_escalation_per_unit, market.new_lc_pct_by_lease_year,
            )
            all_slices.extend(new_slices)

            # Recurse when new tenant lease expires within analysis period
            if new_end_raw < analysis.end_date:
                next_vacancy = new_end_raw + timedelta(days=1)
                rec_slices, rec_leases = generate_speculative_leases(
                    suite=suite,
                    vacancy_start_date=next_vacancy,
                    analysis=analysis,
                    market=next_market,
                    original_recovery_type=recovery_type,
                    original_pro_rata_share=pro_rata_share,
                    original_recovery_overrides=recovery_overrides,
                    original_expense_stop_per_sf=stop_per_sf,
                    cpi_assumption=cpi_assumption,
                    generation=generation + 1,
                    cumulative_weight=new_weight,
                    branch_path=f"{branch_path}N",
                    market_map=market_map,
                    prior_rent=_next_prior(new_lease, new_end_raw, next_market, suite.area, cpi_assumption),
                )
                all_slices.extend(rec_slices)
                all_lease_inputs.extend(rec_leases)

    return all_slices, all_lease_inputs


def _blended_rollover(
    suite: SuiteInput,
    vacancy_start_date: date,
    analysis: AnalysisPeriod,
    market: MarketAssumptions,
    next_market: MarketAssumptions,
    renewal_prob: Decimal,
    expiry_year: int,
    recovery_terms: tuple[str, tuple[ExpenseRecoveryOverride, ...], Decimal | None, Decimal | None],
    renewal_rent_spread_override: Decimal | None,
    cpi_assumption: Decimal,
    generation: int,
    cumulative_weight: Decimal,
    branch_path: str,
    market_map: dict[str, MarketAssumptions] | None,
    downtime_months_override: int | None,
    prior_rent: Decimal | None = None,
) -> tuple[list[MonthlySlice], list[LeaseInput]]:
    """
    published DCF software-style market leasing: one lease whose downtime, rent, free rent, TI and LC are the
    renewal and new-tenant terms weighted by the renewal probability. Months vacant round to whole
    months, free rent may be a fraction of a month; term and rent steps follow the new-tenant terms.
    """
    new_prob = Decimal(1) - renewal_prob
    recovery_type, recovery_overrides, stop_per_sf, pro_rata_share = recovery_terms

    def weighted(renewal: Decimal, new: Decimal) -> Decimal:
        return renewal_prob * renewal + new_prob * new

    def whole_months(renewal: int, new: int) -> int:
        return int(weighted(Decimal(renewal), Decimal(new)).quantize(Decimal(1), rounding=ROUND_HALF_UP))

    if downtime_months_override is None:   # renewals have no downtime
        downtime = whole_months(0, int(rate_for_year(market.downtime_months, market.downtime_schedule, expiry_year)))
    else:
        downtime = downtime_months_override
    start_raw = add_months(vacancy_start_date, downtime)
    slices: list[MonthlySlice] = []
    if downtime > 0:
        slices.extend(make_vacant_slices(
            suite_id=suite.suite_id,
            start_date=vacancy_start_date,
            end_date=min(start_raw - timedelta(days=1), analysis.end_date),
            analysis=analysis,
            scenario_label="vacant",
            scenario_weight=cumulative_weight,
        ))
    if start_raw > analysis.end_date:
        return slices, []

    spread = (
        renewal_rent_spread_override if renewal_rent_spread_override is not None
        else market.renewal_rent_adjustment_pct
    )
    market_rent = _market_rent_at(market, analysis, start_raw)
    if prior_rent is None or market.renewal_rent_rule == "market":
        rent = market_rent * weighted(Decimal(1) + spread, Decimal(1))
    else:   # the renewal rent rule applies to the renewal share before weighting
        rent = weighted(_renewal_rent(market, max(market_rent * (Decimal(1) + spread), Decimal(0)), prior_rent),
                        market_rent)
    free_months = weighted(*_free_rent_months(market, analysis, start_raw))
    end_raw = add_months(start_raw, market.new_lease_term_months) - timedelta(days=1)
    lease = _build_speculative_lease(
        suite=suite,
        lease_id=f"spec_blend_{suite.suite_id}_g{generation}_{branch_path}B",
        tenant_label=f"Market Lease (Gen {generation + 1})",
        start_date=start_raw,
        end_date=min(end_raw, analysis.end_date),
        rent=max(rent, Decimal(0)),
        growth_rate=_lease_escalation_at(market, analysis, start_raw),
        ti_per_sf=Decimal(0),
        lc_pct=Decimal(0),
        free_rent_months=free_months,
        recovery_type=recovery_type,
        recovery_overrides=recovery_overrides,
        expense_stop_per_sf=stop_per_sf,
        pro_rata_share=pro_rata_share,
        rent_payment_frequency=market.rent_payment_frequency,
        rent_basis=market.rent_basis,
        rent_step_pcts=market.lease_rent_steps,
        term_months=market.new_lease_term_months,
        base_year=_base_year(analysis, start_raw, recovery_type, recovery_overrides),
        escalation_per_unit=market.lease_escalation_per_unit,
    )
    lease_slices = project_lease_cash_flows(
        lease, analysis,
        cpi_assumption=cpi_assumption,
        scenario_label="blended",
        scenario_weight=cumulative_weight,
    )
    _apply_fractional_free_rent(lease_slices, start_raw, free_months)
    _add_ti_lc_to_first_slice(
        lease_slices, lease, market.new_lease_term_months, free_months,
        weighted(market.renewal_ti_per_sf, market.new_ti_per_sf),
        weighted(market.renewal_lc_pct, market.new_lc_pct),
        weighted(market.renewal_lc_per_sf, market.new_lc_per_sf),
        _leasing_cost_factor(market, analysis, start_raw), market.lc_includes_escalations,
        market.lease_rent_steps, market.lease_escalation_per_unit,
        _weighted_lc_by_lease_year(market, weighted),
    )
    slices.extend(lease_slices)
    leases = [lease]
    if end_raw < analysis.end_date:
        rec_slices, rec_leases = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=end_raw + timedelta(days=1),
            analysis=analysis,
            market=next_market,
            original_recovery_type=recovery_type,
            original_pro_rata_share=pro_rata_share,
            original_recovery_overrides=recovery_overrides,
            original_expense_stop_per_sf=stop_per_sf,
            cpi_assumption=cpi_assumption,
            generation=generation + 1,
            cumulative_weight=cumulative_weight,
            branch_path=f"{branch_path}B",
            market_map=market_map,
            prior_rent=_next_prior(lease, end_raw, next_market, suite.area, cpi_assumption),
        )
        slices.extend(rec_slices)
        leases.extend(rec_leases)
    return slices, leases


def _weighted_lc_by_lease_year(market: MarketAssumptions, weighted) -> tuple[Decimal, ...]:
    """Blended leasing: each lease year's commission rate weighted between renewal and new tenant
    (a side without rates by lease year uses its single rate). Empty when neither side has them."""
    renewal, new = market.renewal_lc_pct_by_lease_year, market.new_lc_pct_by_lease_year
    if not renewal and not new:
        return ()

    def at(rates: tuple[Decimal, ...], single: Decimal, year: int) -> Decimal:
        return rates[min(year, len(rates) - 1)] if rates else single

    return tuple(
        weighted(at(renewal, market.renewal_lc_pct, y), at(new, market.new_lc_pct, y))
        for y in range(max(len(renewal), len(new)))
    )


def generate_option_lease(
    suite: SuiteInput,
    source_lease: LeaseInput,
    start_date: date,
    analysis: AnalysisPeriod,
    market: MarketAssumptions | None,
    cpi_assumption: Decimal = Decimal("0.025"),
) -> tuple[list[MonthlySlice], list[LeaseInput], date]:
    """
    Contract renewal option exercised at expiry (probability 1).

    Rent is the lease's option rent, or market rent at exercise adjusted by the
    renewal spread when none is given. Returns (slices, lease_inputs, option_end).
    """
    term = source_lease.option_term_months or (market.renewal_term_months if market else 60)
    end_raw = add_months(start_date, term) - timedelta(days=1)
    rent = source_lease.option_rent_per_unit
    rent_basis = source_lease.rent_basis
    frequency = source_lease.rent_payment_frequency
    if rent is None:
        if market is None:
            return [], [], end_raw
        spread = (
            source_lease.renewal_rent_spread_override
            if source_lease.renewal_rent_spread_override is not None
            else market.renewal_rent_adjustment_pct
        )
        rent = max(Decimal(0), _market_rent_at(market, analysis, start_date) * (Decimal(1) + spread))
        rent_basis = market.rent_basis
        frequency = market.rent_payment_frequency
    # The option continues the lease's per-category terms; a stop that resets to the option's base
    # year drops any fixed base-year amount
    option_recovery_type, option_overrides = _reset_stop(
        source_lease.recovery_type, source_lease.recovery_overrides, source_lease.expense_stop_per_sf)
    option_overrides = _rebase(option_overrides)
    option_lease = _build_speculative_lease(
        suite=suite,
        lease_id=f"option_{source_lease.lease_id}",
        tenant_label=source_lease.tenant_name or "Option Renewal",
        start_date=start_date,
        end_date=min(end_raw, analysis.end_date),
        rent=rent,
        growth_rate=_lease_escalation_at(market, analysis, start_date) if market else Decimal(0),
        ti_per_sf=source_lease.option_ti_per_sf,
        lc_pct=source_lease.option_lc_pct,
        free_rent_months=0,
        recovery_type=option_recovery_type,
        recovery_overrides=option_overrides,
        expense_stop_per_sf=source_lease.expense_stop_per_sf,
        # The option is a new lease term: its base year resets to the year it starts
        base_year=_base_year(analysis, start_date, option_recovery_type, option_overrides),
        pro_rata_share=source_lease.pro_rata_share,
        rent_payment_frequency=frequency,
        rent_basis=rent_basis,
    )
    # Growing recovery caps keep growing from the original lease's start
    option_lease = replace(option_lease, recovery_cap_start=source_lease.recovery_cap_start or source_lease.start_date)
    slices = project_lease_cash_flows(
        option_lease, analysis,
        cpi_assumption=cpi_assumption,
        scenario_label="option",
        scenario_weight=Decimal(1),
    )
    _add_ti_lc_to_first_slice(slices, option_lease, term, 0, source_lease.option_ti_per_sf, source_lease.option_lc_pct)
    return slices, [option_lease], end_raw
