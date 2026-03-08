"""
Cash flow waterfall aggregation.

Takes all suite-level monthly slices, aggregates them into annual property-level
cash flows following the standard CRE waterfall:

  GPR → Recoveries → Other Income → GPI → Vacancy → Credit → EGI
  → OpEx → NOI → TI/LC → CapReserves → CFBD → DebtService → Levered CF
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from src.engine.date_utils import add_months, end_of_month
from src.engine.growth import expense_at_year, market_rent_at_year
from src.engine.types import (
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
) -> Decimal:
    """Area-weighted average general vacancy rate across all space types."""
    total_area = sum(s.area for s in suites)
    if total_area == Decimal(0):
        return Decimal("0.05")
    weighted = Decimal(0)
    for suite in suites:
        mkt = market_map.get(suite.space_type)
        if mkt:
            weighted += suite.area * mkt.general_vacancy_pct
        else:
            weighted += suite.area * Decimal("0.05")
    return weighted / total_area


def _blended_credit_loss_rate(
    suites: list[SuiteInput],
    market_map: dict[str, MarketAssumptions],
) -> Decimal:
    """Area-weighted average credit loss rate."""
    total_area = sum(s.area for s in suites)
    if total_area == Decimal(0):
        return Decimal("0.01")
    weighted = Decimal(0)
    for suite in suites:
        mkt = market_map.get(suite.space_type)
        if mkt:
            weighted += suite.area * mkt.credit_loss_pct
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
    Occupancy = (leased area * scenario_weight) / total_area.
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
                leased_by_month[s.month_index] += area * s.scenario_weight

    result = []
    for idx in range(analysis.num_months):
        occ = leased_by_month.get(idx, Decimal(0)) / total_area
        result.append(min(Decimal(1), occ))
    return result


def _mgmt_fee_pct(expenses: list[ExpenseInput]) -> Decimal:
    """Return the management fee as % of EGI, or 0 if not configured."""
    for exp in expenses:
        if exp.is_pct_of_egi and exp.pct_of_egi is not None:
            return exp.pct_of_egi
    return Decimal(0)


def _grossed_up_opex_amount(
    annual_exp: Decimal,
    exp: ExpenseInput,
    actual_occupancy: Decimal,
    apply_stabilized_gross_up: bool,
    stabilized_occupancy_pct: Decimal | None,
) -> Decimal:
    """
    Gross up eligible operating expenses to their reference occupancy.

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


