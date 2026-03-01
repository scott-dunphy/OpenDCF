"""
Engine-internal dataclasses. No SQLAlchemy, no Pydantic, no external deps.
All financial amounts are Decimal. All dates are datetime.date.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class FiscalYear:
    year_number: int          # 1-based
    start_date: date
    end_date: date


@dataclass(frozen=True)
class AnalysisPeriod:
    start_date: date
    end_date: date
    num_months: int
    fiscal_year_end_month: int
    fiscal_years: tuple[FiscalYear, ...]


@dataclass(frozen=True)
class RentStepInput:
    effective_date: date
    rent_per_unit: Decimal


@dataclass(frozen=True)
class FreeRentPeriodInput:
    start_date: date
    end_date: date
    applies_to_base_rent: bool
    applies_to_recoveries: bool


@dataclass(frozen=True)
class ExpenseRecoveryOverride:
    expense_category: str
    recovery_type: str
    base_year_stop_amount: Decimal | None
    cap_per_sf_annual: Decimal | None
    floor_per_sf_annual: Decimal | None
    admin_fee_pct: Decimal | None


@dataclass(frozen=True)
class LeaseInput:
    lease_id: str
    suite_id: str
    tenant_name: str | None
    area: Decimal
    start_date: date
    end_date: date
    base_rent_per_unit: Decimal    # $/SF/yr for commercial, $/unit/mo for residential
    rent_payment_frequency: str    # "monthly", "quarterly", "annual"
    escalation_type: str           # flat, pct_annual, cpi, fixed_step
    escalation_pct: Decimal | None
    cpi_floor: Decimal | None
    cpi_cap: Decimal | None
    rent_steps: tuple[RentStepInput, ...]
    free_rent_periods: tuple[FreeRentPeriodInput, ...]
    recovery_type: str
    pro_rata_share: Decimal | None   # if None, computed from area / total_area
    base_year_stop_amount: Decimal | None
    expense_stop_per_sf: Decimal | None
    recovery_overrides: tuple[ExpenseRecoveryOverride, ...]
    pct_rent_breakpoint: Decimal | None
    pct_rent_rate: Decimal | None
    base_year: int | None = None
    renewal_probability_override: Decimal | None = None
    renewal_rent_spread_override: Decimal | None = None
    projected_annual_sales_per_sf: Decimal | None = None


@dataclass(frozen=True)
class SuiteInput:
    suite_id: str
    suite_name: str
    area: Decimal
    space_type: str


@dataclass(frozen=True)
class OtherIncomeInput:
    income_id: str
    category: str
    base_amount: Decimal
    growth_rate: Decimal


@dataclass(frozen=True)
class CapitalProjectInput:
    project_id: str
    description: str
    total_amount: Decimal
    start_date: date
    duration_months: int


@dataclass(frozen=True)
class MarketAssumptions:
    space_type: str
    market_rent_per_unit: Decimal
    rent_growth_rate: Decimal

    new_lease_term_months: int
    new_ti_per_sf: Decimal
    new_lc_pct: Decimal
    new_free_rent_months: int
    downtime_months: int

    renewal_probability: Decimal
    renewal_term_months: int
    renewal_ti_per_sf: Decimal
    renewal_lc_pct: Decimal
    renewal_free_rent_months: int
    renewal_rent_adjustment_pct: Decimal  # vs market: -0.05 = 5% below market

    general_vacancy_pct: Decimal
    credit_loss_pct: Decimal
    rent_payment_frequency: str = "annual"  # "annual" ($/SF/yr) or "monthly" ($/unit/mo)


@dataclass(frozen=True)
class ExpenseInput:
    expense_id: str
    category: str
    base_amount: Decimal          # total $ for year 1
    growth_rate: Decimal          # annual, e.g. 0.03
    is_recoverable: bool
    is_gross_up_eligible: bool
    gross_up_vacancy_pct: Decimal | None
    is_pct_of_egi: bool
    pct_of_egi: Decimal | None


@dataclass(frozen=True)
class ValuationParams:
    discount_rate: Decimal
    exit_cap_rate: Decimal
    exit_cap_year: int             # -1 = forward year
    exit_costs_pct: Decimal
    capital_reserves_per_unit: Decimal
    total_property_area: Decimal
    use_mid_year_convention: bool
    loan_amount: Decimal | None
    interest_rate: Decimal | None
    amortization_months: int | None
    loan_term_months: int | None
    io_period_months: int
    transfer_tax_preset: str = "none"
    transfer_tax_custom_rate: Decimal | None = None


@dataclass(frozen=True)
class TerminalValueBreakdown:
    noi_basis: Decimal
    gross_value: Decimal
    exit_costs_amount: Decimal
    transfer_tax_amount: Decimal
    net_value: Decimal


# =========================================================================
# Output types
# =========================================================================

@dataclass
class MonthlySlice:
    """One month of cash flow for a single lease or vacant period on a suite."""
    month_index: int         # 0-based from analysis start
    period_start: date
    period_end: date
    suite_id: str
    lease_id: str
    tenant_name: str | None
    base_rent: Decimal       # full rent (before free rent adjustment)
    free_rent_adjustment: Decimal  # negative amount (abatement)
    effective_rent: Decimal  # base_rent + free_rent_adjustment
    expense_recovery: Decimal
    percentage_rent: Decimal
    ti_cost: Decimal         # negative when incurred
    lc_cost: Decimal         # negative when incurred
    is_vacant: bool
    scenario_label: str      # "in_place", "renewal", "new_tenant", "vacant"
    scenario_weight: Decimal  # probability weight (1.0 for in-place)


@dataclass
class SuiteAnnualCashFlow:
    """Per-suite, per-year summary used for tenant detail report."""
    suite_id: str
    suite_name: str
    space_type: str
    area: Decimal
    year: int
    tenant_name: str | None
    scenario: str
    base_rent: Decimal
    effective_rent: Decimal
    free_rent: Decimal         # free rent concessions (negative)
    expense_recovery: Decimal
    turnover_vacancy: Decimal  # market rent lost during vacant months (negative)
    loss_to_lease: Decimal    # contract vs market shortfall (negative)
    ti_cost: Decimal          # tenant improvements (negative)
    lc_cost: Decimal          # leasing commissions (negative)
    ti_lc_cost: Decimal      # combined TI + LC (negative)


@dataclass
class AnnualPropertyCashFlow:
    year: int
    period_start: date
    period_end: date

    gross_potential_rent: Decimal      # base rent at full contract rate
    free_rent: Decimal                 # free rent concessions (negative)
    absorption_vacancy: Decimal       # turnover vacancy (negative)
    loss_to_lease: Decimal             # contract vs market shortfall (negative)
    expense_recoveries: Decimal
    percentage_rent: Decimal
    other_income: Decimal
    gross_potential_income: Decimal

    general_vacancy_loss: Decimal
    credit_loss: Decimal
    effective_gross_income: Decimal

    operating_expenses: Decimal   # negative

    net_operating_income: Decimal

    tenant_improvements: Decimal  # negative
    leasing_commissions: Decimal  # negative
    capital_reserves: Decimal     # negative
    building_improvements: Decimal  # negative, scheduled CapEx projects

    cash_flow_before_debt: Decimal

    debt_service: Decimal         # negative or zero
    levered_cash_flow: Decimal

    expense_detail: dict[str, Decimal] = field(default_factory=dict)  # category → amount (negative)
    other_income_detail: dict[str, Decimal] = field(default_factory=dict)  # category → amount


@dataclass
class EngineResult:
    annual_cash_flows: list[AnnualPropertyCashFlow]
    suite_annual_details: list[SuiteAnnualCashFlow]
    npv: Decimal
    irr: Decimal | None
    terminal_value: Decimal
    pv_cash_flows: Decimal
    pv_terminal: Decimal
    going_in_cap_rate: Decimal
    avg_occupancy_pct: Decimal
    equity_multiple: Decimal | None
    terminal_noi_basis: Decimal = Decimal(0)
    terminal_gross_value: Decimal = Decimal(0)
    terminal_exit_costs_amount: Decimal = Decimal(0)
    terminal_transfer_tax_amount: Decimal = Decimal(0)
    terminal_transfer_tax_preset: str = "none"
