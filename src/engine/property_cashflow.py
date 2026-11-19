"""
Master DCF engine orchestrator.

This is the top-level function called by the service layer.
It coordinates: lease projection → renewal generation → expense recovery
→ waterfall aggregation → terminal value → DCF → IRR.

All inputs are pure engine dataclasses (no DB, no Pydantic).
All outputs are engine result dataclasses.
"""
from __future__ import annotations

from dataclasses import fields, replace
from datetime import date, timedelta
from decimal import Decimal

from src.engine.date_utils import (
    add_months,
    build_analysis_period,
    build_monthly_buckets,
    end_of_month,
    fiscal_year_for_month,
    months_between,
)
from src.engine.dcf import (
    build_debt_schedule_detail,
    build_monthly_debt_detail,
    calculate_irr,
    calculate_terminal_value_breakdown,
    discount_cash_flows,
    discount_monthly_cash_flows,
    equity_multiple as _equity_multiple,
    going_in_cap_rate,
    irr_from_series,
)
from src.engine.expense_engine import (
    _effective_recovery_type, _has_stop_reference, attach_expense_recoveries, recovery_occupancy_context,
)
from src.engine.recovery_pools import (
    deducting_pools_excluding, excluded_net_fees, excluded_recoveries, lease_pool_shares, pool_denominators, pool_occupancies,
)
from src.engine.growth import market_rent_at_year, rate_for_year
from src.engine.lease_projector import make_vacant_slices, project_lease_cash_flows
from src.engine.renewal_engine import (
    _base_year, _market_recovery, generate_option_lease, generate_speculative_leases, last_contract_rent,
    prior_rent_in_market_units,
)
from src.engine.returns import compute_investment_returns, direct_cap_value
from src.engine.types import (
    rent_area,
    AnalysisPeriod,
    AnnualPropertyCashFlow,
    EngineResult,
    ExpenseInput,
    LeaseInput,
    MarketAssumptions,
    MonthlySlice,
    SuiteInput,
    ValuationParams,
    RecoveryPoolInput,
)
from src.engine.waterfall import build_annual_waterfall, compute_occupancy_by_month


def _suites_with_market(suites: list[SuiteInput], market_map: dict[str, MarketAssumptions]) -> list[SuiteInput]:
    """Return suites that have a matching market leasing profile."""
    return [s for s in suites if s.space_type in market_map]


def _recovery_source(lease: LeaseInput | None) -> dict:
    """The expiring lease's recovery terms, which market leases follow under "same as expiring lease"."""
    if lease is None:
        return dict(original_recovery_type="nnn")
    return dict(original_recovery_type=lease.recovery_type, original_pro_rata_share=lease.pro_rata_share,
                original_recovery_overrides=lease.recovery_overrides,
                original_expense_stop_per_sf=lease.expense_stop_per_sf)


def _rollover(
    suite: SuiteInput,
    start_date,
    analysis: AnalysisPeriod,
    market: MarketAssumptions | None,
    mode: str,
    source_lease: LeaseInput | None,
    cpi_assumption: Decimal,
    market_map: dict[str, MarketAssumptions] | None,
    cpi_schedule: tuple[Decimal, ...] = (),
) -> tuple[list[MonthlySlice], list[LeaseInput]]:
    """
    Cash flows for a suite from `start_date` to the end of the analysis, after
    `source_lease` expires (or while the suite is vacant), per upon-expiration mode:
      market   - probability-weighted renewal / new tenant (lease overrides apply)
      renew    - renewal at 100% probability
      vacate   - tenant leaves: downtime, then a new tenant
      option   - contract renewal option, then market
      reabsorb - space returns to vacancy; re-leased only through suite lease-up
      lease_up - vacant space leased per the suite's lease-up assumptions
    """
    recovery_source = _recovery_source(source_lease)

    if mode == "reabsorb" and suite.has_lease_up:
        mode = "lease_up"
    if mode == "reabsorb":
        # Not offered for lease: vacant, but not absorption & turnover vacancy
        return make_vacant_slices(suite.suite_id, start_date, analysis.end_date, analysis, "reabsorbed"), []
    if market is None and mode != "option":
        return make_vacant_slices(suite.suite_id, start_date, analysis.end_date, analysis), []

    if mode == "lease_up":
        # Vacant until leasing begins, then lease_up_months (or MLA downtime) to a new tenant
        slices: list[MonthlySlice] = []
        leasing_start = max(start_date, suite.absorption_start_date or start_date)
        if leasing_start > analysis.end_date:
            return make_vacant_slices(suite.suite_id, start_date, analysis.end_date, analysis), []
        if leasing_start > start_date:
            slices.extend(make_vacant_slices(
                suite.suite_id, start_date, leasing_start - timedelta(days=1), analysis,
            ))
        spec_slices, spec_leases = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=leasing_start,
            analysis=analysis,
            market=market,
            **recovery_source,
            renewal_probability_override=Decimal(0),
            cpi_assumption=cpi_assumption,
            market_map=market_map,
            downtime_months_override=suite.lease_up_months,
            branch_path=f"{leasing_start:%Y%m%d}_",
        )
        return slices + spec_slices, spec_leases

    slices: list[MonthlySlice] = []
    leases: list[LeaseInput] = []
    if mode == "option" and source_lease is not None:
        opt_slices, opt_leases, opt_end = generate_option_lease(
            suite, source_lease, start_date, analysis, market, cpi_assumption,
        )
        if not opt_leases:  # no option rent and no market to price it
            return make_vacant_slices(suite.suite_id, start_date, analysis.end_date, analysis), []
        slices.extend(opt_slices)
        leases.extend(opt_leases)
        if opt_end >= analysis.end_date:
            return slices, leases
        start_date = opt_end + timedelta(days=1)
        if market is None:
            slices.extend(make_vacant_slices(suite.suite_id, start_date, analysis.end_date, analysis))
            return slices, leases
        source_lease = None  # after the option, market assumptions apply without lease overrides
        recovery_source = _recovery_source(opt_leases[0])  # the option's terms expire next
        prior_rent = _prior_rent(opt_leases[0], opt_end, market, suite, analysis, cpi_assumption)
    elif source_lease is not None and source_lease.end_date < start_date:
        prior_rent = _prior_rent(source_lease, source_lease.end_date, market, suite, analysis,
                                 cpi_assumption, cpi_schedule)
    else:
        prior_rent = None  # vacant space, or a gap before the suite's next lease

    probability = source_lease.renewal_probability_override if source_lease else None
    if mode == "renew":
        probability = Decimal(1)
    elif mode == "vacate":
        probability = Decimal(0)
    spec_slices, spec_leases = generate_speculative_leases(
        suite=suite,
        vacancy_start_date=start_date,
        analysis=analysis,
        market=market,
        **recovery_source,
        renewal_probability_override=probability,
        renewal_rent_spread_override=source_lease.renewal_rent_spread_override if source_lease else None,
        cpi_assumption=cpi_assumption,
        market_map=market_map,
        # A suite can roll over more than once (a gap, then after its last lease);
        # the start date keeps each rollover's lease ids distinct.
        branch_path=f"{start_date:%Y%m%d}_",
        prior_rent=prior_rent,
    )
    slices.extend(spec_slices)
    leases.extend(spec_leases)
    return slices, leases