def _avg_occupancy_for_analysis_year(
    analysis: AnalysisPeriod,
    fy: FiscalYear,
    occupancy_by_month: list[Decimal] | None,
) -> Decimal:
    """Average monthly occupancy within an analysis-year bucket."""
    if not occupancy_by_month:
        return Decimal(1)

    occ_values: list[Decimal] = []
    for month_idx, occ in enumerate(occupancy_by_month):
        month_start = add_months(analysis.start_date, month_idx)
        if fy.start_date <= month_start <= fy.end_date:
            occ_values.append(occ)

    if not occ_values:
        return Decimal(1)
    return sum(occ_values) / Decimal(str(len(occ_values)))


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
    debt_schedule: list[Decimal],  # annual debt service by year (1-indexed)
    occupancy_by_month: list[Decimal] | None = None,
    capital_projects: list | None = None,
    other_income_items: list | None = None,
    other_income_annual: Decimal = Decimal(0),  # legacy flat amount
) -> tuple[list[AnnualPropertyCashFlow], list[SuiteAnnualCashFlow]]:
    """
    Aggregate suite-level monthly slices into annual property cash flows.

    Returns:
      - list of AnnualPropertyCashFlow (one per analysis-year bucket)
      - list of SuiteAnnualCashFlow (per-suite per-year for tenant detail report)
    """
    gen_vac_rate = _blended_vacancy_rate(suites, market_map)
    credit_loss_rate = _blended_credit_loss_rate(suites, market_map)
    mgmt_pct = _mgmt_fee_pct(expenses)
    if occupancy_by_month is None:
        occupancy_by_month = compute_occupancy_by_month(suite_slices, suites, analysis)
    non_egi_expenses = [e for e in expenses if not e.is_pct_of_egi]
    suite_area_map = {s.suite_id: s.area for s in suites}
    suite_name_map = {s.suite_id: s.suite_name for s in suites}
    suite_type_map = {s.suite_id: s.space_type for s in suites}

    annual_results: list[AnnualPropertyCashFlow] = []
    suite_annual_results: list[SuiteAnnualCashFlow] = []

    for fy in analysis.fiscal_years:
        year = fy.year_number
        fy_coverage_factor = _analysis_year_coverage_factor(fy)

        # Bucket monthly slices for this analysis-year bucket
        gpr = Decimal(0)
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
        suite_yr_tenant: dict[str, str | None] = {}
        suite_yr_scenario: dict[str, str] = {}

        for suite_id, slices in suite_slices.items():
            area = suite_area_map.get(suite_id, Decimal(0))
            space_type = suite_type_map.get(suite_id, "")
            mkt = market_map.get(space_type)

            # Market rent for this suite in this analysis year (steps by year number)
            mkt_monthly = Decimal(0)
            if mkt:
                grown_rent = market_rent_at_year(
                    mkt.market_rent_per_unit, mkt.rent_growth_rate, year,
                )
                if mkt.rent_payment_frequency == "monthly":
                    mkt_monthly = grown_rent * area  # $/unit/mo × units
                else:
                    mkt_monthly = grown_rent * area / Decimal(12)  # $/SF/yr × SF / 12

            for s in slices:
                if not (fy.start_date <= s.period_start <= fy.end_date):
                    continue
                w = s.scenario_weight

                if s.is_vacant:
                    suite_yr_scenario[suite_id] = "vacant"
                    # Turnover vacancy = market rent lost during vacant months
                    if mkt_monthly > 0:
                        vac_amount = -(mkt_monthly * w)
                        absorption_vac += vac_amount
                        suite_yr_turnover[suite_id] += vac_amount
                else:
                    gpr += s.base_rent * w
                    fr = s.free_rent_adjustment * w  # negative
                    free_rent_total += fr
                    recoveries += s.expense_recovery * w
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
                        ltl = contract_monthly - (mkt_monthly * w)
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
            amt = expense_at_year(oi.base_amount, oi.growth_rate, year) * fy_coverage_factor
            oi_total += amt
            oi_detail[oi.category] = oi_detail.get(oi.category, Decimal(0)) + amt

        gpi = scheduled_rent + recoveries + pct_rent + oi_total

        # General vacancy applied to scheduled rent (industry-standard convention)
        gen_vac_loss = -(scheduled_rent * gen_vac_rate)
        credit_loss = -(scheduled_rent * credit_loss_rate)
        egi = gpi + gen_vac_loss + credit_loss

        fy_avg_occ = _avg_occupancy_for_analysis_year(analysis, fy, occupancy_by_month)

        # Fixed operating expenses (non_egi_expenses already excludes pct-of-EGI items)
        opex = Decimal(0)
        exp_detail: dict[str, Decimal] = {}
        for exp in non_egi_expenses:
            annual_exp = expense_at_year(exp.base_amount, exp.growth_rate, year) * fy_coverage_factor
            amt = _grossed_up_opex_amount(
                annual_exp,
                exp,
                fy_avg_occ,
                apply_stabilized_gross_up=params.apply_stabilized_gross_up,
                stabilized_occupancy_pct=params.stabilized_occupancy_pct,
            )
            opex += amt
            exp_detail[exp.category] = exp_detail.get(exp.category, Decimal(0)) + amt

        # Management fee = EGI * pct / (1 + pct)  [solve circularity algebraically]
        if mgmt_pct > Decimal(0):
            mgmt_fee = egi * mgmt_pct / (Decimal(1) + mgmt_pct)
            opex += mgmt_fee
            exp_detail["management_fee"] = exp_detail.get("management_fee", Decimal(0)) + mgmt_fee

        noi = egi - opex
        cap_reserves = -(params.capital_reserves_per_unit * params.total_property_area * fy_coverage_factor)

        # Building improvements: scheduled CapEx projects spread across months
        bldg_improvements = Decimal(0)
        for proj in (capital_projects or []):
            monthly_cost = proj.total_amount / Decimal(proj.duration_months)
            for m_off in range(proj.duration_months):
                proj_month = add_months(proj.start_date, m_off)
                if fy.start_date <= proj_month <= fy.end_date:
                    bldg_improvements -= monthly_cost

        cfbd = noi + ti_total + lc_total + cap_reserves + bldg_improvements

        debt_svc = -(debt_schedule[year - 1] if year <= len(debt_schedule) else Decimal(0))
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
