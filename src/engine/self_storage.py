"""
Self storage engine: monthly unit-mix revenue build feeding the shared DCF math.

Revenue per unit type is tracked in tenure buckets so existing-customer rate increases
(ECRI) hit the right customers: a move-in enters bucket 0, ages one bucket a month, gets its
first increase on reaching bucket `first_after_months`, then every `interval_months` (the
buckets from `first_after_months` on form a cycle). The opening book, whose move-in dates are
unknown, is spread evenly across that cycle.

Month order: age buckets; apply ECRI (rent up, extra move-outs); base move-outs; move-ins at
the year's street rate up to the target occupancy; first-month concession on move-ins.

Rows use the shared cash flow fields: gross_potential_rent is the in-place rent actually billed;
absorption_vacancy (street rent on vacant units) and loss_to_lease (in-place minus street on
occupied units, positive when customers pay above street) are informational, as in the
waterfall, so street rent x all units = GPR - absorption_vacancy - loss_to_lease.

The operating model is any object shaped like src.schemas.self_storage.SelfStorageOperatingModel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.engine.date_utils import add_months, build_analysis_period, build_monthly_buckets
from src.engine.dcf import (
    build_debt_schedule_detail,
    build_monthly_debt_detail,
    calculate_irr,
    calculate_terminal_value_breakdown,
    discount_cash_flows,
    discount_monthly_cash_flows,
    equity_multiple,
    going_in_cap_rate,
    irr_from_series,
)
from src.engine.expense_engine import occupancy_adjusted_expense
from src.engine.growth import growth_factor_to_year, market_rent_at_year, scheduled_amount_at_year
from src.engine.property_cashflow import _aggregate_monthly_cash_flows
from src.engine.returns import compute_investment_returns, direct_cap_value
from src.engine.types import (
    AnnualPropertyCashFlow,
    CapitalProjectInput,
    EngineResult,
    ExpenseInput,
    OtherIncomeInput,
    ValuationParams,
)

ZERO = Decimal(0)
TWELVE = Decimal(12)


@dataclass
class _TypeState:
    unit: Any  # StorageUnitType
    units: list[Decimal]  # per tenure bucket
    rent: list[Decimal]  # total monthly rent per tenure bucket
    opening: Decimal
    target: Decimal


@dataclass
class _Month:
    """Operating statistics for one month (one entry per unit type in by_type)."""
    occupied: Decimal = ZERO
    occupied_sf: Decimal = ZERO
    move_ins: Decimal = ZERO
    move_outs: Decimal = ZERO
    ecri_move_outs: Decimal = ZERO
    street_rent_all: Decimal = ZERO  # street x all units
    by_type: dict[str, tuple[Decimal, Decimal, Decimal]] = field(default_factory=dict)  # occupied, rent, street


def _new_state(unit, first: int, cycle: int, ecri_on: bool) -> _TypeState:
    size = first + cycle if ecri_on else 1
    units = [ZERO] * size
    rent = [ZERO] * size
    start = first if ecri_on else 0
    spread = size - start
    occupied = Decimal(unit.occupied_units)
    for i in range(start, size):
        units[i] = occupied / spread
        rent[i] = occupied * unit.in_place_rate / spread
    target_pct = unit.stabilized_occupancy
    target = (target_pct * unit.count) if target_pct is not None else occupied
    return _TypeState(unit=unit, units=units, rent=rent, opening=occupied, target=target)


def _simulate(model, buckets) -> tuple[list[dict], list[_Month]]:
    """Monthly revenue lines (before credit loss) and operating statistics."""
    ecri = model.ecri
    ecri_on = ecri.enabled and ecri.increase_pct + ecri.extra_move_out_pct > 0
    first, cycle = ecri.first_after_months, ecri.interval_months
    churn = model.churn.monthly_move_out_pct
    discount = model.concessions.first_month_discount_pct
    states = [_new_state(u, first, cycle, ecri_on) for u in model.unit_types]
    schedule = tuple(model.street_rate_growth_schedule)

    # Lease-up: net absorption above the opening book is capped facility-wide and shared by
    # each type's gap to stabilization
    cap = model.lease_up.monthly_net_absorption_units
    total_gap = sum((max(ZERO, s.target - s.opening) for s in states), ZERO)

    revenue: list[dict] = []
    stats: list[_Month] = []
    for m, bucket in enumerate(buckets):
        year = bucket.year_number
        fraction = Decimal(1) if not cap or total_gap <= 0 else min(Decimal(1), cap * (m + 1) / total_gap)
        month = _Month()
        in_place = concession = vacancy = ZERO
        for s in states:
            unit = s.unit
            street = market_rent_at_year(unit.street_rate, model.street_rate_growth_pct, year, schedule)
            size = len(s.units)
            if ecri_on:
                units, rent = [ZERO] * size, [ZERO] * size
                for i in range(size):
                    j = i + 1 if i + 1 < size else first
                    units[j] += s.units[i]
                    rent[j] += s.rent[i]
                hit = units[first]
                if hit > 0:
                    keep = Decimal(1) - ecri.extra_move_out_pct
                    month.ecri_move_outs += hit * ecri.extra_move_out_pct
                    rent[first] = rent[first] * (Decimal(1) + ecri.increase_pct) * keep
                    units[first] = hit * keep
                s.units, s.rent = units, rent
            if churn > 0:
                month.move_outs += sum(s.units, ZERO) * churn
                s.units = [u * (Decimal(1) - churn) for u in s.units]
                s.rent = [r * (Decimal(1) - churn) for r in s.rent]
            target = s.target
            if cap and s.target > s.opening:
                target = s.opening + (s.target - s.opening) * fraction
            occupied = sum(s.units, ZERO)
            move_ins = max(ZERO, target - occupied)
            s.units[0] += move_ins
            s.rent[0] += move_ins * street
            occupied += move_ins
            type_rent = sum(s.rent, ZERO)

            in_place += type_rent
            concession += move_ins * street * discount
            vacancy += street * (unit.count - occupied)
            month.move_ins += move_ins
            month.occupied += occupied
            month.occupied_sf += occupied * unit.sf_per_unit
            month.street_rent_all += street * unit.count
            month.by_type[unit.name] = (occupied, type_rent, street)
        month.move_outs += month.ecri_move_outs
        revenue.append({"in_place": in_place, "concession": concession, "vacancy": vacancy})
        stats.append(month)
    return revenue, stats


def _ancillary(model, year: int, month: _Month, rental: Decimal) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for line in model.ancillary_lines:
        grown = line.amount * growth_factor_to_year(line.growth_pct, year)
        if line.basis == "annual_fixed":
            amount = grown / TWELVE
        elif line.basis == "per_occupied_unit_month":
            amount = grown * month.occupied
        elif line.basis == "per_move_in":
            amount = grown * month.move_ins
        else:  # pct_of_rental
            amount = line.amount * rental
        out[line.name] = out.get(line.name, ZERO) + amount * line.participation_pct
    return out


def _monthly_rows(
    model, buckets, revenue, stats, expenses, params, capital_projects, other_income_items, debt_by_month,
) -> list[AnnualPropertyCashFlow]:
    rentable_sf = sum((u.sf_per_unit * u.count for u in model.unit_types), ZERO)
    egi_lines = [e for e in expenses if e.is_pct_of_egi and e.pct_of_egi]
    fixed_lines = [e for e in expenses if not e.is_pct_of_egi and not e.is_memo]
    rows = []
    for m, bucket in enumerate(buckets):
        year = bucket.year_number
        rev, month = revenue[m], stats[m]
        rental = rev["in_place"] - rev["concession"]
        other = _ancillary(model, year, month, rental)
        for oi in other_income_items:
            amount = scheduled_amount_at_year(
                oi.base_amount, oi.growth_rate, year, oi.growth_schedule, oi.amount_schedule
            ) / TWELVE
            other[oi.category] = other.get(oi.category, ZERO) + amount
        other_total = sum(other.values(), ZERO)
        gpi = rev["in_place"] - rev["concession"] + other_total
        credit_loss = -(rental * model.credit_loss_pct)
        egi = gpi + credit_loss

        sf_occupancy = month.occupied_sf / rentable_sf if rentable_sf > 0 else ZERO
        detail: dict[str, Decimal] = {}
        for exp in fixed_lines:
            annual = scheduled_amount_at_year(
                exp.base_amount, exp.growth_rate, year, exp.growth_schedule, exp.amount_schedule
            )
            amount = occupancy_adjusted_expense(annual, exp, sf_occupancy) / TWELVE
            detail[exp.category] = detail.get(exp.category, ZERO) + amount
        for exp in egi_lines:
            detail[exp.category] = detail.get(exp.category, ZERO) + egi * exp.pct_of_egi
        opex = sum(detail.values(), ZERO)
        noi = egi - opex

        reserves = -(params.capital_reserves_per_unit * params.total_property_area / TWELVE
                     * growth_factor_to_year(params.capital_reserves_growth_rate, year))
        improvements = ZERO
        for project in capital_projects:
            per_month = project.total_amount / Decimal(project.duration_months)
            for k in range(project.duration_months):
                if bucket.start_date <= add_months(project.start_date, k) <= bucket.end_date:
                    improvements -= per_month
        cfbd = noi + reserves + improvements
        debt = -(debt_by_month[m] if m < len(debt_by_month) else ZERO)
        rows.append(AnnualPropertyCashFlow(
            year=year,
            period_start=bucket.start_date,
            period_end=bucket.end_date,
            gross_potential_rent=rev["in_place"],
            free_rent=-rev["concession"],
            absorption_vacancy=-rev["vacancy"],
            loss_to_lease=rev["in_place"] - (month.street_rent_all - rev["vacancy"]),
            expense_recoveries=ZERO,
            percentage_rent=ZERO,
            other_income=other_total,
            gross_potential_income=gpi,
            general_vacancy_loss=ZERO,
            credit_loss=credit_loss,
            effective_gross_income=egi,
            operating_expenses=-opex,
            net_operating_income=noi,
            tenant_improvements=ZERO,
            leasing_commissions=ZERO,
            capital_reserves=reserves,
            building_improvements=improvements,
            cash_flow_before_debt=cfbd,
            debt_service=debt,
            levered_cash_flow=cfbd + debt,
            expense_detail={k: -v for k, v in detail.items()},
            other_income_detail=other,
        ))
    return rows


def _storage_detail(model, analysis, buckets, stats, rows) -> list[dict]:
    """Per analysis year: occupancy, rates, customer movement and margins."""
    rentable_sf = sum((u.sf_per_unit * u.count for u in model.unit_types), ZERO)
    total_units = sum((Decimal(u.count) for u in model.unit_types), ZERO)
    sf_by_type = {u.name: u.sf_per_unit for u in model.unit_types}
    count_by_type = {u.name: Decimal(u.count) for u in model.unit_types}
    out = []
    for fy in analysis.fiscal_years:
        idx = [m for m, b in enumerate(buckets) if b.year_number == fy.year_number]
        if not idx:
            continue
        n = Decimal(len(idx))
        occupied = sum((stats[m].occupied for m in idx), ZERO) / n
        occupied_sf = sum((stats[m].occupied_sf for m in idx), ZERO) / n
        in_place = sum((rows[m].gross_potential_rent for m in idx), ZERO)
        street_all = sum((stats[m].street_rent_all for m in idx), ZERO)
        street_occupied = in_place - sum((rows[m].loss_to_lease for m in idx), ZERO)
        rental = in_place + sum((rows[m].free_rent for m in idx), ZERO)
        egi = sum((rows[m].effective_gross_income for m in idx), ZERO)
        noi = sum((rows[m].net_operating_income for m in idx), ZERO)
        occupied_sf_months = sum((stats[m].occupied_sf for m in idx), ZERO)
        by_type = []
        for u in model.unit_types:
            occ = sum((stats[m].by_type[u.name][0] for m in idx), ZERO)
            rent = sum((stats[m].by_type[u.name][1] for m in idx), ZERO)
            street = stats[idx[-1]].by_type[u.name][2]
            by_type.append({
                "name": u.name,
                "occupancy_pct": occ / n / count_by_type[u.name] if count_by_type[u.name] else ZERO,
                "in_place_rate": rent / occ if occ else ZERO,
                "street_rate": street,
            })
        out.append({
            "year": fy.year_number,
            "units": total_units,
            "rentable_sf": rentable_sf,
            "occupied_units": occupied,
            "physical_occupancy_units": occupied / total_units if total_units else ZERO,
            "physical_occupancy_sf": occupied_sf / rentable_sf if rentable_sf else ZERO,
            "economic_occupancy": rental / street_all if street_all else ZERO,
            "in_place_rent_per_occupied_sf": in_place * TWELVE / occupied_sf_months if occupied_sf_months else ZERO,
            "street_rent_per_occupied_sf": street_occupied * TWELVE / occupied_sf_months if occupied_sf_months else ZERO,
            "rate_gap_pct": in_place / street_occupied - 1 if street_occupied else ZERO,
            "move_ins": sum((stats[m].move_ins for m in idx), ZERO),
            "move_outs": sum((stats[m].move_outs for m in idx), ZERO),
            "ecri_move_outs": sum((stats[m].ecri_move_outs for m in idx), ZERO),
            "revenue_per_available_sf": egi / rentable_sf if rentable_sf else ZERO,
            "noi_margin": noi / egi if egi else ZERO,
            "by_type": by_type,
        })
    return out


def run_self_storage(
    model,
    property_start_date,
    analysis_period_months: int,
    fiscal_year_end_month: int,
    expenses: list[ExpenseInput],
    params: ValuationParams,
    capital_projects: list[CapitalProjectInput] | None = None,
    other_income_items: list[OtherIncomeInput] | None = None,
    include_monthly: bool = False,
) -> EngineResult:
    """Value a self storage facility from its operating model."""
    if params.discounting_convention == "monthly" and params.use_mid_year_convention:
        raise ValueError("use_mid_year_convention is not supported with monthly discounting")
    capital_projects = capital_projects or []
    other_income_items = other_income_items or []

    # One simulation covers the hold plus the forward year used for the exit NOI
    extended = build_analysis_period(property_start_date, analysis_period_months + 12, fiscal_year_end_month)
    analysis = build_analysis_period(property_start_date, analysis_period_months, fiscal_year_end_month)
    buckets = build_monthly_buckets(extended).fiscal_years
    revenue, stats = _simulate(model, buckets)
    debt_by_month, _, _ = build_monthly_debt_detail(params, analysis.num_months)
    rows = _monthly_rows(model, buckets, revenue, stats, expenses, params, capital_projects,
                         other_income_items, debt_by_month)

    hold_years = len(analysis.fiscal_years)
    extended_annual = _aggregate_monthly_cash_flows(rows, extended)
    annual_cfs = extended_annual[:hold_years]
    monthly_cfs = rows[:analysis.num_months]
    _, debt_balances, debt_balloons = build_debt_schedule_detail(params, hold_years, analysis.num_months)

    forward_noi, forward_capital = None, ZERO
    if len(extended_annual) > hold_years:
        forward = extended_annual[hold_years]
        forward_noi = forward.net_operating_income
        forward_capital = -forward.building_improvements
    terminal = calculate_terminal_value_breakdown(annual_cfs, params, forward_noi, forward_capital)
    terminal_value = terminal.net_value

    monthly = params.discounting_convention == "monthly"
    if monthly:
        pv_cfs, pv_terminal, npv = discount_monthly_cash_flows(monthly_cfs, terminal_value, params.discount_rate)
        series = [-npv] + [cf.cash_flow_before_debt for cf in monthly_cfs]
        series[-1] += terminal_value
        monthly_irr = irr_from_series(series)
        irr = (Decimal(1) + monthly_irr) ** 12 - Decimal(1) if monthly_irr is not None else None
    else:
        pv_cfs, pv_terminal, npv = discount_cash_flows(
            annual_cfs, terminal_value, params.discount_rate, params.use_mid_year_convention,
            params.terminal_timing,
        )
        irr = calculate_irr(annual_cfs, terminal_value, initial_investment=npv)

    year1_noi = annual_cfs[0].net_operating_income if annual_cfs else ZERO
    gin_cap = going_in_cap_rate(year1_noi, npv) if npv > 0 else ZERO
    returns = compute_investment_returns(
        annual_cfs, terminal_value, npv, params, debt_balances, debt_balloons,
        monthly_cfs if monthly else None,
    )
    total_cfbd = sum((cf.cash_flow_before_debt for cf in annual_cfs), ZERO)
    em = equity_multiple(total_cfbd + terminal_value, npv) if npv > 0 else None
    if returns is not None:
        irr = returns.unlevered_irr
        gin_cap = returns.going_in_cap_rate
        em = returns.unlevered_equity_multiple

    rentable_sf = sum((u.sf_per_unit * u.count for u in model.unit_types), ZERO)
    hold_stats = stats[:analysis.num_months]
    avg_occ = (
        sum((s.occupied_sf for s in hold_stats), ZERO) / Decimal(len(hold_stats)) / rentable_sf
        if hold_stats and rentable_sf > 0 else ZERO
    )
    return EngineResult(
        annual_cash_flows=annual_cfs,
        suite_annual_details=[],
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
        monthly_cash_flows=monthly_cfs if (include_monthly or monthly) else [],
        storage_detail=_storage_detail(model, analysis, buckets[:analysis.num_months], hold_stats,
                                       rows[:analysis.num_months]),
    )