def _attach_committed_costs(lease: LeaseInput, slices: list[MonthlySlice], analysis: AnalysisPeriod) -> None:
    """Committed TI/LC on an in-place lease: paid at lease start, or at analysis start if already begun."""
    if not slices or (lease.committed_ti_amount == 0 and lease.committed_lc_amount == 0):
        return
    pay_date = max(lease.start_date, analysis.start_date)
    target = next((s for s in slices if s.period_start <= pay_date <= s.period_end), slices[0])
    target.ti_cost -= lease.committed_ti_amount
    target.lc_cost -= lease.committed_lc_amount


def _prior_rent(
    lease: LeaseInput, end_date, market: MarketAssumptions | None, suite: SuiteInput,
    analysis: AnalysisPeriod, cpi_assumption: Decimal, cpi_schedule: tuple[Decimal, ...] = (),
) -> Decimal | None:
    """The expiring lease's last rent in the market profile's units, when the profile's renewal
    rent rule compares with it."""
    if market is None or market.renewal_rent_rule == "market":
        return None
    rent = last_contract_rent(lease, end_date, cpi_assumption, cpi_schedule, analysis.start_date)
    return prior_rent_in_market_units(lease, rent, market, suite.area)


def _project_suite(
    suite: SuiteInput,
    suite_leases: list[LeaseInput],
    analysis: AnalysisPeriod,
    market: MarketAssumptions | None,
    cpi_assumption: Decimal,
    cpi_schedule: tuple[Decimal, ...] = (),
    market_map: dict[str, MarketAssumptions] | None = None,
) -> tuple[list[MonthlySlice], list[LeaseInput]]:
    """
    Project all monthly slices for a single suite.

    Strategy:
    1. Sort leases by start date.
    2. For each in-place lease, project its cash flows.
    3. Track "coverage" — which months are covered by in-place leases.
    4. For gaps (before first lease, between leases, after last lease):
       - If market assumptions exist: generate probability-weighted speculative leases.
       - Else: generate vacancy slices.

    Returns:
        (slices, speculative_lease_inputs) — all monthly slices for the suite,
        plus the LeaseInput objects created for speculative leases so the caller
        can attach expense recoveries to them.
    """
    all_slices: list[MonthlySlice] = []
    all_spec_leases: list[LeaseInput] = []

    sorted_leases = sorted(suite_leases, key=lambda l: l.start_date)
    previous_lease: LeaseInput | None = None

    # Track gaps relative to in-place leases
    current_date = analysis.start_date

    for lease in sorted_leases:
        lease_start_in_period = max(lease.start_date, analysis.start_date)
        lease_end_in_period = min(lease.end_date, analysis.end_date)

        # Skip overlapping leases: if this lease starts before the previous one ended,
        # advance current_date past the overlap to avoid double-counting rent.
        if lease_start_in_period < current_date:
            lease_end_in_period = max(lease_end_in_period, current_date - timedelta(days=1))
            if lease_end_in_period < current_date:
                continue  # entirely overlapped by prior lease

        # Gap before this lease
        if current_date < lease_start_in_period and previous_lease is None and not suite.has_lease_up:
            # Vacant until its first lease (published DCF software): not offered for lease, so no turnover vacancy
            all_slices.extend(make_vacant_slices(
                suite.suite_id, current_date, lease_start_in_period - timedelta(days=1), analysis, "reabsorbed",
            ))
        elif current_date < lease_start_in_period:
            source_lease = previous_lease  # None before the first lease: space never leased
            if previous_lease is not None:
                mode = previous_lease.upon_expiration
            else:
                mode = "lease_up" if suite.has_lease_up else "market"
            spec_slices, spec_leases = _rollover(
                suite, current_date, analysis, market, mode, source_lease, cpi_assumption, market_map, cpi_schedule,
            )
            # Filter slices to gap only
            gap_slices = [s for s in spec_slices if s.period_end < lease_start_in_period]
            all_slices.extend(gap_slices)
            # Only include lease inputs for leases that have slices in this gap
            included_ids = {s.lease_id for s in gap_slices}
            all_spec_leases.extend(l for l in spec_leases if l.lease_id in included_ids)

        # Project in-place lease
        if lease.start_date <= analysis.end_date and lease.end_date >= analysis.start_date:
            slices = project_lease_cash_flows(
                lease, analysis,
                cpi_assumption=cpi_assumption,
                scenario_label="in_place",
                scenario_weight=Decimal(1),
                cpi_schedule=cpi_schedule,
            )
            # Months already covered by the prior lease belong to it alone.
            slices = [s for s in slices if s.period_end >= current_date]
            _attach_committed_costs(lease, slices, analysis)
            all_slices.extend(slices)

        current_date = lease_end_in_period + timedelta(days=1)
        previous_lease = lease

    # Gap after all in-place leases (post-expiry speculative leasing)
    if current_date <= analysis.end_date:
        last_lease = sorted_leases[-1] if sorted_leases else None
        spec_slices, spec_leases = _rollover(
            suite, current_date, analysis, market,
            last_lease.upon_expiration if last_lease else ("lease_up" if suite.has_lease_up else "market"),
            last_lease, cpi_assumption, market_map, cpi_schedule,
        )
        all_slices.extend(spec_slices)
        all_spec_leases.extend(spec_leases)

    return all_slices, all_spec_leases


