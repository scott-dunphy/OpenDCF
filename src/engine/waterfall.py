"""
Cash flow waterfall aggregation.

Takes all suite-level monthly slices, aggregates them into annual property-level
cash flows following the standard CRE waterfall:

  GPR → Recoveries → Other Income → GPI → Vacancy → Credit → EGI
  → OpEx → NOI → TI/LC → CapReserves → CFBD → DebtService → Levered CF
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from src.engine.date_utils import add_months, end_of_month
from src.engine.expense_engine import occupancy_adjusted_expense
from src.engine.growth import growth_factor_to_year, market_rent_at_year, rate_for_year, scheduled_amount_at_year
from src.engine.types import (
    rent_area,
    AnalysisPeriod,
    AnnualPropertyCashFlow,
    ExpenseInput,
    FiscalYear,
    MarketAssumptions,
    MonthlySlice,
    SuiteAnnualCashFlow,
    SuiteInput,
    ValuationParams,
)


def _blended_vacancy_rate(
    suites: list[SuiteInput],
    market_map: dict[str, MarketAssumptions],
    year: int = 1,
) -> Decimal:
    """Area-weighted average general vacancy rate across all space types for an analysis year."""
    total_area = sum(s.area for s in suites)
    if total_area == Decimal(0):
        return Decimal("0.05")
    weighted = Decimal(0)
    for suite in suites:
        mkt = market_map.get(suite.space_type)
        if mkt:
            weighted += suite.area * rate_for_year(mkt.general_vacancy_pct, mkt.general_vacancy_schedule, year)
        else:
            weighted += suite.area * Decimal("0.05")
    return weighted / total_area


def _blended_credit_loss_rate(
    suites: list[SuiteInput],
    market_map: dict[str, MarketAssumptions],
    year: int = 1,
) -> Decimal:
    """Area-weighted average credit loss rate for an analysis year."""
    total_area = sum(s.area for s in suites)
    if total_area == Decimal(0):
        return Decimal("0.01")
    weighted = Decimal(0)
    for suite in suites:
        mkt = market_map.get(suite.space_type)
        if mkt:
            weighted += suite.area * rate_for_year(mkt.credit_loss_pct, mkt.credit_loss_schedule, year)
        else:
            weighted += suite.area * Decimal("0.01")
    return weighted / total_area


def compute_occupancy_by_month(
    suite_slices: dict[str, list[MonthlySlice]],
    suites: list[SuiteInput],
    analysis: AnalysisPeriod,
) -> list[Decimal]:
    """
    Return a list of occupancy rates (0..1) indexed by month_index.
    Occupancy = (leased area * scenario_weight * month_fraction) / total_area, so a lease ending or
    starting mid-month counts for the days it covers.
    Used for expense gross-up calculations.
    """
    total_area = sum(s.area for s in suites)
    if total_area == Decimal(0):
        return [Decimal(1)] * analysis.num_months

    suite_area_map = {s.suite_id: s.area for s in suites}
    # monthly leased area weighted by probability
    leased_by_month: dict[int, Decimal] = defaultdict(Decimal)

    for suite_id, slices in suite_slices.items():
        area = suite_area_map.get(suite_id, Decimal(0))
        for s in slices:
            if not s.is_vacant:
                leased_by_month[s.month_index] += area * s.scenario_weight * s.month_fraction

    result = []
    for idx in range(analysis.num_months):
        occ = leased_by_month.get(idx, Decimal(0)) / total_area
        result.append(min(Decimal(1), occ))
    return result


def _pct_of_egi_lines(expenses: list[ExpenseInput]) -> list[ExpenseInput]:
    """Expenses charged as a % of EGI (management fee and any other % of revenue lines)."""
    return [e for e in expenses if e.is_pct_of_egi and e.pct_of_egi is not None]


def _fee_gross_up(exp: ExpenseInput, params: ValuationParams, occupancy: Decimal) -> Decimal:
    """Gross-up factor for what tenants reimburse of a % of EGI line: reference / actual occupancy
    when the line is gross-up eligible and the year's occupancy is below the reference."""
    if not (params.apply_stabilized_gross_up and exp.is_gross_up_eligible) or occupancy <= 0:
        return Decimal(1)
    ref = params.stabilized_occupancy_pct if params.stabilized_occupancy_pct is not None else exp.gross_up_vacancy_pct
    return ref / occupancy if ref is not None and occupancy < ref else Decimal(1)


