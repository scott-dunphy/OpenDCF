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

from datetime import date, timedelta
from decimal import Decimal

from src.engine.date_utils import add_months, end_of_month, months_between
from src.engine.growth import market_rent_at_year
from src.engine.lease_projector import make_vacant_slices, project_lease_cash_flows
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

_MAX_GENERATIONS = 5  # prevent runaway recursion


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
    Year 1 = base, Year 2 = base × (1+rate), etc."""
    # Find fiscal year containing target_date
    fy_num = 1
    for fy in analysis.fiscal_years:
        if fy.start_date <= target_date <= fy.end_date:
            fy_num = fy.year_number
            break
    else:
        # Beyond analysis — use last year + 1
        if analysis.fiscal_years:
            fy_num = analysis.fiscal_years[-1].year_number + 1
    return market_rent_at_year(
        market.market_rent_per_unit,
        market.rent_growth_rate,
        fy_num,
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
    free_rent_months: int,
    recovery_type: str = "nnn",
    pro_rata_share: Decimal | None = None,
    rent_payment_frequency: str = "annual",
) -> LeaseInput:
    return LeaseInput(
        lease_id=lease_id,
        suite_id=suite.suite_id,
        tenant_name=tenant_label,
        area=suite.area,
        start_date=start_date,
        end_date=end_date,
        base_rent_per_unit=rent,
        rent_payment_frequency=rent_payment_frequency,
        escalation_type="pct_annual",
        escalation_pct=growth_rate,
        cpi_floor=None,
        cpi_cap=None,
        rent_steps=(),
        free_rent_periods=_make_free_rent_periods(start_date, free_rent_months),
        recovery_type=recovery_type,
        pro_rata_share=pro_rata_share,
        base_year_stop_amount=None,
        expense_stop_per_sf=None,
        recovery_overrides=(),
        pct_rent_breakpoint=None,
        pct_rent_rate=None,
        renewal_probability_override=None,
    )


def _add_ti_lc_to_first_slice(
    slices: list[MonthlySlice],
    ti_per_sf: Decimal,
    lc_pct: Decimal,
    area: Decimal,
) -> None:
    """
    Attach TI cost and LC cost to the first slice of a speculative lease.
    TI = $/SF * area (one-time at commencement).
    LC = pct * total rent over lease term (paid at lease signing, i.e. first month).
    """
    if not slices:
        return
    ti_cost = -(ti_per_sf * area)
    # LC based on total effective rent over the lease
    total_rent = sum(s.effective_rent for s in slices)
    lc_cost = -(total_rent * lc_pct)
    first = slices[0]
    first.ti_cost = ti_cost
    first.lc_cost = lc_cost


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
) -> tuple[list[MonthlySlice], list[LeaseInput]]:
    """
    Recursively generate probability-weighted speculative lease cash flows
    from a vacancy date through the end of the analysis period.

    Each call generates:
      - RENEWAL scenario (weight = cumulative_weight * renewal_probability)
      - NEW TENANT scenario (weight = cumulative_weight * (1 - renewal_probability))
      - Vacancy downtime slices for the new tenant scenario

    Then recurses when either speculative lease expires within the analysis period.

    Returns:
        (slices, lease_inputs) — all generated MonthlySlices and the LeaseInput
        objects used to generate them, so the caller can attach expense recoveries.
    """
    if generation >= _MAX_GENERATIONS:
        return [], []
    if vacancy_start_date >= analysis.end_date:
        return [], []

    # Lease-level renewal overrides apply to the first rollover only.
    renewal_prob = (
        renewal_probability_override
        if generation == 0 and renewal_probability_override is not None
        else market.renewal_probability
    )
    new_prob = Decimal(1) - renewal_prob

    all_slices: list[MonthlySlice] = []
    all_lease_inputs: list[LeaseInput] = []

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
        renewal_rent = max(renewal_rent, Decimal(0))

        renewal_start = vacancy_start_date
        renewal_end_raw = add_months(renewal_start, market.renewal_term_months) - timedelta(days=1)
        renewal_end = min(renewal_end_raw, analysis.end_date)

        renewal_lease = _build_speculative_lease(
            suite=suite,
            lease_id=f"spec_renew_{suite.suite_id}_g{generation}_{branch_path}R",
            tenant_label=f"Renewal Tenant (Gen {generation + 1})",
            start_date=renewal_start,
            end_date=renewal_end,
            rent=renewal_rent,
            growth_rate=market.rent_growth_rate,
            ti_per_sf=market.renewal_ti_per_sf,
            lc_pct=market.renewal_lc_pct,
            free_rent_months=market.renewal_free_rent_months,
            recovery_type=original_recovery_type,
            pro_rata_share=original_pro_rata_share,
            rent_payment_frequency=market.rent_payment_frequency,
        )
        all_lease_inputs.append(renewal_lease)

        renewal_slices = project_lease_cash_flows(
            renewal_lease, analysis,
            cpi_assumption=cpi_assumption,
            scenario_label="renewal",
            scenario_weight=renewal_weight,
        )
        _add_ti_lc_to_first_slice(
            renewal_slices, market.renewal_ti_per_sf, market.renewal_lc_pct, suite.area
        )
        all_slices.extend(renewal_slices)

        # Recurse when renewal lease expires within analysis period
        if renewal_end_raw < analysis.end_date:
            next_vacancy = renewal_end_raw + timedelta(days=1)
            rec_slices, rec_leases = generate_speculative_leases(
                suite=suite,
                vacancy_start_date=next_vacancy,
                analysis=analysis,
                market=market,
                original_recovery_type=original_recovery_type,
                original_pro_rata_share=original_pro_rata_share,
                cpi_assumption=cpi_assumption,
                generation=generation + 1,
                cumulative_weight=renewal_weight,
                branch_path=f"{branch_path}R",
            )
            all_slices.extend(rec_slices)
            all_lease_inputs.extend(rec_leases)

    # ===== NEW TENANT SCENARIO =====
    new_weight = cumulative_weight * new_prob
    if new_weight > Decimal("0.0001"):
        # Downtime: vacant period before new tenant commences
        new_tenant_start_raw = add_months(vacancy_start_date, market.downtime_months)
        new_tenant_start = min(new_tenant_start_raw, analysis.end_date)

        # Vacancy slices during downtime
        if market.downtime_months > 0 and vacancy_start_date < new_tenant_start:
            downtime_end = new_tenant_start - timedelta(days=1)
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

            new_lease = _build_speculative_lease(
                suite=suite,
                lease_id=f"spec_new_{suite.suite_id}_g{generation}_{branch_path}N",
                tenant_label=f"New Tenant (Gen {generation + 1})",
                start_date=new_tenant_start,
                end_date=new_end,
                rent=new_rent,
                growth_rate=market.rent_growth_rate,
                ti_per_sf=market.new_ti_per_sf,
                lc_pct=market.new_lc_pct,
                free_rent_months=market.new_free_rent_months,
                recovery_type=original_recovery_type,
                pro_rata_share=original_pro_rata_share,
                rent_payment_frequency=market.rent_payment_frequency,
            )
            all_lease_inputs.append(new_lease)

            new_slices = project_lease_cash_flows(
                new_lease, analysis,
                cpi_assumption=cpi_assumption,
                scenario_label="new_tenant",
                scenario_weight=new_weight,
            )
            _add_ti_lc_to_first_slice(
                new_slices, market.new_ti_per_sf, market.new_lc_pct, suite.area
            )
            all_slices.extend(new_slices)

            # Recurse when new tenant lease expires within analysis period
            if new_end_raw < analysis.end_date:
                next_vacancy = new_end_raw + timedelta(days=1)
                rec_slices, rec_leases = generate_speculative_leases(
                    suite=suite,
                    vacancy_start_date=next_vacancy,
                    analysis=analysis,
                    market=market,
                    original_recovery_type=original_recovery_type,
                    original_pro_rata_share=original_pro_rata_share,
                    cpi_assumption=cpi_assumption,
                    generation=generation + 1,
                    cumulative_weight=new_weight,
                    branch_path=f"{branch_path}N",
                )
                all_slices.extend(rec_slices)
                all_lease_inputs.extend(rec_leases)

    return all_slices, all_lease_inputs