def _project_suite_by_occupancy(
    suite: SuiteInput,
    suite_leases: list[LeaseInput],
    analysis: AnalysisPeriod,
    market: MarketAssumptions,
    cpi_assumption: Decimal,
    cpi_schedule: tuple[Decimal, ...] = (),
) -> tuple[list[MonthlySlice], list[LeaseInput]]:
    """
    Occupancy-based projection for multifamily/self-storage.

    During in-place lease terms: uses actual contract rent (same as commercial).
    After lease expiry: revenue = market_rent × units, with general vacancy
    handled in the waterfall. Turnover costs are spread as monthly TI.
    Market concessions support two modes:
      - blended (default): expected drag using renewal probability
      - timed: explicit concession months by analysis year (Y1-Y5 + stabilized)
    """
    all_slices: list[MonthlySlice] = []
    sorted_leases = sorted(suite_leases, key=lambda l: l.start_date)

    # Turnover cost: turnover_rate × units × cost_per_turn / 12
    turnover_rate = Decimal(1) - market.renewal_probability
    cost_per_turn = market.new_ti_per_sf  # reuse TI field as $/unit turnover cost
    monthly_turnover = -(turnover_rate * suite.area * cost_per_turn / Decimal(12))
    blended_concession_months = (
        turnover_rate * Decimal(str(market.new_free_rent_months))
        + market.renewal_probability * Decimal(str(market.renewal_free_rent_months))
    )

    def _timed_concession_months(year_number: int) -> Decimal | None:
        if year_number <= 1:
            return market.concession_year1_months
        if year_number == 2:
            return market.concession_year2_months
        if year_number == 3:
            return market.concession_year3_months
        if year_number == 4:
            return market.concession_year4_months
        if year_number == 5:
            return market.concession_year5_months
        return market.concession_stabilized_months

    def _concession_drag_pct_for_year(year_number: int, blended_months: Decimal) -> Decimal:
        concession_months = blended_months
        if (market.concession_timing_mode or "blended") == "timed":
            timed = _timed_concession_months(year_number)
            if timed is not None:
                concession_months = timed
        drag_pct = concession_months / Decimal(12)
        return max(Decimal(0), min(Decimal(1), drag_pct))

    # Project in-place leases for their active terms
    in_place_months: set[int] = set()  # month_index values covered by in-place leases
    for lease in sorted_leases:
        if lease.start_date <= analysis.end_date and lease.end_date >= analysis.start_date:
            slices = project_lease_cash_flows(
                lease, analysis,
                cpi_assumption=cpi_assumption,
                scenario_label="in_place",
                scenario_weight=Decimal(1),
                cpi_schedule=cpi_schedule,
            )
            _attach_committed_costs(lease, slices, analysis)
            for s in slices:
                in_place_months.add(s.month_index)
                # Multifamily/storage concession drag applies to occupied months,
                # including in-place rent roll months.
                fy = fiscal_year_for_month(analysis, s.period_start)
                fy_num = fy.year_number if fy else 1
                concession_drag_pct = _concession_drag_pct_for_year(
                    fy_num, blended_concession_months
                )
                concession_adj = -(s.base_rent * concession_drag_pct)
                s.free_rent_adjustment += concession_adj
                s.effective_rent = max(Decimal(0), s.base_rent + s.free_rent_adjustment)
            all_slices.extend(slices)

    # Fill non-in-place months with occupancy-based market rent
    for month_idx in range(analysis.num_months):
        if month_idx in in_place_months:
            continue

        period_start = add_months(analysis.start_date, month_idx)
        period_end = end_of_month(period_start)
        if period_start > analysis.end_date:
            break

        # Determine fiscal year for market rent growth
        fy = fiscal_year_for_month(analysis, period_start)
        fy_num = fy.year_number if fy else 1

        grown_rent = market_rent_at_year(
            market.market_rent_per_unit, market.rent_growth_rate, fy_num, market.rent_growth_schedule
        )
        # For monthly-basis (multifamily/storage): rent × units
        units = rent_area(suite.area, market.rent_basis)
        if market.rent_payment_frequency == "monthly":
            monthly_revenue = grown_rent * units
        else:
            monthly_revenue = grown_rent * units / Decimal(12)

        concession_drag_pct = _concession_drag_pct_for_year(
            fy_num, blended_concession_months
        )
        free_rent_adj = -(monthly_revenue * concession_drag_pct)
        effective_revenue = monthly_revenue + free_rent_adj

        all_slices.append(MonthlySlice(
            month_index=month_idx,
            period_start=period_start,
            period_end=period_end,
            suite_id=suite.suite_id,
            lease_id=f"mkt_occ_{suite.suite_id}",
            tenant_name="Market Occupancy",
            base_rent=monthly_revenue,
            free_rent_adjustment=free_rent_adj,
            effective_rent=effective_revenue,
            expense_recovery=Decimal(0),  # attached later by expense engine
            percentage_rent=Decimal(0),
            ti_cost=monthly_turnover,
            lc_cost=Decimal(0),
            is_vacant=False,
            scenario_label="market_occupancy",
            scenario_weight=Decimal(1),  # full weight; waterfall handles vacancy %
        ))

    return all_slices, []  # no speculative lease inputs needed


