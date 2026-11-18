"""
Marina valuation module.

Model coverage:
- Slip inventory: wet slips, dry stack, moorings; length classes; utility tiers.
- Revenue: annual/seasonal/transient dockage, utility charges, fuel margin,
  repair/service, retail/F&B, storage, launch fees.
- Demand logic: monthly seasonality, weather shocks, waitlist conversion,
  churn and repricing.
- Costs: fixed/variable opex, cyclical events (e.g., dredging/storm work),
  reserve deductions, capex lifecycle.
- Legal/tenure: fee simple vs leasehold with permit/submerged-land costs and
  terminal reversion risk adjustments.
- Outputs: unlevered/levered DCF, IRR, terminal value, covenant views,
  scenario and sensitivity runs, and debt sizing.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from itertools import product
from typing import Literal

SlipKind = Literal["wet_slip", "dry_stack", "mooring"]
UtilityServiceLevel = Literal[
    "none", "water_only", "thirty_amp", "fifty_amp", "hundred_amp", "metered"
]
TenureType = Literal["fee_simple", "leasehold"]

ONE = Decimal(1)
ZERO = Decimal(0)


def _d(value: int | str | float | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _clamp(value: Decimal, low: Decimal = ZERO, high: Decimal = ONE) -> Decimal:
    return max(low, min(high, value))


def _grow(base: Decimal, growth_rate: Decimal, year_number: int) -> Decimal:
    return base * (ONE + growth_rate) ** Decimal(str(max(0, year_number - 1)))


def _validate_12(values: tuple[Decimal, ...], field_name: str) -> None:
    if len(values) != 12:
        raise ValueError(f"{field_name} must have exactly 12 monthly values.")


@dataclass(frozen=True)
class SlipClassInput:
    name: str
    kind: SlipKind
    length_class: str
    utility_service_level: UtilityServiceLevel
    count: int
    annual_contract_share: Decimal
    seasonal_contract_share: Decimal
    transient_share: Decimal
    annual_contract_rate: Decimal
    seasonal_contract_rate: Decimal
    transient_daily_rate: Decimal
    utility_fee_monthly: Decimal = Decimal(0)
    utility_fee_transient_daily: Decimal = Decimal(0)
    repair_service_revenue_per_occupied_day: Decimal = Decimal(0)
    retail_fnb_revenue_per_occupied_day: Decimal = Decimal(0)
    storage_fee_per_month: Decimal = Decimal(0)
    launch_fee_per_transient_arrival: Decimal = Decimal(0)
    avg_transient_stay_days: Decimal = Decimal("2.0")
    base_annual_occupancy: Decimal = Decimal("0.95")
    base_seasonal_occupancy: Decimal = Decimal("0.70")
    base_transient_capture: Decimal = Decimal("0.55")

    def __post_init__(self) -> None:
        shares = self.annual_contract_share + self.seasonal_contract_share + self.transient_share
        if shares > ONE:
            raise ValueError(f"SlipClassInput {self.name}: contract shares must sum to <= 1.0")
        if self.count < 0:
            raise ValueError("Slip count cannot be negative.")


@dataclass(frozen=True)
class DemandModelInput:
    monthly_seasonality: tuple[Decimal, ...]
    monthly_weather_shock_pct: tuple[Decimal, ...]
    seasonal_active_months: tuple[int, ...] = (4, 5, 6, 7, 8, 9, 10)
    annual_occupancy_growth_pct: Decimal = Decimal("0.00")
    seasonal_occupancy_growth_pct: Decimal = Decimal("0.00")
    waitlist_start_count: Decimal = Decimal("0")
    waitlist_conversion_pct: Decimal = Decimal("0.50")
    waitlist_new_demand_per_year: Decimal = Decimal("0")
    annual_rate_growth_pct: Decimal = Decimal("0.03")
    seasonal_rate_growth_pct: Decimal = Decimal("0.03")
    transient_rate_growth_pct: Decimal = Decimal("0.03")
    ancillary_growth_pct: Decimal = Decimal("0.03")
    transient_weather_sensitivity: Decimal = Decimal("1.00")
    vacancy_collection_loss_pct: Decimal = Decimal("0.00")
    management_fee_pct: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        _validate_12(self.monthly_seasonality, "monthly_seasonality")
        _validate_12(self.monthly_weather_shock_pct, "monthly_weather_shock_pct")


@dataclass(frozen=True)
class FuelDockInput:
    enabled: bool = True
    fuel_sales_per_occupied_day: Decimal = Decimal("25")
    fuel_margin_pct: Decimal = Decimal("0.22")
    annual_growth_pct: Decimal = Decimal("0.02")


@dataclass(frozen=True)
class AdditionalRevenueLineInput:
    name: str
    annual_fixed: Decimal
    per_occupied_day: Decimal = Decimal(0)
    growth_pct: Decimal = Decimal("0.03")


@dataclass(frozen=True)
class OperatingCostLineInput:
    name: str
    annual_fixed: Decimal
    per_occupied_day: Decimal = Decimal(0)
    growth_pct: Decimal = Decimal("0.03")


@dataclass(frozen=True)
class CyclicalCostInput:
    name: str
    base_amount: Decimal
    first_year: int
    every_n_years: int
    growth_pct: Decimal = Decimal("0.02")
    probability_pct: Decimal = Decimal("1.0")
    treat_as_capex: bool = False


@dataclass(frozen=True)
class LegalTenureInput:
    tenure_type: TenureType = "fee_simple"
    annual_ground_lease: Decimal = Decimal(0)
    ground_lease_growth_pct: Decimal = Decimal("0.02")
    annual_submerged_land_lease: Decimal = Decimal(0)
    submerged_land_lease_growth_pct: Decimal = Decimal("0.02")
    annual_permit_concession_fees: Decimal = Decimal(0)
    permit_growth_pct: Decimal = Decimal("0.02")
    remaining_lease_years: int | None = None
    lease_extension_probability: Decimal = Decimal("0.70")
    reversion_value_loss_pct: Decimal = Decimal("1.00")
    expiry_warning_horizon_years: int = 5


@dataclass(frozen=True)
class CapexLifecycleInput:
    name: str
    asset_type: str
    base_amount: Decimal
    first_year: int
    every_n_years: int
    growth_pct: Decimal = Decimal("0.02")
    deferred_maintenance_catchup_year: int | None = None
    deferred_maintenance_amount: Decimal = Decimal(0)


@dataclass(frozen=True)
class DebtInput:
    loan_amount: Decimal | None = None
    interest_rate: Decimal | None = None
    amortization_months: int | None = None
    term_months: int | None = None
    io_period_months: int = 0
    minimum_dscr: Decimal = Decimal("1.30")
    maximum_ltv: Decimal = Decimal("0.65")
    minimum_debt_yield: Decimal = Decimal("0.09")


@dataclass(frozen=True)
class ValuationInput:
    hold_years: int
    discount_rate: Decimal
    exit_cap_rate: Decimal
    exit_costs_pct: Decimal = Decimal("0.02")
    use_mid_year_convention: bool = False
    terminal_noi_growth_pct: Decimal = Decimal("0.02")
    dock_replacement_reserve_per_slip_year: Decimal = Decimal(0)
    reserve_growth_pct: Decimal = Decimal("0.02")
    initial_purchase_price: Decimal | None = None
    levered_discount_rate: Decimal | None = None


@dataclass(frozen=True)
class MarinaModelInput:
    as_of_date: date
    slip_classes: tuple[SlipClassInput, ...]
    demand: DemandModelInput
    operating_cost_lines: tuple[OperatingCostLineInput, ...]
    cyclical_costs: tuple[CyclicalCostInput, ...]
    legal_tenure: LegalTenureInput
    capex_lifecycle: tuple[CapexLifecycleInput, ...]
    valuation: ValuationInput
    additional_revenue_lines: tuple[AdditionalRevenueLineInput, ...] = ()
    fuel_dock: FuelDockInput = FuelDockInput()
    debt: DebtInput | None = None


@dataclass
class SlipClassAnnualRevenue:
    slip_class_name: str
    kind: str
    count: int
    annual_contract_revenue: Decimal
    seasonal_contract_revenue: Decimal
    transient_revenue: Decimal
    utility_revenue: Decimal
    repair_service_revenue: Decimal
    retail_fnb_revenue: Decimal
    storage_revenue: Decimal
    launch_fee_revenue: Decimal
    total_revenue: Decimal
    occupied_days: Decimal
    avg_occupancy_pct: Decimal


@dataclass
class MarinaAnnualCashFlow:
    year: int
    annual_contract_revenue: Decimal
    seasonal_contract_revenue: Decimal
    transient_revenue: Decimal
    utility_service_revenue: Decimal
    fuel_margin_revenue: Decimal
    repair_service_revenue: Decimal
    retail_fnb_revenue: Decimal
    storage_revenue: Decimal
    launch_fee_revenue: Decimal
    additional_revenue: Decimal
    potential_gross_revenue: Decimal
    vacancy_collection_loss: Decimal
    effective_gross_income: Decimal
    management_fee: Decimal
    operating_expenses: Decimal
    legal_tenure_costs: Decimal
    reserve_costs: Decimal
    cyclical_opex: Decimal
    noi: Decimal
    capex: Decimal
    cash_flow_before_debt: Decimal
    debt_service: Decimal
    balloon_payment: Decimal
    levered_cash_flow: Decimal
    avg_occupancy_pct: Decimal
    waitlist_end_count: Decimal
    slip_class_detail: list[SlipClassAnnualRevenue]


@dataclass
class CovenantViewYear:
    year: int
    debt_service: Decimal
    dscr: Decimal | None
    ending_loan_balance: Decimal
    ltv: Decimal | None
    debt_yield: Decimal | None


@dataclass
class MarinaValuationResult:
    annual_cash_flows: list[MarinaAnnualCashFlow]
    terminal_noi: Decimal
    terminal_value_gross: Decimal
    terminal_value_net: Decimal
    terminal_value_after_tenure_risk: Decimal
    pv_unlevered_cash_flows: Decimal
    pv_unlevered_terminal: Decimal
    npv_unlevered: Decimal
    irr_unlevered: Decimal | None
    pv_levered_cash_flows: Decimal
    npv_levered: Decimal
    irr_levered: Decimal | None
    enterprise_value: Decimal
    equity_value: Decimal
    covenants: list[CovenantViewYear]


@dataclass(frozen=True)
class MarinaScenarioInput:
    name: str
    occupancy_multiplier: Decimal = Decimal("1.00")
    rate_multiplier: Decimal = Decimal("1.00")
    opex_multiplier: Decimal = Decimal("1.00")
    weather_shock_additive_pct: Decimal = Decimal("0.00")
    exit_cap_rate_shift_bps: int = 0


@dataclass
class MarinaScenarioResult:
    scenario_name: str
    result: MarinaValuationResult


@dataclass
class MarinaSensitivityPoint:
    discount_rate: Decimal
    exit_cap_rate: Decimal
    occupancy_multiplier: Decimal
    npv_unlevered: Decimal
    npv_levered: Decimal


@dataclass
class DebtSizingResult:
    recommended_loan_amount: Decimal
    max_loan_by_dscr: Decimal
    max_loan_by_ltv: Decimal
    max_loan_by_debt_yield: Decimal
    binding_constraint: str


def _monthly_payment(principal: Decimal, monthly_rate: Decimal, n_months: int) -> Decimal:
    if n_months <= 0:
        return Decimal(0)
    if monthly_rate == Decimal(0):
        return principal / Decimal(str(n_months))
    r = monthly_rate
    n = Decimal(str(n_months))
    return principal * (r * (ONE + r) ** n) / ((ONE + r) ** n - ONE)


def _build_debt_service_and_balances(
    debt: DebtInput | None,
    hold_years: int,
) -> tuple[list[Decimal], list[Decimal], list[Decimal], list[Decimal]]:
    if debt is None or debt.loan_amount is None or debt.interest_rate is None:
        zeros = [Decimal(0)] * hold_years
        return zeros, zeros, zeros, zeros

    loan = debt.loan_amount
    monthly_rate = debt.interest_rate / Decimal(12)
    amort_months = debt.amortization_months or 360
    term_months = debt.term_months
    io_months = debt.io_period_months or 0
    fixed_payment = _monthly_payment(loan, monthly_rate, amort_months)

    balance = loan
    annual_service: list[Decimal] = []
    annual_balloon: list[Decimal] = []
    annual_end_balance: list[Decimal] = []
    annual_service_for_dscr: list[Decimal] = []

    for year in range(1, hold_years + 1):
        year_service = Decimal(0)
        year_balloon = Decimal(0)
        year_service_for_dscr = Decimal(0)
        for month_in_year in range(1, 13):
            month_num = (year - 1) * 12 + month_in_year
            if term_months is not None and month_num > term_months:
                continue

            is_maturity_month = term_months is not None and month_num == term_months
            interest = balance * monthly_rate
            if month_num <= io_months:
                if is_maturity_month:
                    year_service += interest
                    year_balloon += balance
                    year_service_for_dscr += interest
                    balance = Decimal(0)
                else:
                    year_service += interest
                    year_service_for_dscr += interest
            else:
                # Pay only what remains; nothing is due once the loan is repaid.
                principal = fixed_payment - interest
                principal = max(Decimal(0), principal)
                principal = min(principal, balance)
                if is_maturity_month:
                    year_service += interest + principal
                    year_balloon += balance - principal
                    year_service_for_dscr += interest + principal
                    balance = Decimal(0)
                else:
                    balance -= principal
                    year_service += interest + principal
                    year_service_for_dscr += interest + principal

        annual_service.append(year_service)
        annual_balloon.append(year_balloon)
        annual_end_balance.append(balance)
        annual_service_for_dscr.append(year_service_for_dscr)

    return annual_service, annual_balloon, annual_end_balance, annual_service_for_dscr


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

    for guess in [0.08, 0.12, 0.04, 0.18]:
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
    annual_cash_flows: list[Decimal],
    terminal_value: Decimal,
    discount_rate: Decimal,
    use_mid_year: bool,
) -> tuple[Decimal, Decimal, Decimal]:
    pv_cash = Decimal(0)
    for idx, cf in enumerate(annual_cash_flows):
        year = idx + 1
        t = Decimal(str(year)) - (Decimal("0.5") if use_mid_year else Decimal(0))
        pv_cash += cf / (ONE + discount_rate) ** t

    n = Decimal(str(len(annual_cash_flows))) - (Decimal("0.5") if use_mid_year else Decimal(0))
    pv_terminal = terminal_value / (ONE + discount_rate) ** n
    return pv_cash, pv_terminal, pv_cash + pv_terminal


def _tenure_terminal_factor(legal: LegalTenureInput, hold_years: int) -> Decimal:
    if legal.tenure_type == "fee_simple":
        return Decimal(1)
    if legal.remaining_lease_years is None:
        return Decimal(1)

    years_remaining_at_exit = legal.remaining_lease_years - hold_years
    if years_remaining_at_exit <= 0:
        extension_prob = _clamp(legal.lease_extension_probability)
    elif years_remaining_at_exit < legal.expiry_warning_horizon_years:
        proximity = Decimal(
            str(legal.expiry_warning_horizon_years - years_remaining_at_exit)
        ) / Decimal(str(legal.expiry_warning_horizon_years))
        extension_prob = ONE - proximity * (ONE - _clamp(legal.lease_extension_probability))
    else:
        extension_prob = ONE

    expected_factor = ONE - (ONE - extension_prob) * _clamp(legal.reversion_value_loss_pct)
    return _clamp(expected_factor, Decimal(0), Decimal("1.2"))


def _capex_for_year(capex_items: tuple[CapexLifecycleInput, ...], year: int) -> Decimal:
    total = Decimal(0)
    for item in capex_items:
        if item.every_n_years > 0 and year >= item.first_year and (year - item.first_year) % item.every_n_years == 0:
            total += _grow(item.base_amount, item.growth_pct, year)
        if item.deferred_maintenance_catchup_year == year:
            total += _grow(item.deferred_maintenance_amount, item.growth_pct, year)
    return total


def _cyclical_costs_for_year(
    cyclical_costs: tuple[CyclicalCostInput, ...], year: int
) -> tuple[Decimal, Decimal]:
    opex = Decimal(0)
    capex = Decimal(0)
    for cost in cyclical_costs:
        if cost.every_n_years > 0 and year >= cost.first_year and (year - cost.first_year) % cost.every_n_years == 0:
            amount = _grow(cost.base_amount, cost.growth_pct, year) * _clamp(cost.probability_pct)
            if cost.treat_as_capex:
                capex += amount
            else:
                opex += amount
    return opex, capex


def run_marina_valuation(model: MarinaModelInput) -> MarinaValuationResult:
    hold_years = model.valuation.hold_years
    service_months = len(model.demand.seasonal_active_months) or 1
    total_slips = sum(_d(s.count) for s in model.slip_classes)

    annual_units_by_class: dict[str, Decimal] = {}
    seasonal_occ_by_class: dict[str, Decimal] = {}
    waitlist = model.demand.waitlist_start_count

    for sc in model.slip_classes:
        annual_capacity = _d(sc.count) * sc.annual_contract_share
        annual_units_by_class[sc.name] = annual_capacity * _clamp(sc.base_annual_occupancy)
        seasonal_occ_by_class[sc.name] = sc.base_seasonal_occupancy

    (
        debt_service_by_year,
        balloon_by_year,
        debt_balance_by_year,
        debt_service_for_dscr_by_year,
    ) = _build_debt_service_and_balances(
        model.debt, hold_years
    )
    annual_rows: list[MarinaAnnualCashFlow] = []

    for year in range(1, hold_years + 1):
        annual_rev = Decimal(0)
        seasonal_rev = Decimal(0)
        transient_rev = Decimal(0)
        utility_rev = Decimal(0)
        repair_rev = Decimal(0)
        retail_rev = Decimal(0)
        storage_rev = Decimal(0)
        launch_rev = Decimal(0)
        occupied_day_total = Decimal(0)
        fuel_eligible_day_total = Decimal(0)  # excludes moorings (no fuel access)
        capacity_day_total = Decimal(0)

        if year > 1:
            # -- Annual contract occupancy trending --
            # Occupancy grows/declines by annual_occupancy_growth_pct per year.
            # Waitlist conversions add demand into available capacity.
            total_vacant = Decimal(0)
            for sc in model.slip_classes:
                annual_capacity = _d(sc.count) * sc.annual_contract_share
                prev_units = annual_units_by_class[sc.name]
                new_units = prev_units * (ONE + model.demand.annual_occupancy_growth_pct)
                new_units = _clamp(
                    new_units / (annual_capacity if annual_capacity > ZERO else ONE)
                ) * annual_capacity
                annual_units_by_class[sc.name] = new_units
                total_vacant += max(ZERO, annual_capacity - new_units)

            # Waitlist fills vacant annual slips
            if waitlist > ZERO and total_vacant > ZERO:
                converted = min(waitlist, total_vacant) * _clamp(
                    model.demand.waitlist_conversion_pct
                )
                for sc in model.slip_classes:
                    annual_capacity = _d(sc.count) * sc.annual_contract_share
                    vacant = max(ZERO, annual_capacity - annual_units_by_class[sc.name])
                    share = vacant / total_vacant if total_vacant > ZERO else ZERO
                    annual_units_by_class[sc.name] += converted * share
                    annual_units_by_class[sc.name] = min(
                        annual_units_by_class[sc.name], annual_capacity
                    )
                waitlist -= converted
            waitlist += model.demand.waitlist_new_demand_per_year

            # -- Seasonal contract occupancy trending --
            for sc in model.slip_classes:
                prev_occ = seasonal_occ_by_class[sc.name]
                new_occ = prev_occ * (ONE + model.demand.seasonal_occupancy_growth_pct)
                seasonal_occ_by_class[sc.name] = _clamp(new_occ)

        slip_class_rows: list[SlipClassAnnualRevenue] = []
        for sc in model.slip_classes:
            annual_capacity = _d(sc.count) * sc.annual_contract_share
            seasonal_capacity = _d(sc.count) * sc.seasonal_contract_share
            transient_capacity = _d(sc.count) * sc.transient_share

            annual_rate = _grow(
                sc.annual_contract_rate,
                model.demand.annual_rate_growth_pct,
                year,
            )
            seasonal_rate = _grow(
                sc.seasonal_contract_rate,
                model.demand.seasonal_rate_growth_pct,
                year,
            )
            transient_rate = _grow(
                sc.transient_daily_rate,
                model.demand.transient_rate_growth_pct,
                year,
            )

            # Grow ancillary rates
            ancillary_g = model.demand.ancillary_growth_pct
            grown_utility_monthly = _grow(sc.utility_fee_monthly, ancillary_g, year)
            grown_utility_transient = _grow(sc.utility_fee_transient_daily, ancillary_g, year)
            grown_repair = _grow(sc.repair_service_revenue_per_occupied_day, ancillary_g, year)
            grown_retail = _grow(sc.retail_fnb_revenue_per_occupied_day, ancillary_g, year)
            grown_storage = _grow(sc.storage_fee_per_month, ancillary_g, year)
            grown_launch = _grow(sc.launch_fee_per_transient_arrival, ancillary_g, year)

            annual_units = annual_units_by_class[sc.name]
            eff_seasonal_occ = seasonal_occ_by_class[sc.name]

            # Per-slip-class accumulators
            sc_annual_rev = Decimal(0)
            sc_seasonal_rev = Decimal(0)
            sc_transient_rev = Decimal(0)
            sc_utility_rev = Decimal(0)
            sc_repair_rev = Decimal(0)
            sc_retail_rev = Decimal(0)
            sc_storage_rev = Decimal(0)
            sc_launch_rev = Decimal(0)
            sc_occupied_days = Decimal(0)
            sc_capacity_days = Decimal(0)

            for month in range(1, 13):
                days = _d(calendar.monthrange(model.as_of_date.year + year - 1, month)[1])
                seasonality = model.demand.monthly_seasonality[month - 1]
                weather_shock = model.demand.monthly_weather_shock_pct[month - 1]
                weather_factor = _clamp(
                    ONE - weather_shock * model.demand.transient_weather_sensitivity,
                    Decimal(0),
                    ONE,
                )

                seasonal_units = Decimal(0)
                seasonal_contracted_units = Decimal(0)
                if month in model.demand.seasonal_active_months:
                    # Contracted units: fixed obligation, not weather/seasonality modulated
                    seasonal_contracted_units = seasonal_capacity * _clamp(eff_seasonal_occ)
                    # Effective units: modulated for ancillary revenue & transient supply calc
                    seasonal_target = seasonal_capacity * _clamp(
                        eff_seasonal_occ * seasonality
                    )
                    seasonal_units = seasonal_target * weather_factor

                transient_supply = transient_capacity
                transient_supply += max(Decimal(0), seasonal_capacity - seasonal_units)
                transient_supply += max(Decimal(0), annual_capacity - annual_units)
                transient_capture = _clamp(sc.base_transient_capture * seasonality * weather_factor)
                transient_units = transient_supply * transient_capture

                annual_occupied_days = annual_units * days
                seasonal_occupied_days = seasonal_units * days
                transient_occupied_days = transient_units * days
                occupied_days = (
                    annual_occupied_days + seasonal_occupied_days + transient_occupied_days
                )
                # Occupied slips this month (for storage revenue)
                occupied_slips = annual_units + seasonal_units + transient_units

                occupied_day_total += occupied_days
                sc_occupied_days += occupied_days
                if sc.kind != "mooring":
                    fuel_eligible_day_total += occupied_days
                capacity_day_total += _d(sc.count) * days
                sc_capacity_days += _d(sc.count) * days

                m_annual = annual_units * annual_rate / Decimal(12)
                annual_rev += m_annual
                sc_annual_rev += m_annual
                if month in model.demand.seasonal_active_months:
                    m_seasonal = seasonal_contracted_units * seasonal_rate / _d(service_months)
                    seasonal_rev += m_seasonal
                    sc_seasonal_rev += m_seasonal
                m_transient = transient_occupied_days * transient_rate
                transient_rev += m_transient
                sc_transient_rev += m_transient

                m_util = annual_units * grown_utility_monthly
                if month in model.demand.seasonal_active_months:
                    m_util += seasonal_units * grown_utility_monthly
                m_util += transient_occupied_days * grown_utility_transient
                utility_rev += m_util
                sc_utility_rev += m_util

                m_repair = occupied_days * grown_repair
                repair_rev += m_repair
                sc_repair_rev += m_repair
                m_retail = occupied_days * grown_retail
                retail_rev += m_retail
                sc_retail_rev += m_retail
                # Storage revenue on occupied slips only
                m_storage = occupied_slips * grown_storage
                storage_rev += m_storage
                sc_storage_rev += m_storage

                arrivals = transient_occupied_days / max(sc.avg_transient_stay_days, Decimal("1"))
                m_launch = arrivals * grown_launch
                launch_rev += m_launch
                sc_launch_rev += m_launch

            sc_total = (
                sc_annual_rev + sc_seasonal_rev + sc_transient_rev
                + sc_utility_rev + sc_repair_rev + sc_retail_rev
                + sc_storage_rev + sc_launch_rev
            )
            sc_occ_pct = (
                sc_occupied_days / sc_capacity_days
                if sc_capacity_days > Decimal(0)
                else Decimal(0)
            )
            slip_class_rows.append(SlipClassAnnualRevenue(
                slip_class_name=sc.name,
                kind=sc.kind,
                count=sc.count,
                annual_contract_revenue=sc_annual_rev,
                seasonal_contract_revenue=sc_seasonal_rev,
                transient_revenue=sc_transient_rev,
                utility_revenue=sc_utility_rev,
                repair_service_revenue=sc_repair_rev,
                retail_fnb_revenue=sc_retail_rev,
                storage_revenue=sc_storage_rev,
                launch_fee_revenue=sc_launch_rev,
                total_revenue=sc_total,
                occupied_days=sc_occupied_days,
                avg_occupancy_pct=sc_occ_pct,
            ))

        fuel_margin = Decimal(0)
        if model.fuel_dock.enabled:
            fuel_sales = fuel_eligible_day_total * _grow(
                model.fuel_dock.fuel_sales_per_occupied_day,
                model.fuel_dock.annual_growth_pct,
                year,
            )
            fuel_margin = fuel_sales * model.fuel_dock.fuel_margin_pct

        additional_rev = Decimal(0)
        for line in model.additional_revenue_lines:
            grown_fixed = _grow(line.annual_fixed, line.growth_pct, year)
            grown_var = _grow(line.per_occupied_day, line.growth_pct, year) * occupied_day_total
            additional_rev += grown_fixed + grown_var

        potential_gross_revenue = (
            annual_rev
            + seasonal_rev
            + transient_rev
            + utility_rev
            + fuel_margin
            + repair_rev
            + retail_rev
            + storage_rev
            + launch_rev
            + additional_rev
        )

        # Collection loss (physical vacancy is already modeled via occupancy;
        # this covers credit/collection losses on occupied slips)
        vacancy_loss = potential_gross_revenue * _clamp(
            model.demand.vacancy_collection_loss_pct
        )
        egi = potential_gross_revenue - vacancy_loss

        # Management fee (% of EGI)
        mgmt_fee = egi * _clamp(model.demand.management_fee_pct)

        operating_expenses = Decimal(0)
        for line in model.operating_cost_lines:
            grown_fixed = _grow(line.annual_fixed, line.growth_pct, year)
            grown_var = _grow(line.per_occupied_day, line.growth_pct, year) * occupied_day_total
            operating_expenses += grown_fixed + grown_var

        legal_costs = (
            _grow(
                model.legal_tenure.annual_ground_lease,
                model.legal_tenure.ground_lease_growth_pct,
                year,
            )
            + _grow(
                model.legal_tenure.annual_submerged_land_lease,
                model.legal_tenure.submerged_land_lease_growth_pct,
                year,
            )
            + _grow(
                model.legal_tenure.annual_permit_concession_fees,
                model.legal_tenure.permit_growth_pct,
                year,
            )
        )

        reserve_costs = (
            _grow(
                model.valuation.dock_replacement_reserve_per_slip_year,
                model.valuation.reserve_growth_pct,
                year,
            )
            * total_slips
        )

        cyclical_opex, cyclical_capex = _cyclical_costs_for_year(model.cyclical_costs, year)
        lifecycle_capex = _capex_for_year(model.capex_lifecycle, year)
        capex = cyclical_capex + lifecycle_capex

        noi = egi - mgmt_fee - operating_expenses - legal_costs - cyclical_opex
        cfbd = noi - reserve_costs - capex
        debt_service = debt_service_by_year[year - 1]
        balloon = balloon_by_year[year - 1]
        levered_cf = cfbd - debt_service - balloon

        occupancy = (
            occupied_day_total / capacity_day_total
            if capacity_day_total > Decimal(0)
            else Decimal(0)
        )

        annual_rows.append(
            MarinaAnnualCashFlow(
                year=year,
                annual_contract_revenue=annual_rev,
                seasonal_contract_revenue=seasonal_rev,
                transient_revenue=transient_rev,
                utility_service_revenue=utility_rev,
                fuel_margin_revenue=fuel_margin,
                repair_service_revenue=repair_rev,
                retail_fnb_revenue=retail_rev,
                storage_revenue=storage_rev,
                launch_fee_revenue=launch_rev,
                additional_revenue=additional_rev,
                potential_gross_revenue=potential_gross_revenue,
                vacancy_collection_loss=vacancy_loss,
                effective_gross_income=egi,
                management_fee=mgmt_fee,
                operating_expenses=operating_expenses,
                legal_tenure_costs=legal_costs,
                reserve_costs=reserve_costs,
                cyclical_opex=cyclical_opex,
                noi=noi,
                capex=capex,
                cash_flow_before_debt=cfbd,
                debt_service=debt_service,
                balloon_payment=balloon,
                levered_cash_flow=levered_cf,
                avg_occupancy_pct=occupancy,
                waitlist_end_count=waitlist,
                slip_class_detail=slip_class_rows,
            )
        )
    last_noi = annual_rows[-1].noi if annual_rows else Decimal(0)
    terminal_noi = last_noi * (ONE + model.valuation.terminal_noi_growth_pct)
    if model.valuation.exit_cap_rate > Decimal(0):
        terminal_gross = terminal_noi / model.valuation.exit_cap_rate
    else:
        terminal_gross = Decimal(0)
    terminal_net = terminal_gross * (ONE - model.valuation.exit_costs_pct)
    terminal_tenure_factor = _tenure_terminal_factor(model.legal_tenure, model.valuation.hold_years)
    terminal_after_tenure = terminal_net * terminal_tenure_factor

    unlevered_cfs = [row.cash_flow_before_debt for row in annual_rows]
    levered_cfs = [row.levered_cash_flow for row in annual_rows]
    pv_unlev_cf, pv_unlev_term, npv_unlev = _discount_cash_flows(
        unlevered_cfs,
        terminal_after_tenure,
        model.valuation.discount_rate,
        model.valuation.use_mid_year_convention,
    )
    exit_loan_balance = debt_balance_by_year[-1] if debt_balance_by_year else Decimal(0)
    levered_terminal = terminal_after_tenure - exit_loan_balance

    levered_dr = (
        model.valuation.levered_discount_rate
        if model.valuation.levered_discount_rate is not None
        else model.valuation.discount_rate
    )
    pv_lev_cf, _, npv_lev = _discount_cash_flows(
        levered_cfs,
        levered_terminal,
        levered_dr,
        model.valuation.use_mid_year_convention,
    )

    unlevered_irr_cfs = list(unlevered_cfs)
    if unlevered_irr_cfs:
        unlevered_irr_cfs[-1] += terminal_after_tenure
    if model.valuation.initial_purchase_price is not None:
        unlevered_irr_cfs = [-model.valuation.initial_purchase_price] + unlevered_irr_cfs
    irr_unlev = _irr(unlevered_irr_cfs)

    levered_irr_cfs = list(levered_cfs)
    if levered_irr_cfs:
        levered_irr_cfs[-1] += levered_terminal
    if model.valuation.initial_purchase_price is not None:
        debt_amount = (
            model.debt.loan_amount if model.debt and model.debt.loan_amount else Decimal(0)
        )
        equity_outlay = model.valuation.initial_purchase_price - debt_amount
        levered_irr_cfs = [-equity_outlay] + levered_irr_cfs
    irr_lev = _irr(levered_irr_cfs)

    covenants: list[CovenantViewYear] = []
    for row in annual_rows:
        idx = row.year - 1
        balance = debt_balance_by_year[idx]
        covenant_debt_service = debt_service_for_dscr_by_year[idx]
        dscr = (row.noi / covenant_debt_service) if covenant_debt_service > Decimal(0) else None
        estimated_value = (
            row.noi / model.valuation.exit_cap_rate
            if model.valuation.exit_cap_rate > Decimal(0)
            else Decimal(0)
        )
        ltv = (
            (balance / estimated_value)
            if estimated_value > Decimal(0) and balance > Decimal(0)
            else None
        )
        debt_yield = (row.noi / balance) if balance > Decimal(0) else None
        covenants.append(
            CovenantViewYear(
                year=row.year,
                debt_service=covenant_debt_service,
                dscr=dscr,
                ending_loan_balance=balance,
                ltv=ltv,
                debt_yield=debt_yield,
            )
        )

    return MarinaValuationResult(
        annual_cash_flows=annual_rows,
        terminal_noi=terminal_noi,
        terminal_value_gross=terminal_gross,
        terminal_value_net=terminal_net,
        terminal_value_after_tenure_risk=terminal_after_tenure,
        pv_unlevered_cash_flows=pv_unlev_cf,
        pv_unlevered_terminal=pv_unlev_term,
        npv_unlevered=npv_unlev,
        irr_unlevered=irr_unlev,
        pv_levered_cash_flows=pv_lev_cf,
        npv_levered=npv_lev,
        irr_levered=irr_lev,
        enterprise_value=npv_unlev,
        equity_value=npv_lev,
        covenants=covenants,
    )


def _apply_scenario(base: MarinaModelInput, scenario: MarinaScenarioInput) -> MarinaModelInput:
    shifted_weather = tuple(
        _clamp(m + scenario.weather_shock_additive_pct, Decimal(0), Decimal("0.95"))
        for m in base.demand.monthly_weather_shock_pct
    )
    new_demand = replace(base.demand, monthly_weather_shock_pct=shifted_weather)

    new_slips = tuple(
        replace(
            sc,
            annual_contract_rate=sc.annual_contract_rate * scenario.rate_multiplier,
            seasonal_contract_rate=sc.seasonal_contract_rate * scenario.rate_multiplier,
            transient_daily_rate=sc.transient_daily_rate * scenario.rate_multiplier,
            base_annual_occupancy=_clamp(sc.base_annual_occupancy * scenario.occupancy_multiplier),
            base_seasonal_occupancy=_clamp(
                sc.base_seasonal_occupancy * scenario.occupancy_multiplier
            ),
            base_transient_capture=_clamp(
                sc.base_transient_capture * scenario.occupancy_multiplier
            ),
        )
        for sc in base.slip_classes
    )

    new_opex = tuple(
        replace(
            line,
            annual_fixed=line.annual_fixed * scenario.opex_multiplier,
            per_occupied_day=line.per_occupied_day * scenario.opex_multiplier,
        )
        for line in base.operating_cost_lines
    )

    new_exit_cap_rate = base.valuation.exit_cap_rate + _d(
        scenario.exit_cap_rate_shift_bps
    ) / Decimal("10000")
    new_valuation = replace(base.valuation, exit_cap_rate=max(Decimal("0.0001"), new_exit_cap_rate))

    return replace(
        base,
        demand=new_demand,
        slip_classes=new_slips,
        operating_cost_lines=new_opex,
        valuation=new_valuation,
    )


def run_marina_scenarios(
    base: MarinaModelInput,
    scenarios: tuple[MarinaScenarioInput, ...],
) -> list[MarinaScenarioResult]:
    out: list[MarinaScenarioResult] = []
    for scenario in scenarios:
        scenario_model = _apply_scenario(base, scenario)
        out.append(
            MarinaScenarioResult(
                scenario_name=scenario.name,
                result=run_marina_valuation(scenario_model),
            )
        )
    return out


def run_marina_sensitivity(
    base: MarinaModelInput,
    discount_rates: tuple[Decimal, ...],
    exit_cap_rates: tuple[Decimal, ...],
    occupancy_multipliers: tuple[Decimal, ...],
) -> list[MarinaSensitivityPoint]:
    points: list[MarinaSensitivityPoint] = []
    for dr, cap, occ in product(discount_rates, exit_cap_rates, occupancy_multipliers):
        scenario = MarinaScenarioInput(
            name="sensitivity",
            occupancy_multiplier=occ,
            rate_multiplier=Decimal("1.0"),
            opex_multiplier=Decimal("1.0"),
        )
        scenario_model = _apply_scenario(base, scenario)
        scenario_model = replace(
            scenario_model,
            valuation=replace(
                scenario_model.valuation,
                discount_rate=dr,
                exit_cap_rate=cap,
            ),
        )
        result = run_marina_valuation(scenario_model)
        points.append(
            MarinaSensitivityPoint(
                discount_rate=dr,
                exit_cap_rate=cap,
                occupancy_multiplier=occ,
                npv_unlevered=result.npv_unlevered,
                npv_levered=result.npv_levered,
            )
        )
    return points


def size_debt_for_covenants(base: MarinaModelInput) -> DebtSizingResult:
    if base.debt is None or base.debt.interest_rate is None:
        raise ValueError(
            "Debt assumptions with at least interest_rate are required for debt sizing."
        )

    unlevered_model = replace(base, debt=None)
    unlevered_result = run_marina_valuation(unlevered_model)
    enterprise_value = max(unlevered_result.enterprise_value, Decimal(0))
    min_noi = min((row.noi for row in unlevered_result.annual_cash_flows), default=Decimal(0))

    max_by_ltv = enterprise_value * _clamp(base.debt.maximum_ltv)
    max_by_debt_yield = (
        min_noi / base.debt.minimum_debt_yield
        if base.debt.minimum_debt_yield > Decimal(0)
        else max_by_ltv
    )
    search_hi = max(max_by_ltv, max_by_debt_yield, Decimal("1"))

    def _min_dscr_for_loan(loan_amount: Decimal) -> Decimal:
        debt = replace(base.debt, loan_amount=loan_amount)
        result = run_marina_valuation(replace(base, debt=debt))
        dscr_values = [
            c.dscr for c in result.covenants if c.dscr is not None and c.debt_service > Decimal(0)
        ]
        return min(dscr_values) if dscr_values else Decimal("99")

    lo = Decimal(0)
    hi = search_hi
    for _ in range(50):
        mid = (lo + hi) / Decimal(2)
        min_dscr = _min_dscr_for_loan(mid)
        if min_dscr >= base.debt.minimum_dscr:
            lo = mid
        else:
            hi = mid
    max_by_dscr = lo

    recommended = min(max_by_dscr, max_by_ltv, max_by_debt_yield)
    if recommended == max_by_dscr:
        binding = "dscr"
    elif recommended == max_by_ltv:
        binding = "ltv"
    else:
        binding = "debt_yield"

    return DebtSizingResult(
        recommended_loan_amount=recommended,
        max_loan_by_dscr=max_by_dscr,
        max_loan_by_ltv=max_by_ltv,
        max_loan_by_debt_yield=max_by_debt_yield,
        binding_constraint=binding,
    )
