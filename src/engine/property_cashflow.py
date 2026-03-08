"""
Master DCF engine orchestrator.

This is the top-level function called by the service layer.
It coordinates: lease projection → renewal generation → expense recovery
→ waterfall aggregation → terminal value → DCF → IRR.

All inputs are pure engine dataclasses (no DB, no Pydantic).
All outputs are engine result dataclasses.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from src.engine.date_utils import add_months, build_analysis_period, end_of_month, fiscal_year_for_month
from src.engine.dcf import (
    build_debt_schedule,
    calculate_irr,
    calculate_terminal_value_breakdown,
    discount_cash_flows,
    equity_multiple as _equity_multiple,
    going_in_cap_rate,
)
from src.engine.expense_engine import attach_expense_recoveries
from src.engine.growth import expense_at_year, market_rent_at_year
from src.engine.lease_projector import make_vacant_slices, project_lease_cash_flows
from src.engine.renewal_engine import generate_speculative_leases
from src.engine.types import (
    AnalysisPeriod,
    AnnualPropertyCashFlow,
    EngineResult,
    ExpenseInput,
    LeaseInput,
    MarketAssumptions,
    MonthlySlice,
    SuiteInput,
    ValuationParams,
)
from src.engine.waterfall import build_annual_waterfall, compute_occupancy_by_month


def _suites_with_market(suites: list[SuiteInput], market_map: dict[str, MarketAssumptions]) -> list[SuiteInput]:
    """Return suites that have a matching market leasing profile."""
    return [s for s in suites if s.space_type in market_map]


def _project_suite(
    suite: SuiteInput,
    suite_leases: list[LeaseInput],
    analysis: AnalysisPeriod,
    market: MarketAssumptions | None,
    cpi_assumption: Decimal,
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

        # Gap before this lease
        if current_date < lease_start_in_period:
            if market is not None:
                source_lease = previous_lease or lease
                spec_slices, spec_leases = generate_speculative_leases(
                    suite=suite,
                    vacancy_start_date=current_date,
                    analysis=analysis,
                    market=market,
                    original_recovery_type=source_lease.recovery_type,
                    original_pro_rata_share=source_lease.pro_rata_share,
                    renewal_probability_override=source_lease.renewal_probability_override,
                    renewal_rent_spread_override=source_lease.renewal_rent_spread_override,
                    cpi_assumption=cpi_assumption,
                )
                # Filter slices to gap only
                gap_slices = [s for s in spec_slices if s.period_end < lease_start_in_period]
                all_slices.extend(gap_slices)
                # Only include lease inputs for leases that have slices in this gap
                included_ids = {s.lease_id for s in gap_slices}
                all_spec_leases.extend(l for l in spec_leases if l.lease_id in included_ids)
            else:
                vac = make_vacant_slices(suite.suite_id, current_date,
                                         lease_start_in_period - timedelta(days=1), analysis)
                all_slices.extend(vac)

        # Project in-place lease
        if lease.start_date <= analysis.end_date and lease.end_date >= analysis.start_date:
            slices = project_lease_cash_flows(
                lease, analysis,
                cpi_assumption=cpi_assumption,
                scenario_label="in_place",
                scenario_weight=Decimal(1),
            )
            all_slices.extend(slices)

        current_date = lease_end_in_period + timedelta(days=1)
        previous_lease = lease

    # Gap after all in-place leases (post-expiry speculative leasing)
    if current_date <= analysis.end_date:
        if market is not None:
            # Determine recovery type from the last in-place lease (if any)
            last_lease = sorted_leases[-1] if sorted_leases else None
            recovery_type = last_lease.recovery_type if last_lease else "nnn"
            pro_rata = last_lease.pro_rata_share if last_lease else None
            spec_slices, spec_leases = generate_speculative_leases(
                suite=suite,
                vacancy_start_date=current_date,
                analysis=analysis,
                market=market,
                original_recovery_type=recovery_type,
                original_pro_rata_share=pro_rata,
                renewal_probability_override=(
                    last_lease.renewal_probability_override if last_lease else None
                ),
                renewal_rent_spread_override=(
                    last_lease.renewal_rent_spread_override if last_lease else None
                ),
                cpi_assumption=cpi_assumption,
            )
            all_slices.extend(spec_slices)
            all_spec_leases.extend(spec_leases)
        else:
            vac = make_vacant_slices(suite.suite_id, current_date, analysis.end_date, analysis)
            all_slices.extend(vac)

    return all_slices, all_spec_leases


def _project_suite_by_occupancy(
    suite: SuiteInput,
    suite_leases: list[LeaseInput],
    analysis: AnalysisPeriod,
    market: MarketAssumptions,
    cpi_assumption: Decimal,
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
            )
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
                s.effective_rent = s.base_rent + s.free_rent_adjustment
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
            market.market_rent_per_unit, market.rent_growth_rate, fy_num
        )
        # For monthly-basis (multifamily/storage): rent × units
        if market.rent_payment_frequency == "monthly":
            monthly_revenue = grown_rent * suite.area
        else:
            monthly_revenue = grown_rent * suite.area / Decimal(12)

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

    # Blended expense growth rate (weighted by base amount)
    non_egi_exps = [e for e in expenses if not e.is_pct_of_egi]
    total_exp_base = sum(e.base_amount for e in non_egi_exps)
    exp_growth = (
        sum(e.base_amount * e.growth_rate for e in non_egi_exps) / total_exp_base
        if total_exp_base > Decimal(0)
        else Decimal("0.03")
    )

    # Blended rent growth rate (area-weighted across market assumptions)
    total_area = sum(s.area for s in suites)
    rent_growth = (
        sum(
            s.area * market_map[s.space_type].rent_growth_rate
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
    forward_gpi = forward_gpr + forward_recoveries + forward_pct_rent + last.other_income

    # Apply the same vacancy/credit loss rates as last year
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
    _use_extended_forward_noi: bool = True,
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
    """
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
                suite, suite_leases, analysis, market, cpi_assumption
            )
        else:
            slices, spec_leases = _project_suite(
                suite, suite_leases, analysis, market, cpi_assumption
            )
        suite_slices[suite.suite_id] = slices
        all_speculative_leases.extend(spec_leases)

    # Step 2: Compute occupancy by month (needed for expense gross-up)
    occupancy_by_month = compute_occupancy_by_month(suite_slices, suites, analysis)

    # Step 3: Attach expense recoveries to all in-place AND speculative lease slices
    # Build a combined lease input map: in-place + speculative
    lease_input_map: dict[str, LeaseInput] = {l.lease_id: l for l in leases}
    for spec_lease in all_speculative_leases:
        lease_input_map[spec_lease.lease_id] = spec_lease

    total_area = params.total_property_area
    for suite in suites:
        slices = suite_slices[suite.suite_id]
        # Group slices by lease_id to apply recoveries per lease
        lease_map: dict[str, list[MonthlySlice]] = {}
        for s in slices:
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
                recovery_audit=recovery_audit,
            )

    # Step 4: Build debt schedule
    num_years = len(analysis.fiscal_years)
    debt_schedule = build_debt_schedule(params, num_years)

    # Step 5: Waterfall aggregation
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
    )

    # Step 6: Terminal value
    forward_noi = _estimate_forward_noi(annual_cfs, expenses, market_assumptions, suites)
    if params.exit_cap_year == -1 and _use_extended_forward_noi and annual_cfs:
        # For terminal value, use explicit NOI from Year (Hold + 1), not a growth proxy.
        # Extend the run by 12 months and take the first additional annual NOI.
        extended = run_valuation(
            property_start_date=property_start_date,
            analysis_period_months=analysis_period_months + 12,
            fiscal_year_end_month=fiscal_year_end_month,
            suites=suites,
            leases=leases,
            market_assumptions=market_assumptions,
            expenses=expenses,
            params=params,
            property_type=property_type,
            capital_projects=capital_projects,
            other_income_items=other_income_items,
            other_income_annual=other_income_annual,
            cpi_assumption=cpi_assumption,
            _use_extended_forward_noi=False,
        )
        if len(extended.annual_cash_flows) > len(annual_cfs):
            forward_noi = extended.annual_cash_flows[len(annual_cfs)].net_operating_income
    terminal = calculate_terminal_value_breakdown(annual_cfs, params, forward_noi)
    terminal_value = terminal.net_value

    # Step 7: DCF discounting → NPV
    pv_cfs, pv_terminal, npv = discount_cash_flows(
        annual_cfs, terminal_value, params.discount_rate, params.use_mid_year_convention
    )

    # Step 8: IRR (use NPV as implied purchase price)
    irr = calculate_irr(annual_cfs, terminal_value, initial_investment=npv)

    # Step 9: Key metrics
    year1_noi = annual_cfs[0].net_operating_income if annual_cfs else Decimal(0)
    gin_cap = going_in_cap_rate(year1_noi, npv) if npv > Decimal(0) else Decimal(0)

    # Average occupancy
    avg_occ = sum(occupancy_by_month) / Decimal(str(len(occupancy_by_month))) if occupancy_by_month else Decimal(0)

    # Equity multiple: (total unlevered distributions + terminal value) / NPV
    # NPV here is the implied purchase price at the given discount rate.
    total_cfbd = sum(cf.cash_flow_before_debt for cf in annual_cfs)
    em = _equity_multiple(total_cfbd + terminal_value, npv) if npv > Decimal(0) else None

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
        recovery_audit=recovery_audit,
    )