def _estimate_forward_noi(
    annual_cfs: list[AnnualPropertyCashFlow],
    expenses: list[ExpenseInput],
    market_map: dict[str, MarketAssumptions],
    suites: list[SuiteInput],
) -> Decimal:
    """
    Estimate year N+1 NOI for terminal value by growing revenue and expense
    components separately rather than applying a single growth factor to NOI.

    Revenue (GPR, pct_rent) grows by the area-weighted market rent growth rate.
    Expense recoveries and operating expenses grow by the expense-weighted
    average expense growth rate.

    This correctly handles NNN leases (recovery and expense both grow at the
    same rate so they net to zero), FSG leases (expense grows but no recovery
    passes through), and mixed portfolios.
    """
    if not annual_cfs:
        return Decimal(0)
    last = annual_cfs[-1]
    forward_year = len(annual_cfs) + 1

    # Blended expense growth rate (weighted by base amount)
    non_egi_exps = [e for e in expenses if not e.is_pct_of_egi]
    total_exp_base = sum(e.base_amount for e in non_egi_exps)
    exp_growth = (
        sum(
            e.base_amount * rate_for_year(e.growth_rate, e.growth_schedule, forward_year)
            for e in non_egi_exps
        ) / total_exp_base
        if total_exp_base > Decimal(0)
        else Decimal("0.03")
    )

    # Blended rent growth rate (area-weighted across market assumptions)
    total_area = sum(s.area for s in suites)
    rent_growth = (
        sum(
            s.area * rate_for_year(
                market_map[s.space_type].rent_growth_rate,
                market_map[s.space_type].rent_growth_schedule,
                forward_year,
            )
            for s in suites
            if s.space_type in market_map
        ) / total_area
        if total_area > Decimal(0) and market_map
        else exp_growth
    )

    # Grow revenue components by rent growth; expenses/recoveries by expense growth
    forward_gpr = last.gross_potential_rent * (Decimal(1) + rent_growth)
    forward_recoveries = last.expense_recoveries * (Decimal(1) + exp_growth)
    forward_pct_rent = last.percentage_rent * (Decimal(1) + rent_growth)
    forward_other_income = last.other_income * (Decimal(1) + rent_growth)
    forward_gpi = forward_gpr + forward_recoveries + forward_pct_rent + forward_other_income

    # Apply the same vacancy/credit loss rates as last year (based on GPR)
    if last.gross_potential_rent > Decimal(0):
        vac_rate = -last.general_vacancy_loss / last.gross_potential_rent
        credit_rate = -last.credit_loss / last.gross_potential_rent
    else:
        vac_rate = Decimal("0.05")
        credit_rate = Decimal("0.01")
    forward_egi = forward_gpi - forward_gpr * vac_rate - forward_gpr * credit_rate

    # Grow operating expenses (management fee is implicit in last.operating_expenses)
    forward_opex = (-last.operating_expenses) * (Decimal(1) + exp_growth)

    return forward_egi - forward_opex


def _vacancy_exclusions(
    suites: list[SuiteInput],
    leases: list[LeaseInput],
    speculative_leases: list[LeaseInput],
    market_assumptions: dict[str, MarketAssumptions],
) -> tuple[frozenset[str], frozenset[str]]:
    """
    Leases excluded from general vacancy and credit loss, and the suites whose downtime does
    not count against general vacancy: tenants flagged as excluded, every lease in suites whose
    market profile is excluded, and market leases following an excluded tenant whose exclusion
    does not end at rollover.
    """
    mla_suites = {
        s.suite_id for s in suites
        if (m := market_assumptions.get(s.space_type)) is not None and m.exclude_from_general_vacancy
    }
    last_lease: dict[str, LeaseInput] = {}
    for lease in leases:
        if lease.suite_id not in last_lease or lease.end_date > last_lease[lease.suite_id].end_date:
            last_lease[lease.suite_id] = lease
    carried = {
        sid for sid, lease in last_lease.items()
        if lease.exclude_from_general_vacancy and not lease.vacancy_exclusion_ends_at_rollover
    }
    suites_excluded = frozenset(mla_suites | carried)
    lease_ids = [l.lease_id for l in leases if l.exclude_from_general_vacancy or l.suite_id in mla_suites]
    lease_ids += [l.lease_id for l in speculative_leases if l.suite_id in suites_excluded]
    return suites_excluded, frozenset(lease_ids)


def _fill_turnover_vacancy(
    suite_slices: dict[str, list[MonthlySlice]],
    suites: list[SuiteInput],
    market_assumptions: dict[str, MarketAssumptions],
    analysis: AnalysisPeriod,
    leases_by_suite: dict[str, list[LeaseInput]],
) -> list[LeaseInput]:
    """
    Full occupancy: months vacant between leases become occupied at market rent by a market lease
    paying recoveries on the terms a market lease there would get (the profile's recovery structure,
    else the expiring lease's terms), with its base year in the year each vacancy starts.
    Space taken off the market (reabsorbed) stays vacant. Returns the fill leases, for recoveries.
    """
    leases: list[LeaseInput] = []
    for suite in suites:
        market = market_assumptions.get(suite.space_type)
        if market is None:
            continue
        vacant = sorted((s for s in suite_slices[suite.suite_id] if s.is_vacant and s.scenario_label == "vacant"),
                        key=lambda s: s.period_start)
        runs: list[list[MonthlySlice]] = []   # contiguous vacancies, each filled by its own lease
        for s in vacant:
            if runs and s.period_start <= runs[-1][-1].period_end + timedelta(days=1):
                runs[-1].append(s)
            else:
                runs.append([s])
        for run in runs:
            start = run[0].period_start
            lease_id = f"full_occupancy_{suite.suite_id}_{start:%Y%m%d}"
            for s in run:
                year = fiscal_year_for_month(analysis, s.period_start).year_number
                rent = market_rent_at_year(market.market_rent_per_unit, market.rent_growth_rate, year,
                                           market.rent_growth_schedule)
                units = rent_area(suite.area, market.rent_basis)
                monthly = rent * units if market.rent_payment_frequency == "monthly" else rent * units / 12
                monthly *= s.month_fraction
                s.is_vacant = False
                s.lease_id = lease_id
                s.scenario_label = "full_occupancy"
                s.base_rent = monthly
                s.effective_rent = monthly
            expired = [l for l in leases_by_suite.get(suite.suite_id, []) if l.end_date < start]
            source = max(expired, key=lambda l: l.end_date) if expired else None
            rtype, overrides, stop, share = _market_recovery(
                market, source.recovery_type, source.recovery_overrides, source.expense_stop_per_sf,
                source.pro_rata_share,
            ) if source else _market_recovery(market, "nnn")
            leases.append(LeaseInput(
                lease_id=lease_id, suite_id=suite.suite_id, tenant_name="Full occupancy", area=suite.area,
                start_date=start, end_date=max(s.period_end for s in run), base_rent_per_unit=Decimal(0),
                rent_payment_frequency=market.rent_payment_frequency, escalation_type="flat",
                escalation_pct=None, cpi_floor=None, cpi_cap=None, rent_steps=(), free_rent_periods=(),
                recovery_type=rtype, pro_rata_share=share, base_year_stop_amount=None,
                expense_stop_per_sf=stop, recovery_overrides=overrides,
                pct_rent_breakpoint=None, pct_rent_rate=None,
                base_year=_base_year(analysis, start, rtype, overrides),
            ))
    return leases