def _analysis_year_coverage_factor(fy: FiscalYear) -> Decimal:
    """
    Fraction of a full 12-month analysis year represented by this bucket.

    Uses month-level proration so full months contribute 1.0 and partial months
    contribute day-fractions. A full 12-month analysis year returns 1.0.
    """
    full_start = fy.start_date
    full_end = add_months(full_start, 12) - timedelta(days=1)
    covered_months = Decimal(0)

    for i in range(12):
        month_start = add_months(full_start, i)
        month_end = end_of_month(month_start)
        if month_start > full_end:
            break
        overlap_start = max(month_start, fy.start_date)
        overlap_end = min(month_end, fy.end_date)
        if overlap_start > overlap_end:
            continue
        covered_days = Decimal(str((overlap_end - overlap_start).days + 1))
        month_days = Decimal(str((month_end - month_start).days + 1))
        covered_months += covered_days / month_days

    factor = covered_months / Decimal(12)
    return max(Decimal(0), min(Decimal(1), factor))


def build_annual_waterfall(
    suite_slices: dict[str, list[MonthlySlice]],  # suite_id -> flat list of all slices
    suites: list[SuiteInput],
    expenses: list[ExpenseInput],
    params: ValuationParams,
    analysis: AnalysisPeriod,
    market_map: dict[str, MarketAssumptions],
    debt_schedule: list[Decimal],  # debt service per bucket, in bucket order
    occupancy_by_month: list[Decimal] | None = None,
    capital_projects: list | None = None,
    other_income_items: list | None = None,
    other_income_annual: Decimal = Decimal(0),  # legacy flat amount
    vacancy_excluded_lease_ids: frozenset[str] | set[str] = frozenset(),
    vacancy_excluded_suite_ids: frozenset[str] | set[str] = frozenset(),
    pool_fee_paid: dict | None = None,
) -> tuple[list[AnnualPropertyCashFlow], list[SuiteAnnualCashFlow]]:
    """
    Aggregate suite-level monthly slices into annual property cash flows.
    Passing monthly buckets (date_utils.build_monthly_buckets) gives monthly cash flows.
    pool_fee_paid: if given, filled with what excluded net leases pay toward each deducting pool's
    % of EGI lines, by bucket start: {start: {(pool, category): amount}}.

    Returns:
      - list of AnnualPropertyCashFlow (one per analysis-year bucket)
      - list of SuiteAnnualCashFlow (per-suite per-year for tenant detail report)
    """
    vacancy_rates: dict[int, Decimal] = {}
    credit_loss_rates: dict[int, Decimal] = {}
    fee_lines = _pct_of_egi_lines(expenses)
    if occupancy_by_month is None:
        occupancy_by_month = compute_occupancy_by_month(suite_slices, suites, analysis)
    non_egi_expenses = [e for e in expenses if not e.is_pct_of_egi]
    suite_area_map = {s.suite_id: s.area for s in suites}
    suite_name_map = {s.suite_id: s.suite_name for s in suites}
    suite_type_map = {s.suite_id: s.space_type for s in suites}

    annual_results: list[AnnualPropertyCashFlow] = []
    suite_annual_results: list[SuiteAnnualCashFlow] = []

    # Assign each slice to its bucket once rather than scanning every slice per bucket
    bucket_starts = [fy.start_date for fy in analysis.fiscal_years]
    slices_by_bucket: list[dict[str, list[MonthlySlice]]] = [defaultdict(list) for _ in bucket_starts]
    for suite_id, slices in suite_slices.items():
        for s in slices:
            i = bisect_right(bucket_starts, s.period_start) - 1
            if i >= 0 and s.period_start <= analysis.fiscal_years[i].end_date:
                slices_by_bucket[i][suite_id].append(s)

    # Variable expenses use the analysis year's average occupancy, so monthly
    # buckets sum exactly to the annual figures
    occ_by_year: dict[int, list[Decimal]] = defaultdict(list)
    for month_idx, occ in enumerate(occupancy_by_month):
        i = bisect_right(bucket_starts, add_months(analysis.start_date, month_idx)) - 1
        if i >= 0:
            occ_by_year[analysis.fiscal_years[i].year_number].append(occ)

    for bucket_idx, fy in enumerate(analysis.fiscal_years):
        year = fy.year_number
        fy_coverage_factor = _analysis_year_coverage_factor(fy)

        # Bucket monthly slices for this analysis-year bucket
        gpr = Decimal(0)
        excluded_gpr = Decimal(0)  # rent from tenants excluded from general vacancy / credit loss
        excluded_recoveries = Decimal(0)
        excluded_absorption_vac = Decimal(0)
        excluded_free_rent = Decimal(0)
        free_rent_total = Decimal(0)
        absorption_vac = Decimal(0)
        loss_to_lease = Decimal(0)
        recoveries = Decimal(0)
        pct_rent = Decimal(0)
        ti_total = Decimal(0)
        lc_total = Decimal(0)

        # Per-suite tracking for annual detail
        suite_yr_base_rent: dict[str, Decimal] = defaultdict(Decimal)
        suite_yr_eff_rent: dict[str, Decimal] = defaultdict(Decimal)
        suite_yr_free_rent: dict[str, Decimal] = defaultdict(Decimal)
        suite_yr_recovery: dict[str, Decimal] = defaultdict(Decimal)
        suite_yr_turnover: dict[str, Decimal] = defaultdict(Decimal)
        suite_yr_ltl: dict[str, Decimal] = defaultdict(Decimal)
        suite_yr_ti: dict[str, Decimal] = defaultdict(Decimal)
        suite_yr_lc: dict[str, Decimal] = defaultdict(Decimal)
        suite_yr_ti_lc: dict[str, Decimal] = defaultdict(Decimal)
        # % of EGI lines reimbursed: weighted shares with no floor or cap, summed by (suite, category,
        # grossed up, deducting pool, pool it pays into, excluded from general vacancy, pool gross-up
        # factor, pool deduction); slices with a floor or cap are kept whole
        fee_shares: dict[tuple, Decimal] = defaultdict(Decimal)
        limited_fee_slices: list[tuple[str, Decimal, MonthlySlice, bool]] = []
        suite_yr_tenant: dict[str, str | None] = {}
        suite_yr_scenario: dict[str, str] = {}

        for suite_id in suite_slices:
            slices = slices_by_bucket[bucket_idx].get(suite_id, [])
            area = suite_area_map.get(suite_id, Decimal(0))
            space_type = suite_type_map.get(suite_id, "")
            mkt = market_map.get(space_type)

            # Market rent for this suite in this analysis year (steps by year number)
            mkt_monthly = Decimal(0)
            if mkt:
                grown_rent = market_rent_at_year(
                    mkt.market_rent_per_unit, mkt.rent_growth_rate, year, mkt.rent_growth_schedule,
                )
                units = rent_area(area, mkt.rent_basis)
                if mkt.rent_payment_frequency == "monthly":
                    mkt_monthly = grown_rent * units  # $/unit/mo × units
                else:
                    mkt_monthly = grown_rent * units / Decimal(12)  # $/SF/yr × SF / 12

            for s in slices:
                w = s.scenario_weight

                if s.is_vacant:
                    suite_yr_scenario[suite_id] = "vacant"
                    # Turnover vacancy = market rent lost during vacant months (not for
                    # space taken off the market at expiry)
                    if mkt_monthly > 0 and s.scenario_label != "reabsorbed":
                        vac_amount = -(mkt_monthly * s.month_fraction * w)
                        absorption_vac += vac_amount
                        suite_yr_turnover[suite_id] += vac_amount
                        if suite_id in vacancy_excluded_suite_ids:
                            excluded_absorption_vac += vac_amount
                else:
                    gpr += s.base_rent * w
                    if s.lease_id in vacancy_excluded_lease_ids:
                        excluded_gpr += s.base_rent * w
                        excluded_recoveries += s.expense_recovery * w
                    fr = s.free_rent_adjustment * w  # negative
                    if s.lease_id in vacancy_excluded_lease_ids:
                        excluded_free_rent += fr
                    free_rent_total += fr
                    recoveries += s.expense_recovery * w
                    if s.mgmt_fee_shares:
                        fee_excluded = s.lease_id in vacancy_excluded_lease_ids
                        if s.mgmt_fee_caps or any(f.floor is not None or f.cap is not None
                                                  for f in s.mgmt_fee_shares.values()):
                            limited_fee_slices.append((suite_id, w, s, fee_excluded))
                        else:
                            for c, f in s.mgmt_fee_shares.items():
                                fee_shares[(suite_id, c, f.gross_up, f.pool, f.pays_into, fee_excluded,
                                            f.gross_factor, f.deduction)] += f.share * w
                    pct_rent += s.percentage_rent * w
                    suite_yr_base_rent[suite_id] += s.base_rent * w
                    suite_yr_eff_rent[suite_id] += s.effective_rent * w
                    suite_yr_free_rent[suite_id] += fr
                    suite_yr_recovery[suite_id] += s.expense_recovery * w
                    if suite_id not in suite_yr_tenant:
                        suite_yr_tenant[suite_id] = s.tenant_name
                        suite_yr_scenario[suite_id] = s.scenario_label
                    # Loss to lease: only for in-place leases (contract vs market gap).
                    # Uses base_rent (not effective_rent) — free rent is a separate line.
                    # Speculative leases (renewal/new tenant) are at market by definition.
                    if mkt_monthly > 0 and s.scenario_label == "in_place":
                        contract_monthly = s.base_rent * w
                        ltl = contract_monthly - (mkt_monthly * s.month_fraction * w)
                        if ltl < 0:
                            loss_to_lease += ltl
                            suite_yr_ltl[suite_id] += ltl

                ti_total += s.ti_cost * w
                lc_total += s.lc_cost * w
                suite_yr_ti[suite_id] += s.ti_cost * w
                suite_yr_lc[suite_id] += s.lc_cost * w
                suite_yr_ti_lc[suite_id] += (s.ti_cost + s.lc_cost) * w

        scheduled_rent = gpr + free_rent_total  # effective rent after free rent

        # Other income items (parking, antenna, storage, etc.) with growth
        oi_total = other_income_annual * fy_coverage_factor  # legacy flat fallback
        oi_detail: dict[str, Decimal] = {}
        for oi in (other_income_items or []):
            amt = scheduled_amount_at_year(
                oi.base_amount, oi.growth_rate, year, oi.growth_schedule, oi.amount_schedule
            ) * fy_coverage_factor
            oi_total += amt
            oi_detail[oi.category] = oi_detail.get(oi.category, Decimal(0)) + amt

        if year not in vacancy_rates:
            vacancy_rates[year] = _blended_vacancy_rate(suites, market_map, year)
            credit_loss_rates[year] = _blended_credit_loss_rate(suites, market_map, year)
        gen_vac_rate = vacancy_rates[year]
        credit_loss_rate = credit_loss_rates[year]

        def _revenue(mgmt_recovery: Decimal, excluded_mgmt: Decimal) -> tuple[Decimal, Decimal, Decimal, Decimal]:
            """(gross potential income, general vacancy, credit loss, EGI) given the fee reimbursed (and
            the part of it from tenants excluded from general vacancy)."""
            gpi = scheduled_rent + recoveries + mgmt_recovery + pct_rent + oi_total
            # General vacancy and credit loss applied to GPR (standard CRE convention), or to
            # gross revenue, excluding rent from tenants flagged as credit tenants.
            vacancy_base = gpr - excluded_gpr
            if params.vacancy_on_gross_revenue:
                # Gross revenue: rent after free rent, plus recoveries and other revenue
                vacancy_base += free_rent_total - excluded_free_rent
                vacancy_base += gpi - scheduled_rent - excluded_recoveries
                vacancy_base -= excluded_mgmt
            if params.reduce_general_vacancy_by_downtime:
                # Rate applies to potential rent (incl. vacant space at market); modeled
                # absorption/turnover vacancy counts toward it, floored at zero.
                modeled_vac = -(absorption_vac - excluded_absorption_vac)
                gen_vac_loss = -max(Decimal(0), (vacancy_base + modeled_vac) * gen_vac_rate - modeled_vac)
            else:
                gen_vac_loss = -(vacancy_base * gen_vac_rate)
            credit_loss = -(vacancy_base * credit_loss_rate)
            return gpi, gen_vac_loss, credit_loss, gpi + gen_vac_loss + credit_loss

        # Tenants reimbursing the management fee raise EGI, which raises the fee: iterate to
        # the fixed point (the reimbursed share of a few % of EGI converges in a few steps)
        year_occ = occ_by_year.get(year)
        fy_avg_occ = sum(year_occ) / Decimal(len(year_occ)) if year_occ else Decimal(1)
        months = Decimal(12) * fy_coverage_factor
        # Each recoverable % of EGI line by category: as charged, and grossed up on its own terms
        fee_pct: dict[str, Decimal] = defaultdict(Decimal)
        fee_pct_grossed: dict[str, Decimal] = defaultdict(Decimal)
        for line in fee_lines:
            if line.is_recoverable:
                fee_pct[line.category] += line.pct_of_egi
                fee_pct_grossed[line.category] += line.pct_of_egi * _fee_gross_up(line, params, fy_avg_occ)
        deducting = (any(key[3] for key in fee_shares)
                     or any(f.pool for _, _, s, _ in limited_fee_slices for f in s.mgmt_fee_shares.values()))

        def _mgmt_by_suite(egi_: Decimal) -> tuple[dict[str, Decimal], Decimal, dict[tuple[str, str], Decimal]]:
            """Fee each suite reimburses: each line's monthly fee x its share, raised to its floor and
            lowered to its cap (then the cap group's room); and the part from tenants excluded from
            general vacancy. A line in a deducting pool is shared after what the pool's excluded
            tenants pay toward it (found in a first pass: they are outside that pool) and what its excluded
            base-year / modified gross tenants pay (`deduction`). A line in a pool with excluded suites
            grosses up by its own factor (`gross_factor`). Also returns what is paid into each pool."""
            paid: dict[tuple[str, str], Decimal] = {}
            for _ in range(2 if deducting else 1):
                out: dict[str, Decimal] = defaultdict(Decimal)
                excluded = Decimal(0)
                new_paid: dict[tuple[str, str], Decimal] = defaultdict(Decimal)

                def line_fee(category: str, gross_up: bool, pool: str | None, gross_factor: Decimal | None,
                             deduction: Decimal) -> Decimal:
                    if gross_factor is not None:
                        fee = egi_ * fee_pct.get(category, Decimal(0)) * gross_factor / months
                    else:
                        fee = egi_ * (fee_pct_grossed if gross_up else fee_pct).get(category, Decimal(0)) / months
                    if pool is not None:
                        fee = max(Decimal(0), fee - paid.get((pool, category), Decimal(0)) / months - deduction)
                    return fee

                for (sid, c, gross_up, pool, pays_into, excl, gross_factor, deduction), share in fee_shares.items():
                    amount = line_fee(c, gross_up, pool, gross_factor, deduction) * share
                    out[sid] += amount
                    if excl:
                        excluded += amount
                    if pays_into:
                        new_paid[(pays_into, c)] += amount
                for sid, w, s, excl in limited_fee_slices:
                    amounts: dict[str, Decimal] = {}
                    for c, f in s.mgmt_fee_shares.items():
                        amount = line_fee(c, f.gross_up, f.pool, f.gross_factor, f.deduction) * f.share
                        if f.floor is not None:
                            amount = max(amount, f.floor)
                        if f.cap is not None:
                            amount = min(amount, f.cap)
                        amounts[c] = amount
                    for group, room in s.mgmt_fee_caps.items():
                        members = [c for c, f in s.mgmt_fee_shares.items() if f.cap_group == group]
                        total = sum((amounts[c] for c in members), Decimal(0))
                        if total > room:
                            for c in members:
                                amounts[c] = amounts[c] * room / total
                    for c, amount in amounts.items():
                        out[sid] += amount * w
                        if excl:
                            excluded += amount * w
                        if s.mgmt_fee_shares[c].pays_into:
                            new_paid[(s.mgmt_fee_shares[c].pays_into, c)] += amount * w
                paid = new_paid
            return out, excluded, paid

        mgmt_recovery = Decimal(0)
        excluded_mgmt = Decimal(0)
        mgmt_suites: dict[str, Decimal] = {}
        paid_into_pools: dict[tuple[str, str], Decimal] = {}
        gpi, gen_vac_loss, credit_loss, egi = _revenue(mgmt_recovery, excluded_mgmt)
        for _ in range(50):
            if months <= 0 or not (fee_shares or limited_fee_slices):
                break
            mgmt_suites, excluded_mgmt, paid_into_pools = _mgmt_by_suite(egi)
            new_recovery = sum(mgmt_suites.values(), Decimal(0))
            converged = abs(new_recovery - mgmt_recovery) < Decimal("0.000001")
            mgmt_recovery = new_recovery
            gpi, gen_vac_loss, credit_loss, egi = _revenue(mgmt_recovery, excluded_mgmt)
            if converged:
                break
        recoveries += mgmt_recovery
        if pool_fee_paid is not None and paid_into_pools:
            pool_fee_paid[fy.start_date] = dict(paid_into_pools)
        for sid, amount in mgmt_suites.items():
            suite_yr_recovery[sid] += amount

        # Fixed operating expenses (non_egi_expenses already excludes pct-of-EGI items)
        opex = Decimal(0)
        exp_detail: dict[str, Decimal] = {}
        for exp in non_egi_expenses:
            annual_exp = scheduled_amount_at_year(
                exp.base_amount, exp.growth_rate, year, exp.growth_schedule, exp.amount_schedule
            ) * fy_coverage_factor
            if exp.variable_pct > Decimal(0):
                # Fixed/variable split: landlord incurs the occupancy-adjusted amount
                amt = occupancy_adjusted_expense(annual_exp, exp, fy_avg_occ)
                opex += amt
                exp_detail[exp.category] = exp_detail.get(exp.category, Decimal(0)) + amt
                continue
            # Gross-up only sets what tenants are billed (recoveries); the landlord pays the
            # expense as entered
            opex += annual_exp
            exp_detail[exp.category] = exp_detail.get(exp.category, Decimal(0)) + annual_exp

        # % of EGI lines (management fee and any others) = EGI * pct, each under its own category
        for fee_line in fee_lines:
            fee = egi * fee_line.pct_of_egi
            opex += fee
            exp_detail[fee_line.category] = exp_detail.get(fee_line.category, Decimal(0)) + fee

        noi = egi - opex
        cap_reserves = -(params.capital_reserves_per_unit * params.total_property_area * fy_coverage_factor
                         * growth_factor_to_year(params.capital_reserves_growth_rate, year))

        # Building improvements: scheduled CapEx projects spread across months
        bldg_improvements = Decimal(0)
        for proj in (capital_projects or []):
            monthly_cost = proj.total_amount / Decimal(proj.duration_months)
            for m_off in range(proj.duration_months):
                proj_month = add_months(proj.start_date, m_off)
                if fy.start_date <= proj_month <= fy.end_date:
                    bldg_improvements -= monthly_cost

        cfbd = noi + ti_total + lc_total + cap_reserves + bldg_improvements

        debt_svc = -(debt_schedule[bucket_idx] if bucket_idx < len(debt_schedule) else Decimal(0))
        levered_cf = cfbd + debt_svc

        annual_results.append(AnnualPropertyCashFlow(
            year=year,
            period_start=fy.start_date,
            period_end=fy.end_date,
            gross_potential_rent=gpr,
            free_rent=free_rent_total,
            absorption_vacancy=absorption_vac,
            loss_to_lease=loss_to_lease,
            expense_recoveries=recoveries,
            percentage_rent=pct_rent,
            other_income=oi_total,
            gross_potential_income=gpi,
            general_vacancy_loss=gen_vac_loss,
            credit_loss=credit_loss,
            effective_gross_income=egi,
            operating_expenses=-opex,
            expense_detail={k: -v for k, v in exp_detail.items()},
            other_income_detail=oi_detail,
            net_operating_income=noi,
            tenant_improvements=ti_total,
            leasing_commissions=lc_total,
            capital_reserves=cap_reserves,
            building_improvements=bldg_improvements,
            cash_flow_before_debt=cfbd,
            debt_service=debt_svc,
            levered_cash_flow=levered_cf,
        ))

        # Collect per-suite annual details
        for suite in suites:
            sid = suite.suite_id
            suite_annual_results.append(SuiteAnnualCashFlow(
                suite_id=sid,
                suite_name=suite_name_map[sid],
                space_type=suite_type_map[sid],
                area=suite.area,
                year=year,
                tenant_name=suite_yr_tenant.get(sid),
                scenario=suite_yr_scenario.get(sid, "vacant"),
                base_rent=suite_yr_base_rent.get(sid, Decimal(0)),
                effective_rent=suite_yr_eff_rent.get(sid, Decimal(0)),
                free_rent=suite_yr_free_rent.get(sid, Decimal(0)),
                expense_recovery=suite_yr_recovery.get(sid, Decimal(0)),
                turnover_vacancy=suite_yr_turnover.get(sid, Decimal(0)),
                loss_to_lease=suite_yr_ltl.get(sid, Decimal(0)),
                ti_cost=suite_yr_ti.get(sid, Decimal(0)),
                lc_cost=suite_yr_lc.get(sid, Decimal(0)),
                ti_lc_cost=suite_yr_ti_lc.get(sid, Decimal(0)),
            ))

    return annual_results, suite_annual_results
