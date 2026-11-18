"""
Seniors housing valuation module.

Model coverage:
- Acuity levels: Independent Living (IL), Assisted Living (AL), Memory Care (MC),
  Skilled Nursing (SNF).
- Unit types: studio, 1BR, 2BR, semi-private, private per acuity level.
- Revenue: monthly service fees, tiered care-level surcharges, second-person fees,
  community fees (booked on move-in), ancillary revenue, SNF payer-mix reimbursement.
- Census/occupancy: stabilized targets, ramp-up modeling, monthly turnover,
  absorption rates.
- Expenses: labor by department (variable + fixed), food/dietary, insurance,
  marketing, management fee, utilities, property taxes, medical supplies,
  capital reserves — all scalable by acuity and census.
- Outputs: unlevered/levered DCF, IRR, terminal value, key operating metrics
  (RevPOR, RevPAR, EBITDARM, staffing ratios), unit-type detail drill-down.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from decimal import Decimal
from itertools import product
from typing import Literal

AcuityLevel = Literal["independent_living", "assisted_living", "memory_care", "skilled_nursing"]
UnitType = Literal["studio", "one_br", "two_br", "semi_private", "private", "cottage"]
PayerType = Literal["private_pay", "medicare", "medicaid", "medicare_advantage", "insurance"]

ONE = Decimal(1)
ZERO = Decimal(0)
TWELVE = Decimal(12)
THIRTY = Decimal("30.42")


def _d(value: int | str | float | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _clamp(value: Decimal, low: Decimal = ZERO, high: Decimal = ONE) -> Decimal:
    return max(low, min(high, value))


def _grow(base: Decimal, growth_rate: Decimal, year_number: int) -> Decimal:
    return base * (ONE + growth_rate) ** Decimal(str(max(0, year_number - 1)))


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CareLevelTier:
    """A single care-level surcharge tier within an acuity level."""
    name: str
    monthly_surcharge: Decimal
    pct_of_residents: Decimal  # fraction of residents at this care level


@dataclass(frozen=True)
class UnitTypeInput:
    """A unit type within an acuity level (e.g. 'AL Studio', 'MC Private')."""
    name: str
    acuity: AcuityLevel
    unit_type: UnitType
    count: int
    avg_sf: Decimal
    monthly_base_fee: Decimal
    second_person_fee_monthly: Decimal = ZERO
    second_person_pct: Decimal = ZERO  # fraction of units with 2nd occupant
    community_fee: Decimal = ZERO  # one-time move-in fee
    avg_length_of_stay_months: Decimal = Decimal("24")  # informational; community fees are booked on move-in
    stabilized_occupancy: Decimal = Decimal("0.90")
    annual_turnover_rate: Decimal = Decimal("0.40")
    care_level_tiers: tuple[CareLevelTier, ...] = ()


@dataclass(frozen=True)
class SNFPayerMixInput:
    """Payer mix and per-diem rates for skilled nursing units."""
    payer: PayerType
    pct_of_days: Decimal
    daily_rate: Decimal
    annual_rate_growth: Decimal = Decimal("0.02")


@dataclass(frozen=True)
class AncillaryRevenueInput:
    """An ancillary revenue line item (per-unit or fixed)."""
    name: str
    annual_fixed: Decimal = ZERO
    per_occupied_unit_month: Decimal = ZERO
    growth_pct: Decimal = Decimal("0.03")
    applies_to_acuity: tuple[AcuityLevel, ...] = ()  # empty = all


@dataclass(frozen=True)
class ExpenseLineInput:
    """An operating expense line item."""
    name: str
    category: str  # labor, food, insurance, marketing, utilities, property_tax, etc.
    annual_fixed: Decimal = ZERO
    per_occupied_unit_month: Decimal = ZERO
    pct_of_revenue: Decimal = ZERO  # e.g. management fee as % of revenue
    growth_pct: Decimal | None = None  # None = the valuation's expense_growth_rate
    is_variable: bool = True  # scales with occupancy (for variable portion)
    applies_to_acuity: tuple[AcuityLevel, ...] = ()  # empty = all


@dataclass(frozen=True)
class CapexInput:
    """Capital expenditure / reserve item."""
    name: str
    annual_per_unit: Decimal = ZERO
    annual_fixed: Decimal = ZERO
    growth_pct: Decimal = Decimal("0.03")


@dataclass(frozen=True)
class OccupancyRampInput:
    """Occupancy ramp-up schedule for lease-up scenarios."""
    start_occupancy: Decimal = Decimal("0.30")
    monthly_absorption_units: Decimal = Decimal("5")
    stabilization_month: int | None = None  # auto-calculated if None


@dataclass(frozen=True)
class DebtInput:
    loan_amount: Decimal | None = None
    interest_rate: Decimal | None = None
    amortization_months: int | None = None
    term_months: int | None = None
    io_period_months: int = 0
    minimum_dscr: Decimal = Decimal("1.30")
    maximum_ltv: Decimal = Decimal("0.65")


@dataclass(frozen=True)
class ValuationAssumptions:
    hold_years: int
    discount_rate: Decimal
    exit_cap_rate: Decimal
    exit_costs_pct: Decimal = Decimal("0.02")
    use_mid_year_convention: bool = False
    terminal_noi_growth_pct: Decimal = Decimal("0.02")
    fee_growth_rate: Decimal = Decimal("0.04")  # annual rate increase
    expense_growth_rate: Decimal = Decimal("0.035")  # annual expense growth
    initial_purchase_price: Decimal | None = None
    levered_discount_rate: Decimal | None = None


@dataclass(frozen=True)
class SeniorsHousingModelInput:
    as_of_date: object  # date
    community_name: str
    unit_types: tuple[UnitTypeInput, ...]
    snf_payer_mix: tuple[SNFPayerMixInput, ...] = ()
    ancillary_revenue: tuple[AncillaryRevenueInput, ...] = ()
    expenses: tuple[ExpenseLineInput, ...]  = ()
    capex: tuple[CapexInput, ...] = ()
    valuation: ValuationAssumptions = None  # type: ignore[assignment]
    occupancy_ramp: OccupancyRampInput | None = None
    debt: DebtInput | None = None


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------


@dataclass
class UnitTypeAnnualDetail:
    """Annual revenue detail for a single unit type — the expandable row."""
    unit_type_name: str
    acuity: str
    unit_type: str
    unit_count: int
    occupied_units: Decimal
    occupancy_pct: Decimal
    base_rent_revenue: Decimal
    care_level_revenue: Decimal
    second_person_revenue: Decimal
    community_fee_revenue: Decimal
    snf_payer_revenue: Decimal
    total_revenue: Decimal


@dataclass
class ExpenseLineAnnualDetail:
    """Annual detail for a single expense line — the expandable row."""
    name: str
    category: str
    amount: Decimal
    per_unit_month: Decimal  # amount / occupied_unit_months for reference
    acuity_breakdown: dict[str, Decimal]  # acuity -> amount contributed


@dataclass
class AncillaryLineAnnualDetail:
    name: str
    amount: Decimal


@dataclass
class CapexLineAnnualDetail:
    name: str
    amount: Decimal


@dataclass
class SeniorsHousingAnnualCashFlow:
    year: int
    # Revenue
    base_rent_revenue: Decimal
    care_level_revenue: Decimal
    second_person_revenue: Decimal
    community_fee_revenue: Decimal
    snf_payer_revenue: Decimal
    ancillary_revenue: Decimal
    potential_gross_revenue: Decimal
    effective_gross_income: Decimal  # after vacancy (census-driven)
    # Expenses
    total_labor: Decimal
    total_food_dietary: Decimal
    total_insurance: Decimal
    total_marketing: Decimal
    total_utilities: Decimal
    total_property_tax: Decimal
    total_medical_supplies: Decimal
    management_fee: Decimal
    total_other_expenses: Decimal
    total_operating_expenses: Decimal
    # Profitability
    noi: Decimal
    ebitdarm: Decimal  # NOI + management fee (property-level before mgmt)
    total_capex: Decimal
    cash_flow_before_debt: Decimal
    debt_service: Decimal
    balloon_payment: Decimal
    levered_cash_flow: Decimal
    # Operating metrics
    total_units: int
    occupied_units: Decimal
    avg_occupancy_pct: Decimal
    rev_por: Decimal  # revenue per occupied room per month
    rev_par: Decimal  # revenue per available room per month
    operating_expense_ratio: Decimal
    noi_margin: Decimal
    # Drill-down detail
    unit_type_detail: list[UnitTypeAnnualDetail]
    expense_detail: list[ExpenseLineAnnualDetail]
    ancillary_detail: list[AncillaryLineAnnualDetail]
    capex_detail: list[CapexLineAnnualDetail]


@dataclass
class SeniorsHousingValuationResult:
    annual_cash_flows: list[SeniorsHousingAnnualCashFlow]
    terminal_noi: Decimal
    terminal_value_gross: Decimal
    terminal_value_net: Decimal
    pv_unlevered_cash_flows: Decimal
    pv_unlevered_terminal: Decimal
    npv_unlevered: Decimal
    irr_unlevered: Decimal | None
    going_in_cap_rate: Decimal | None
    pv_levered_cash_flows: Decimal
    npv_levered: Decimal
    irr_levered: Decimal | None
    equity_value: Decimal


# ---------------------------------------------------------------------------
# Debt service
# ---------------------------------------------------------------------------


def _monthly_payment(principal: Decimal, monthly_rate: Decimal, n_months: int) -> Decimal:
    if n_months <= 0:
        return ZERO
    if monthly_rate == ZERO:
        return principal / _d(n_months)
    r = monthly_rate
    n = _d(n_months)
    return principal * (r * (ONE + r) ** n) / ((ONE + r) ** n - ONE)


def _build_debt_service(
    debt: DebtInput | None, hold_years: int
) -> tuple[list[Decimal], list[Decimal], list[Decimal]]:
    """Returns (annual_service, annual_balloon, annual_end_balance)."""
    if debt is None or debt.loan_amount is None or debt.interest_rate is None:
        zeros = [ZERO] * hold_years
        return zeros, zeros, zeros

    loan = debt.loan_amount
    monthly_rate = debt.interest_rate / TWELVE
    amort_months = debt.amortization_months or 360
    term_months = debt.term_months
    io_months = debt.io_period_months or 0
    fixed_pmt = _monthly_payment(loan, monthly_rate, amort_months)

    balance = loan
    svc: list[Decimal] = []
    balloons: list[Decimal] = []
    balances: list[Decimal] = []

    for year in range(1, hold_years + 1):
        yr_svc = ZERO
        yr_balloon = ZERO
        for m in range(1, 13):
            month_num = (year - 1) * 12 + m
            if term_months is not None and month_num > term_months:
                continue
            is_maturity = term_months is not None and month_num == term_months
            interest = balance * monthly_rate
            if month_num <= io_months:
                yr_svc += interest
                if is_maturity:
                    yr_balloon += balance
                    balance = ZERO
            else:
                principal = min(fixed_pmt - interest, balance)
                principal = max(ZERO, principal)
                # Pay only what remains; nothing is due once the loan is repaid.
                yr_svc += interest + principal
                if is_maturity:
                    yr_balloon += balance - principal
                    balance = ZERO
                else:
                    balance -= principal
        svc.append(yr_svc)
        balloons.append(yr_balloon)
        balances.append(balance)

    return svc, balloons, balances


# ---------------------------------------------------------------------------
# IRR / discounting
# ---------------------------------------------------------------------------


def _irr(cash_flows: list[Decimal]) -> Decimal | None:
    if not cash_flows:
        return None
    if not (any(c > 0 for c in cash_flows) and any(c < 0 for c in cash_flows)):
        return None
    cfs = [float(c) for c in cash_flows]

    def npv(rate: float) -> float:
        return sum(cf / ((1 + rate) ** t) for t, cf in enumerate(cfs))

    def dnpv(rate: float) -> float:
        return sum(-(t * cf) / ((1 + rate) ** (t + 1)) for t, cf in enumerate(cfs))

    for guess in [0.08, 0.12, 0.04, 0.18, 0.25]:
        rate = guess
        try:
            for _ in range(200):
                denom = dnpv(rate)
                if abs(denom) < 1e-14:
                    break
                new_rate = rate - npv(rate) / denom
                new_rate = max(new_rate, -0.99)
                if abs(new_rate - rate) < 1e-10:
                    rate = new_rate
                    break
                rate = new_rate
            if abs(npv(rate)) < 0.01:
                return Decimal(str(round(rate, 8)))
        except (ZeroDivisionError, OverflowError):
            continue
    return None


def _discount_cash_flows(
    annual_cfs: list[Decimal],
    terminal_value: Decimal,
    discount_rate: Decimal,
    use_mid_year: bool,
) -> tuple[Decimal, Decimal, Decimal]:
    pv_cf = ZERO
    for idx, cf in enumerate(annual_cfs):
        year = idx + 1
        t = _d(year) - (Decimal("0.5") if use_mid_year else ZERO)
        pv_cf += cf / (ONE + discount_rate) ** t
    n = _d(len(annual_cfs)) - (Decimal("0.5") if use_mid_year else ZERO)
    pv_term = terminal_value / (ONE + discount_rate) ** n
    return pv_cf, pv_term, pv_cf + pv_term


# ---------------------------------------------------------------------------
# Occupancy / census
# ---------------------------------------------------------------------------


def _effective_occupancy(
    unit: UnitTypeInput,
    year: int,
    month: int,
    ramp: OccupancyRampInput | None,
    total_units_all: int,
) -> Decimal:
    """Return occupied units for a unit type in a given month."""
    if ramp is None:
        return _d(unit.count) * _clamp(unit.stabilized_occupancy)

    global_month = (year - 1) * 12 + month
    stabilized = _d(unit.count) * _clamp(unit.stabilized_occupancy)

    if ramp.stabilization_month and global_month >= ramp.stabilization_month:
        return stabilized

    # Ramp: start at start_occupancy, absorb monthly_absorption_units total across
    # all unit types, distributed proportionally by unit count.
    unit_share = _d(unit.count) / _d(max(total_units_all, 1))
    start_units = _d(unit.count) * _clamp(ramp.start_occupancy)
    absorbed = ramp.monthly_absorption_units * unit_share * _d(max(0, global_month - 1))
    return min(start_units + absorbed, stabilized)


def _validate_model_inputs(model: SeniorsHousingModelInput) -> None:
    for ut in model.unit_types:
        tier_total = sum((tier.pct_of_residents for tier in ut.care_level_tiers), ZERO)
        if tier_total > ONE:
            raise ValueError(
                f"Unit type '{ut.name}' care_level_tiers pct_of_residents must sum to <= 1."
            )
    payer_total = sum((pm.pct_of_days for pm in model.snf_payer_mix), ZERO)
    if payer_total > ONE:
        raise ValueError("SNF payer mix pct_of_days must sum to <= 1.")


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


def run_seniors_housing_valuation(
    model: SeniorsHousingModelInput,
) -> SeniorsHousingValuationResult:
    _validate_model_inputs(model)
    v = model.valuation
    hold_years = v.hold_years
    total_units = sum(u.count for u in model.unit_types)

    debt_svc, balloons, debt_bal = _build_debt_service(model.debt, hold_years)
    annual_rows: list[SeniorsHousingAnnualCashFlow] = []

    # Pre-index unit types by acuity for expense allocation
    acuity_set: set[str] = {u.acuity for u in model.unit_types}

    for year in range(1, hold_years + 1):
        # ── Revenue by unit type ──────────────────────────────────────────
        ut_details: list[UnitTypeAnnualDetail] = []
        year_base_rent = ZERO
        year_care_rev = ZERO
        year_second_rev = ZERO
        year_community_rev = ZERO
        year_snf_rev = ZERO
        year_total_occupied = ZERO

        for ut in model.unit_types:
            # Monthly loop for occupancy precision
            ut_occ_total = ZERO
            ut_base = ZERO
            ut_care = ZERO
            ut_second = ZERO
            ut_community = ZERO
            ut_snf = ZERO

            for month in range(1, 13):
                occ = _effective_occupancy(ut, year, month, model.occupancy_ramp, total_units)
                days_in_month = _d(calendar.monthrange(
                    model.as_of_date.year + year - 1, month
                )[1])
                ut_occ_total += occ

                # Base rent (monthly fee * occupied units, grown)
                grown_fee = _grow(ut.monthly_base_fee, v.fee_growth_rate, year)
                ut_base += occ * grown_fee

                # Care-level surcharges
                for tier in ut.care_level_tiers:
                    grown_surcharge = _grow(tier.monthly_surcharge, v.fee_growth_rate, year)
                    ut_care += occ * _clamp(tier.pct_of_residents) * grown_surcharge

                # Second person fees
                if ut.second_person_pct > ZERO:
                    grown_sp = _grow(ut.second_person_fee_monthly, v.fee_growth_rate, year)
                    ut_second += occ * _clamp(ut.second_person_pct) * grown_sp

                # Community fees, booked when received: turnover move-ins
                # (occupied * turnover_rate / 12) plus lease-up move-ins (net
                # occupancy gain over the prior month)
                if ut.community_fee > ZERO:
                    if year == 1 and month == 1:
                        prior_occ = occ  # residents at the start are already in place
                    else:
                        prior_year, prior_month = (year, month - 1) if month > 1 else (year - 1, 12)
                        prior_occ = _effective_occupancy(ut, prior_year, prior_month, model.occupancy_ramp, total_units)
                    monthly_moveins = occ * ut.annual_turnover_rate / TWELVE + max(ZERO, occ - prior_occ)
                    grown_cf = _grow(ut.community_fee, v.fee_growth_rate, year)
                    ut_community += monthly_moveins * grown_cf

                # SNF payer revenue (replaces base rent for SNF units)
                if ut.acuity == "skilled_nursing" and model.snf_payer_mix:
                    snf_month_rev = ZERO
                    for pm in model.snf_payer_mix:
                        grown_rate = _grow(pm.daily_rate, pm.annual_rate_growth, year)
                        snf_month_rev += occ * _clamp(pm.pct_of_days) * grown_rate * days_in_month
                    ut_snf += snf_month_rev

            avg_occ = ut_occ_total / TWELVE
            year_total_occupied += avg_occ

            # For SNF: snf_payer_revenue IS the primary revenue, base_rent is the
            # private-pay component already captured in payer mix
            if ut.acuity == "skilled_nursing" and model.snf_payer_mix:
                ut_total = ut_snf + ut_care + ut_second + ut_community
                year_snf_rev += ut_snf
            else:
                ut_total = ut_base + ut_care + ut_second + ut_community
                year_base_rent += ut_base

            year_care_rev += ut_care
            year_second_rev += ut_second
            year_community_rev += ut_community

            occ_pct = avg_occ / _d(max(ut.count, 1))
            ut_details.append(UnitTypeAnnualDetail(
                unit_type_name=ut.name,
                acuity=ut.acuity,
                unit_type=ut.unit_type,
                unit_count=ut.count,
                occupied_units=avg_occ,
                occupancy_pct=occ_pct,
                base_rent_revenue=ut_base,
                care_level_revenue=ut_care,
                second_person_revenue=ut_second,
                community_fee_revenue=ut_community,
                snf_payer_revenue=ut_snf,
                total_revenue=ut_total,
            ))

        # ── Ancillary revenue ─────────────────────────────────────────────
        year_ancillary = ZERO
        ancillary_details: list[AncillaryLineAnnualDetail] = []
        for anc in model.ancillary_revenue:
            anc_amount = _grow(anc.annual_fixed, anc.growth_pct, year)
            # Per occupied unit (filtered by acuity if specified)
            if anc.per_occupied_unit_month > ZERO:
                for ut_det in ut_details:
                    if anc.applies_to_acuity and ut_det.acuity not in anc.applies_to_acuity:
                        continue
                    grown_per_unit = _grow(anc.per_occupied_unit_month, anc.growth_pct, year)
                    anc_amount += ut_det.occupied_units * grown_per_unit * TWELVE
            year_ancillary += anc_amount
            ancillary_details.append(AncillaryLineAnnualDetail(name=anc.name, amount=anc_amount))

        # ── Gross revenue ─────────────────────────────────────────────────
        pgr = year_base_rent + year_care_rev + year_second_rev + year_community_rev + year_snf_rev + year_ancillary
        # EGI = PGR (vacancy is already reflected in census/occupancy model)
        egi = pgr

        # ── Expenses ──────────────────────────────────────────────────────
        expense_details: list[ExpenseLineAnnualDetail] = []
        cat_totals: dict[str, Decimal] = {}

        # Compute occupied units by acuity for expense allocation
        occ_by_acuity: dict[str, Decimal] = {}
        for ut_det in ut_details:
            occ_by_acuity[ut_det.acuity] = occ_by_acuity.get(ut_det.acuity, ZERO) + ut_det.occupied_units

        for exp in model.expenses:
            exp_amount = ZERO
            acuity_breakdown: dict[str, Decimal] = {}

            # pct_of_revenue (e.g. management fee)
            if exp.pct_of_revenue > ZERO:
                pct_amount = egi * _grow(exp.pct_of_revenue, ZERO, 1)  # pct doesn't grow
                exp_amount += pct_amount
            # Fixed portion (grown by expense growth)
            growth = exp.growth_pct if exp.growth_pct is not None else v.expense_growth_rate
            if exp.annual_fixed > ZERO:
                fixed_grown = _grow(exp.annual_fixed, growth, year)
                # Distribute fixed across applicable acuities proportionally
                applicable_acuities = exp.applies_to_acuity or tuple(acuity_set)
                total_applicable_units = sum(
                    occ_by_acuity.get(a, ZERO) for a in applicable_acuities
                )
                for a in applicable_acuities:
                    share = (
                        occ_by_acuity.get(a, ZERO) / total_applicable_units
                        if total_applicable_units > ZERO else ZERO
                    )
                    a_amount = fixed_grown * share
                    acuity_breakdown[a] = acuity_breakdown.get(a, ZERO) + a_amount
                exp_amount += fixed_grown

            # Per-occupied-unit portion
            if exp.per_occupied_unit_month > ZERO:
                applicable_acuities = exp.applies_to_acuity or tuple(acuity_set)
                grown_per = _grow(exp.per_occupied_unit_month, growth, year)
                for a in applicable_acuities:
                    occ = occ_by_acuity.get(a, ZERO)
                    a_amount = occ * grown_per * TWELVE
                    exp_amount += a_amount
                    acuity_breakdown[a] = acuity_breakdown.get(a, ZERO) + a_amount

            per_unit_m = (
                exp_amount / (year_total_occupied * TWELVE)
                if year_total_occupied > ZERO else ZERO
            )
            expense_details.append(ExpenseLineAnnualDetail(
                name=exp.name,
                category=exp.category,
                amount=exp_amount,
                per_unit_month=per_unit_m,
                acuity_breakdown=acuity_breakdown,
            ))
            cat_totals[exp.category] = cat_totals.get(exp.category, ZERO) + exp_amount

        total_opex = sum(e.amount for e in expense_details)

        # ── CapEx ─────────────────────────────────────────────────────────
        capex_details: list[CapexLineAnnualDetail] = []
        year_capex = ZERO
        for cx in model.capex:
            cx_amount = ZERO
            growth = cx.growth_pct
            if cx.annual_per_unit > ZERO:
                cx_amount += _grow(cx.annual_per_unit, growth, year) * _d(total_units)
            if cx.annual_fixed > ZERO:
                cx_amount += _grow(cx.annual_fixed, growth, year)
            year_capex += cx_amount
            capex_details.append(CapexLineAnnualDetail(name=cx.name, amount=cx_amount))

        # ── Profitability ─────────────────────────────────────────────────
        noi = egi - total_opex
        ebitdarm = noi + cat_totals.get("management_fee", ZERO)
        cfbd = noi - year_capex
        ds = debt_svc[year - 1]
        balloon = balloons[year - 1]
        lcf = cfbd - ds - balloon

        # ── Operating metrics ─────────────────────────────────────────────
        avg_occ_pct = year_total_occupied / _d(max(total_units, 1))
        rev_por = egi / (year_total_occupied * TWELVE) if year_total_occupied > ZERO else ZERO
        rev_par = egi / (_d(total_units) * TWELVE) if total_units > 0 else ZERO
        opex_ratio = total_opex / egi if egi > ZERO else ZERO
        noi_margin = noi / egi if egi > ZERO else ZERO

        annual_rows.append(SeniorsHousingAnnualCashFlow(
            year=year,
            base_rent_revenue=year_base_rent,
            care_level_revenue=year_care_rev,
            second_person_revenue=year_second_rev,
            community_fee_revenue=year_community_rev,
            snf_payer_revenue=year_snf_rev,
            ancillary_revenue=year_ancillary,
            potential_gross_revenue=pgr,
            effective_gross_income=egi,
            total_labor=cat_totals.get("labor", ZERO),
            total_food_dietary=cat_totals.get("food", ZERO),
            total_insurance=cat_totals.get("insurance", ZERO),
            total_marketing=cat_totals.get("marketing", ZERO),
            total_utilities=cat_totals.get("utilities", ZERO),
            total_property_tax=cat_totals.get("property_tax", ZERO),
            total_medical_supplies=cat_totals.get("medical_supplies", ZERO),
            management_fee=cat_totals.get("management_fee", ZERO),
            total_other_expenses=sum(
                v for k, v in cat_totals.items()
                if k not in ("labor", "food", "insurance", "marketing", "utilities",
                             "property_tax", "medical_supplies", "management_fee")
            ),
            total_operating_expenses=total_opex,
            noi=noi,
            ebitdarm=ebitdarm,
            total_capex=year_capex,
            cash_flow_before_debt=cfbd,
            debt_service=ds,
            balloon_payment=balloon,
            levered_cash_flow=lcf,
            total_units=total_units,
            occupied_units=year_total_occupied,
            avg_occupancy_pct=avg_occ_pct,
            rev_por=rev_por,
            rev_par=rev_par,
            operating_expense_ratio=opex_ratio,
            noi_margin=noi_margin,
            unit_type_detail=ut_details,
            expense_detail=expense_details,
            ancillary_detail=ancillary_details,
            capex_detail=capex_details,
        ))

    # ── Terminal value & DCF ──────────────────────────────────────────────
    last_noi = annual_rows[-1].noi if annual_rows else ZERO
    terminal_noi = last_noi * (ONE + v.terminal_noi_growth_pct)
    terminal_gross = terminal_noi / v.exit_cap_rate if v.exit_cap_rate > ZERO else ZERO
    terminal_net = terminal_gross * (ONE - v.exit_costs_pct)

    unlevered_cfs = [row.cash_flow_before_debt for row in annual_rows]
    pv_cf, pv_term, npv_unlev = _discount_cash_flows(
        unlevered_cfs, terminal_net, v.discount_rate, v.use_mid_year_convention
    )

    # Going-in cap rate
    going_in_cap = None
    if v.initial_purchase_price and v.initial_purchase_price > ZERO and annual_rows:
        going_in_cap = annual_rows[0].noi / v.initial_purchase_price

    # Unlevered IRR
    irr_cfs = list(unlevered_cfs)
    if irr_cfs:
        irr_cfs[-1] += terminal_net
    if v.initial_purchase_price is not None:
        irr_cfs = [-v.initial_purchase_price] + irr_cfs
    irr_unlev = _irr(irr_cfs)

    # Levered
    exit_balance = debt_bal[-1] if debt_bal else ZERO
    levered_terminal = terminal_net - exit_balance
    levered_cfs = [row.levered_cash_flow for row in annual_rows]
    levered_dr = (
        v.levered_discount_rate
        if v.levered_discount_rate is not None
        else v.discount_rate
    )
    pv_lev_cf, _, npv_lev = _discount_cash_flows(
        levered_cfs, levered_terminal, levered_dr, v.use_mid_year_convention
    )

    levered_irr_cfs = list(levered_cfs)
    if levered_irr_cfs:
        levered_irr_cfs[-1] += levered_terminal
    if v.initial_purchase_price is not None:
        debt_amount = model.debt.loan_amount if model.debt and model.debt.loan_amount else ZERO
        equity_outlay = v.initial_purchase_price - debt_amount
        levered_irr_cfs = [-equity_outlay] + levered_irr_cfs
    irr_lev = _irr(levered_irr_cfs)

    return SeniorsHousingValuationResult(
        annual_cash_flows=annual_rows,
        terminal_noi=terminal_noi,
        terminal_value_gross=terminal_gross,
        terminal_value_net=terminal_net,
        pv_unlevered_cash_flows=pv_cf,
        pv_unlevered_terminal=pv_term,
        npv_unlevered=npv_unlev,
        irr_unlevered=irr_unlev,
        going_in_cap_rate=going_in_cap,
        pv_levered_cash_flows=pv_lev_cf,
        npv_levered=npv_lev,
        irr_levered=irr_lev,
        equity_value=npv_lev,
    )


# ---------------------------------------------------------------------------
# Scenario / sensitivity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeniorsHousingScenarioInput:
    name: str
    occupancy_multiplier: Decimal = ONE
    rate_multiplier: Decimal = ONE
    opex_multiplier: Decimal = ONE
    exit_cap_rate_shift_bps: int = 0


@dataclass
class SeniorsHousingScenarioResult:
    scenario_name: str
    result: SeniorsHousingValuationResult


@dataclass
class SeniorsHousingSensitivityPoint:
    discount_rate: Decimal
    exit_cap_rate: Decimal
    occupancy_multiplier: Decimal
    npv_unlevered: Decimal
    npv_levered: Decimal


def _apply_scenario(
    base: SeniorsHousingModelInput, scenario: SeniorsHousingScenarioInput
) -> SeniorsHousingModelInput:
    from dataclasses import replace

    rm = scenario.rate_multiplier
    new_units = tuple(
        replace(
            ut,
            monthly_base_fee=ut.monthly_base_fee * rm,
            second_person_fee_monthly=ut.second_person_fee_monthly * rm,
            community_fee=ut.community_fee * rm,
            care_level_tiers=tuple(
                CareLevelTier(
                    name=t.name,
                    monthly_surcharge=t.monthly_surcharge * rm,
                    pct_of_residents=t.pct_of_residents,
                )
                for t in ut.care_level_tiers
            ),
            stabilized_occupancy=_clamp(ut.stabilized_occupancy * scenario.occupancy_multiplier),
        )
        for ut in base.unit_types
    )
    new_snf = tuple(
        SNFPayerMixInput(
            payer=pm.payer,
            pct_of_days=pm.pct_of_days,
            daily_rate=pm.daily_rate * rm,
            annual_rate_growth=pm.annual_rate_growth,
        )
        for pm in base.snf_payer_mix
    )
    new_expenses = tuple(
        replace(
            e,
            annual_fixed=e.annual_fixed * scenario.opex_multiplier,
            per_occupied_unit_month=e.per_occupied_unit_month * scenario.opex_multiplier,
        )
        for e in base.expenses
    )
    new_exit = base.valuation.exit_cap_rate + _d(scenario.exit_cap_rate_shift_bps) / Decimal("10000")
    new_val = replace(base.valuation, exit_cap_rate=max(Decimal("0.0001"), new_exit))

    return replace(base, unit_types=new_units, snf_payer_mix=new_snf, expenses=new_expenses, valuation=new_val)


def run_seniors_housing_scenarios(
    base: SeniorsHousingModelInput,
    scenarios: tuple[SeniorsHousingScenarioInput, ...],
) -> list[SeniorsHousingScenarioResult]:
    return [
        SeniorsHousingScenarioResult(
            scenario_name=s.name,
            result=run_seniors_housing_valuation(_apply_scenario(base, s)),
        )
        for s in scenarios
    ]


def run_seniors_housing_sensitivity(
    base: SeniorsHousingModelInput,
    discount_rates: tuple[Decimal, ...],
    exit_cap_rates: tuple[Decimal, ...],
    occupancy_multipliers: tuple[Decimal, ...],
) -> list[SeniorsHousingSensitivityPoint]:
    from dataclasses import replace

    points: list[SeniorsHousingSensitivityPoint] = []
    for dr, cap, occ in product(discount_rates, exit_cap_rates, occupancy_multipliers):
        scenario = SeniorsHousingScenarioInput(name="sensitivity", occupancy_multiplier=occ)
        m = _apply_scenario(base, scenario)
        m = replace(m, valuation=replace(m.valuation, discount_rate=dr, exit_cap_rate=cap))
        result = run_seniors_housing_valuation(m)
        points.append(SeniorsHousingSensitivityPoint(
            discount_rate=dr, exit_cap_rate=cap, occupancy_multiplier=occ,
            npv_unlevered=result.npv_unlevered, npv_levered=result.npv_levered,
        ))
    return points