# Most passes valuing the fee for base-year and modified gross fee rows (it converges in a few);
# growth caps alone keep two
_FEE_PASSES = 10


def _fee_rows(leases, expenses: list[ExpenseInput]) -> bool:
    """Whether a lease recovers a % of EGI line over a base year or in a modified gross pool."""
    fee_categories = {e.category for e in expenses if e.is_pct_of_egi and e.is_recoverable}
    return any(
        (recovery_type := _effective_recovery_type(lease, category)) == "modified_gross"
        or (recovery_type == "base_year_stop" and _has_stop_reference(lease, category))
        for lease in leases for category in fee_categories)


def _fee_in_growth_cap(leases, expenses: list[ExpenseInput]) -> bool:
    """Whether recoveries need each % of EGI line's fee by year: a lease caps the growth of a group
    that includes one, or recovers one over a base year or in a modified gross pool (by its type for
    that line, overrides included)."""
    fee_categories = {e.category for e in expenses if e.is_pct_of_egi and e.is_recoverable}
    for lease in leases:
        for category in fee_categories:
            recovery_type = _effective_recovery_type(lease, category)
            if recovery_type == "modified_gross" or (
                    recovery_type == "base_year_stop" and _has_stop_reference(lease, category)):
                return True
        groups: dict[str, list] = {}
        for o in lease.recovery_overrides:
            if o.cap_group:
                groups.setdefault(o.cap_group, []).append(o)
        for members in groups.values():
            if any(o.cap_growth_pct is not None for o in members) and any(
                    o.expense_category in fee_categories for o in members):
                return True
    return False


def _fee_by_recovery_year(
    annual_cfs: list[AnnualPropertyCashFlow], analysis: AnalysisPeriod, calendar: bool,
    monthly_cfs: list[AnnualPropertyCashFlow] | None,
    fee_categories: frozenset[str],
) -> dict[str, dict[int, Decimal]]:
    """Each recoverable % of EGI line's fee (`fee_categories`) by recovery year, by category."""
    return {c: _line_fee_by_recovery_year(annual_cfs, analysis, calendar, monthly_cfs, c) for c in fee_categories}


def _line_fee_by_recovery_year(
    annual_cfs: list[AnnualPropertyCashFlow], analysis: AnalysisPeriod, calendar: bool,
    monthly_cfs: list[AnnualPropertyCashFlow] | None,
    category: str,
) -> dict[int, Decimal]:
    """
    One % of EGI line's fee by recovery year: the analysis year number, or
    the calendar year when recoveries follow calendar years (months outside the analysis at the nearest year's rate).
    With monthly cash flows, each analysis year's fee falls in its months as the monthly fee does.
    """
    def fee_of(cf: AnnualPropertyCashFlow) -> Decimal:
        return -cf.expense_detail.get(category, Decimal(0))

    fees = [fee_of(cf) for cf in annual_cfs]
    if not calendar:
        return {fy.year_number: fee for fy, fee in zip(analysis.fiscal_years, fees)}
    monthly_fees = [fee_of(cf) for cf in monthly_cfs or ()]
    monthly: dict[tuple[int, int], Decimal] = {}
    first_month = 0
    for fy, fee in zip(analysis.fiscal_years, fees):
        months = months_between(fy.start_date, fy.end_date) + 1
        shape = monthly_fees[first_month:first_month + months]
        total = sum(shape, Decimal(0))
        d = fy.start_date
        for i in range(months):
            monthly[(d.year, d.month)] = fee * shape[i] / total if len(shape) == months and total else fee / months
            d = add_months(d, 1)
        first_month += months
    first, last = analysis.fiscal_years[0].start_date, analysis.fiscal_years[-1].end_date
    out: dict[int, Decimal] = {}
    for year in range(first.year, last.year + 1):
        total = Decimal(0)
        for month in range(1, 13):
            key = (year, month)
            if key not in monthly:
                key = (first.year, first.month) if date(year, month, 1) < first else (last.year, last.month)
            total += monthly[key]
        out[year] = total
    return out


def _aggregate_monthly_cash_flows(monthly_cfs, analysis):
    """Roll monthly waterfall results into the analysis-year buckets without recalculation."""
    annual = []
    for fy in analysis.fiscal_years:
        group = [cf for cf in monthly_cfs if fy.start_date <= cf.period_start <= fy.end_date]
        if not group:
            continue
        updates = {"year": fy.year_number, "period_start": fy.start_date, "period_end": fy.end_date}
        for field in fields(AnnualPropertyCashFlow):
            name = field.name
            if name in updates:
                continue
            if name in ("expense_detail", "other_income_detail"):
                detail = {}
                for cf in group:
                    for key, value in getattr(cf, name).items():
                        detail[key] = detail.get(key, Decimal(0)) + value
                updates[name] = detail
            else:
                updates[name] = sum((getattr(cf, name) for cf in group), Decimal(0))
        annual.append(replace(group[0], **updates))
    return annual


def _aggregate_monthly_suite_details(monthly_details):
    """Roll per-suite monthly details into per-suite analysis-year results."""
    grouped = {}
    for detail in monthly_details:
        grouped.setdefault((detail.year, detail.suite_id), []).append(detail)
    annual = []
    numeric = ("base_rent", "effective_rent", "free_rent", "expense_recovery", "turnover_vacancy",
               "loss_to_lease", "ti_cost", "lc_cost", "ti_lc_cost")
    for group in grouped.values():
        updates = {name: sum((getattr(item, name) for item in group), Decimal(0)) for name in numeric}
        occupied = next((item for item in reversed(group) if item.tenant_name is not None), group[-1])
        updates.update(tenant_name=occupied.tenant_name, scenario=occupied.scenario)
        annual.append(replace(group[0], **updates))
    return annual


def run_valuation(
    property_start_date,
    analysis_period_months: int,
    fiscal_year_end_month: int,
    suites: list[SuiteInput],
    leases: list[LeaseInput],
    market_assumptions: dict[str, MarketAssumptions],
    expenses: list[ExpenseInput],
    params: ValuationParams,
    property_type: str = "office",
    capital_projects: list | None = None,
    other_income_items: list | None = None,
    other_income_annual: Decimal = Decimal(0),
    cpi_assumption: Decimal = Decimal("0.025"),
    cpi_schedule: tuple[Decimal, ...] = (),
    _use_extended_forward_noi: bool = True,
    include_monthly: bool = False,
    _full_occupancy: bool = False,
    recovery_pools: tuple[RecoveryPoolInput, ...] = (),
) -> EngineResult:
    """
    Full DCF valuation engine.

    Parameters
    ----------
    property_start_date : date
        First day of the analysis period.
    analysis_period_months : int
        Hold period in months (typically 120 = 10 years).
    fiscal_year_end_month : int
        Month number (1-12) for fiscal year end (e.g. 12 = Dec).
    suites : list[SuiteInput]
        All suites/units in the property.
    leases : list[LeaseInput]
        All in-place leases (sorted by suite).
    market_assumptions : dict[str, MarketAssumptions]
        Market leasing assumptions keyed by space_type.
    expenses : list[ExpenseInput]
        Operating expense line items.
    params : ValuationParams
        Valuation assumptions (discount rate, exit cap, debt, etc.).
    other_income_annual : Decimal
        Annual other income (parking, fees, etc.).
    cpi_assumption : Decimal
        CPI rate for CPI-escalated leases.
    cpi_schedule : tuple[Decimal, ...]
        Optional year-by-year CPI rates (last carries forward); replaces cpi_assumption.
    """
    if params.discounting_convention not in ("annual", "monthly"):
        raise ValueError("discounting_convention must be 'annual' or 'monthly'")
    if params.vacancy_calculation_frequency not in ("annual", "monthly"):
        raise ValueError("vacancy_calculation_frequency must be 'annual' or 'monthly'")
    if params.discounting_convention == "monthly" and params.use_mid_year_convention:
        raise ValueError("use_mid_year_convention is not supported with monthly discounting")

    # Build analysis period with fiscal years
    analysis = build_analysis_period(
        property_start_date, analysis_period_months, fiscal_year_end_month
    )

    # Index leases by suite
    leases_by_suite: dict[str, list[LeaseInput]] = {}
    for lease in leases:
        leases_by_suite.setdefault(lease.suite_id, []).append(lease)

    # Step 1: Project all suites, collecting speculative lease inputs
    suite_slices: dict[str, list[MonthlySlice]] = {}
    all_speculative_leases: list[LeaseInput] = []
    recovery_audit = []

    use_occupancy = property_type in ("multifamily", "self_storage")

    for suite in suites:
        suite_leases = leases_by_suite.get(suite.suite_id, [])
        market = market_assumptions.get(suite.space_type)
        if use_occupancy and market is not None:
            slices, spec_leases = _project_suite_by_occupancy(
                suite, suite_leases, analysis, market, cpi_assumption, cpi_schedule
            )
        else:
            slices, spec_leases = _project_suite(
                suite, suite_leases, analysis, market, cpi_assumption, cpi_schedule, market_assumptions
            )
        suite_slices[suite.suite_id] = slices
        all_speculative_leases.extend(spec_leases)
    if _full_occupancy:
        all_speculative_leases.extend(_fill_turnover_vacancy(suite_slices, suites, market_assumptions, analysis,
                                                             leases_by_suite))

    # Step 2: Compute occupancy by month (needed for expense gross-up)
    occupancy_by_month = compute_occupancy_by_month(suite_slices, suites, analysis)

    # Step 3: Attach expense recoveries to all in-place AND speculative lease slices
    # Build a combined lease input map: in-place + speculative
    lease_input_map: dict[str, LeaseInput] = {l.lease_id: l for l in leases}
    for spec_lease in all_speculative_leases:
        if params.calendar_year_recoveries and spec_lease.base_year is not None:
            # Reimbursing calendar years, a market lease's base year is the calendar year it starts
            spec_lease = replace(spec_lease, base_year=spec_lease.start_date.year)
        lease_input_map[spec_lease.lease_id] = spec_lease

    total_area = params.total_property_area
    recovery_context = recovery_occupancy_context(analysis, occupancy_by_month)
    pools = list(recovery_pools)
    pool_denominator = pool_denominators(pools, suites, suite_slices, analysis, total_area,
                                         params.calendar_year_recoveries)
    pool_occupancy = pool_occupancies(pools, suites, suite_slices, analysis, params.calendar_year_recoveries)
    # Suites whose recoveries other tenants' pools deduct are billed first, to learn what they pay
    contributors = [s for s in suites
                    if any(p.deduct_excluded_recoveries and s.suite_id in p.excluded_suite_ids for p in pools)]

    def attach_suites(targets, audit: list | None, fee_by_year: dict[str, dict[int, Decimal]] | None, deductions: dict,
                      net_fees: dict | None = None) -> None:
        for suite in targets:
            shares = (lease_pool_shares(suite.suite_id, pools, pool_denominator, deductions, pool_occupancy, net_fees)
                      if pools else None)
            pays_into = deducting_pools_excluding(suite.suite_id, pools) if pools else None
            # Group slices by lease_id to apply recoveries per lease
            lease_map: dict[str, list[MonthlySlice]] = {}
            for s in suite_slices[suite.suite_id]:
                lease_map.setdefault(s.lease_id, []).append(s)

            for lid, lslices in lease_map.items():
                lease_input = lease_input_map.get(lid)
                if lease_input is None:
                    continue  # vacant slices have unique IDs and no recovery
                attach_expense_recoveries(
                    lslices,
                    lease_input,
                    expenses,
                    analysis,
                    total_area,
                    occupancy_by_month,
                    apply_stabilized_gross_up=params.apply_stabilized_gross_up,
                    stabilized_occupancy_pct=params.stabilized_occupancy_pct,
                    recovery_audit=audit,
                    calendar_year_recoveries=params.calendar_year_recoveries,
                    fee_by_year=fee_by_year,
                    occupancy_context=recovery_context,
                    pool_shares=shares,
                    pays_into=pays_into,
                )

    def attach_all(audit: list | None, fee_by_year: dict[str, dict[int, Decimal]] | None = None,
                   net_fees: dict | None = None) -> None:
        """net_fees: what excluded net leases pay toward deducting pools' % of EGI lines (from the
        waterfall), deducted from base-year and modified gross leases' fee rows."""
        deductions: dict = {}
        if contributors:
            # What a pool's excluded suites pay toward it does not depend on any deduction (they are
            # outside that pool), so one pass finds it; a contributor inside another deducting pool
            # is then billed again below with that pool's deduction
            attach_suites(contributors, None, fee_by_year, {})
            deductions = excluded_recoveries(pools, suite_slices, analysis, params.calendar_year_recoveries)
        attach_suites(suites, audit, fee_by_year, deductions, net_fees)

    fee_capped = _fee_in_growth_cap(lease_input_map.values(), expenses)
    attach_all(None if fee_capped else recovery_audit)

    excluded_suites, vacancy_excluded = _vacancy_exclusions(suites, leases, all_speculative_leases,
                                                            market_assumptions)

    if fee_capped:
        # Growth caps that include the management fee, and base-year and modified gross fee rows, need
        # the fee, which depends on recoveries: value the fee and recompute recoveries with it, twice
        # for growth caps alone; with fee rows, until the fee moves less than a cent (each pass shrinks
        # the change by about the fee's %). Only the last pass records the recovery audit.
        passes = _FEE_PASSES if _fee_rows(lease_input_map.values(), expenses) else 2
        fee_categories = frozenset(e.category for e in expenses if e.is_pct_of_egi and e.is_recoverable)
        previous: dict[str, dict[int, Decimal]] | None = None
        for i in range(passes):
            paid_by_bucket: dict = {}
            fee_cfs, _ = build_annual_waterfall(
                suite_slices=suite_slices, suites=suites, expenses=expenses, params=params,
                analysis=analysis, market_map=market_assumptions, debt_schedule=[Decimal(0)] * len(analysis.fiscal_years),
                occupancy_by_month=occupancy_by_month, capital_projects=capital_projects,
                other_income_items=other_income_items, other_income_annual=other_income_annual,
                vacancy_excluded_lease_ids=vacancy_excluded, vacancy_excluded_suite_ids=excluded_suites,
                pool_fee_paid=None if params.calendar_year_recoveries else paid_by_bucket,
            )
            monthly_fee_cfs = None
            if params.calendar_year_recoveries:
                monthly_fee_cfs, _ = build_annual_waterfall(
                    suite_slices=suite_slices, suites=suites, expenses=expenses, params=params,
                    analysis=build_monthly_buckets(analysis), market_map=market_assumptions,
                    debt_schedule=[Decimal(0)] * analysis.num_months, occupancy_by_month=occupancy_by_month,
                    capital_projects=capital_projects, other_income_items=other_income_items,
                    other_income_annual=other_income_annual, vacancy_excluded_lease_ids=vacancy_excluded,
                    vacancy_excluded_suite_ids=excluded_suites, pool_fee_paid=paid_by_bucket,
                )
            fee_by_year = _fee_by_recovery_year(fee_cfs, analysis, params.calendar_year_recoveries, monthly_fee_cfs,
                                                fee_categories)
            last = i == passes - 1 or previous is not None and sum(
                (abs(fee - previous.get(c, {}).get(y, Decimal(0)))
                 for c, by_year in fee_by_year.items() for y, fee in by_year.items()), Decimal(0)) < Decimal("0.01")
            attach_all(recovery_audit if last else None, fee_by_year,
                       excluded_net_fees(paid_by_bucket, analysis, params.calendar_year_recoveries))
            if last:
                break
            previous = fee_by_year

    # Step 4: Build debt schedule
    num_years = len(analysis.fiscal_years)
    debt_schedule, debt_balances, debt_balloons = build_debt_schedule_detail(params, num_years, analysis.num_months)

    monthly_cfs: list[AnnualPropertyCashFlow] = []
    monthly_suite = []
    if (include_monthly or params.discounting_convention == "monthly"
            or params.vacancy_calculation_frequency == "monthly"):
        monthly_cfs, monthly_suite = build_annual_waterfall(
            suite_slices=suite_slices,
            suites=suites,
            expenses=expenses,
            params=params,
            analysis=build_monthly_buckets(analysis),
            market_map=market_assumptions,
            debt_schedule=build_monthly_debt_detail(params, analysis.num_months)[0],
            occupancy_by_month=occupancy_by_month,
            capital_projects=capital_projects,
            other_income_items=other_income_items,
            other_income_annual=other_income_annual,
            vacancy_excluded_lease_ids=vacancy_excluded,
            vacancy_excluded_suite_ids=excluded_suites,
        )

    # Step 5: Waterfall aggregation. When vacancy is calculated monthly, preserve each
    # month's zero floor and then sum the completed monthly waterfalls into annual results.
    if params.vacancy_calculation_frequency == "monthly":
        annual_cfs = _aggregate_monthly_cash_flows(monthly_cfs, analysis)
        suite_annual = _aggregate_monthly_suite_details(monthly_suite)
    else:
        annual_cfs, suite_annual = build_annual_waterfall(
            suite_slices=suite_slices,
            suites=suites,
            expenses=expenses,
            params=params,
            analysis=analysis,
            market_map=market_assumptions,
            debt_schedule=debt_schedule,
            occupancy_by_month=occupancy_by_month,
            capital_projects=capital_projects,
            other_income_items=other_income_items,
            other_income_annual=other_income_annual,
            vacancy_excluded_lease_ids=vacancy_excluded,
            vacancy_excluded_suite_ids=excluded_suites,
        )

    # Step 6: Terminal value
    forward_noi = _estimate_forward_noi(annual_cfs, expenses, market_assumptions, suites)
    forward_capital = forward_leasing = forward_free_rent = Decimal(0)
    # A terminal NOI override replaces the forward NOI; the extended run is then only
    # needed for the Year N+1 deductions.
    needs_extended = (
        params.terminal_noi_override is None or params.exit_deduct_forward_capital
        or params.exit_deduct_forward_leasing_costs or params.exit_deduct_forward_free_rent
    )
    if params.exit_cap_year == -1 and needs_extended and _use_extended_forward_noi and annual_cfs:
        # For terminal value, use explicit NOI from Year (Hold + 1), not a growth proxy.
        # Extend the run by 12 months and take the first additional annual NOI.
        forward_markets = market_assumptions
        if params.exit_noi_full_occupancy:
            forward_markets = {
                k: replace(m, general_vacancy_pct=params.exit_stabilized_vacancy_pct, general_vacancy_schedule=())
                for k, m in market_assumptions.items()
            }
        extended = run_valuation(
            property_start_date=property_start_date,
            analysis_period_months=analysis_period_months + 12,
            fiscal_year_end_month=fiscal_year_end_month,
            suites=suites,
            leases=leases,
            market_assumptions=forward_markets,
            expenses=expenses,
            params=params,
            property_type=property_type,
            capital_projects=capital_projects,
            other_income_items=other_income_items,
            other_income_annual=other_income_annual,
            cpi_assumption=cpi_assumption,
            cpi_schedule=cpi_schedule,
            _use_extended_forward_noi=False,
            _full_occupancy=params.exit_noi_full_occupancy,
            recovery_pools=recovery_pools,
        )
        if len(extended.annual_cash_flows) > len(annual_cfs):
            fwd = extended.annual_cash_flows[len(annual_cfs)]
            forward_noi = fwd.net_operating_income
            forward_capital = -(fwd.tenant_improvements + fwd.leasing_commissions + fwd.building_improvements)
            forward_leasing = -(fwd.tenant_improvements + fwd.leasing_commissions)
            forward_free_rent = -fwd.free_rent
    terminal = calculate_terminal_value_breakdown(
        annual_cfs, params, forward_noi, forward_capital, forward_leasing, forward_free_rent,
    )
    terminal_value = terminal.net_value

    # Step 7: DCF discounting → NPV
    if params.discounting_convention == "monthly":
        pv_cfs, pv_terminal, npv = discount_monthly_cash_flows(
            monthly_cfs, terminal_value, params.discount_rate
        )
    else:
        pv_cfs, pv_terminal, npv = discount_cash_flows(
            annual_cfs, terminal_value, params.discount_rate, params.use_mid_year_convention,
            params.terminal_timing,
        )

    # Step 8: IRR (use NPV as implied purchase price)
    if params.discounting_convention == "monthly":
        # Monthly IRR, annualized, so it reproduces the monthly-discounted NPV's rate
        monthly_series = [-npv] + [cf.cash_flow_before_debt for cf in monthly_cfs]
        monthly_series[-1] += terminal_value
        monthly_irr = irr_from_series(monthly_series)
        irr = (Decimal(1) + monthly_irr) ** 12 - Decimal(1) if monthly_irr is not None else None
    else:
        irr = calculate_irr(annual_cfs, terminal_value, initial_investment=npv)

    # Step 9: Key metrics
    year1_noi = annual_cfs[0].net_operating_income if annual_cfs else Decimal(0)
    gin_cap = going_in_cap_rate(year1_noi, npv) if npv > Decimal(0) else Decimal(0)

    # Returns at an actual purchase price (unlevered + levered), when provided
    returns = compute_investment_returns(
        annual_cfs, terminal_value, npv, params, debt_balances, debt_balloons,
        monthly_cfs if params.discounting_convention == "monthly" else None,
    )

    # Average occupancy
    avg_occ = sum(occupancy_by_month) / Decimal(str(len(occupancy_by_month))) if occupancy_by_month else Decimal(0)

    # Equity multiple: (total unlevered distributions + terminal value) / NPV
    # NPV here is the implied purchase price at the given discount rate.
    total_cfbd = sum(cf.cash_flow_before_debt for cf in annual_cfs)
    em = _equity_multiple(total_cfbd + terminal_value, npv) if npv > Decimal(0) else None
    if returns is not None:
        irr = returns.unlevered_irr
        gin_cap = returns.going_in_cap_rate
        em = returns.unlevered_equity_multiple

    return EngineResult(
        annual_cash_flows=annual_cfs,
        suite_annual_details=suite_annual,
        npv=npv,
        irr=irr,
        terminal_value=terminal_value,
        pv_cash_flows=pv_cfs,
        pv_terminal=pv_terminal,
        going_in_cap_rate=gin_cap,
        avg_occupancy_pct=avg_occ,
        equity_multiple=em,
        terminal_noi_basis=terminal.noi_basis,
        terminal_gross_value=terminal.gross_value,
        terminal_exit_costs_amount=terminal.exit_costs_amount,
        terminal_transfer_tax_amount=terminal.transfer_tax_amount,
        terminal_transfer_tax_preset=params.transfer_tax_preset,
        terminal_capital_deduction_amount=terminal.capital_deduction_amount,
        direct_cap_value=direct_cap_value(year1_noi, params.direct_cap_rate),
        returns=returns,
        recovery_audit=recovery_audit,
        monthly_cash_flows=monthly_cfs,
    )
