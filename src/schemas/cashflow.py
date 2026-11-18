from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class SlipClassRevenueSummary(BaseModel):
    """Per-slip-class revenue breakdown for marina valuations."""
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


class AnnualCashFlowSummary(BaseModel):
    """One row per fiscal year in the analysis period."""
    year: int
    period_start: date
    period_end: date

    # Revenue
    gross_potential_rent: Decimal      # base rent at full contract rate
    free_rent: Decimal = Decimal(0)   # free rent concessions (negative)
    absorption_vacancy: Decimal       # turnover vacancy - rent lost during downtime (negative)
    loss_to_lease: Decimal = Decimal(0)  # contract vs market shortfall (negative)
    expense_recoveries: Decimal
    percentage_rent: Decimal
    other_income: Decimal
    gross_potential_income: Decimal

    # Vacancy & credit
    general_vacancy_loss: Decimal     # structural vacancy (negative)
    credit_loss: Decimal              # credit loss (negative)
    effective_gross_income: Decimal

    # Expenses
    operating_expenses: Decimal       # total OpEx (negative)
    expense_detail: dict[str, Decimal] = {}  # category → amount (negative)
    other_income_detail: dict[str, Decimal] = {}  # category → amount

    # NOI
    net_operating_income: Decimal

    # Capital items
    tenant_improvements: Decimal      # TI costs (negative)
    leasing_commissions: Decimal      # LC costs (negative)
    capital_reserves: Decimal         # capex reserves (negative)
    building_improvements: Decimal = Decimal(0)  # scheduled CapEx projects (negative)

    cash_flow_before_debt: Decimal

    # Optional levered
    debt_service: Decimal             # (negative if levered, else 0)
    balloon_payment: Decimal = Decimal(0)  # maturity balloon (negative if applicable)
    levered_cash_flow: Decimal

    # Marina-specific: per-slip-class revenue breakdown
    slip_class_detail: list[SlipClassRevenueSummary] = []
    # Self storage: occupancy, in-place vs street rate, move-ins/outs, by unit type
    storage_detail: dict | None = None


class TenantCashFlowDetail(BaseModel):
    """Per-tenant/suite annual cash flow detail."""
    suite_id: str
    suite_name: str
    tenant_name: str | None
    space_type: str
    area: Decimal
    lease_start: date | None
    lease_end: date | None
    scenario: str  # "in_place", "renewal", "new_tenant", "vacant", "blended"
    annual_base_rent: list[Decimal]      # one per analysis year
    annual_free_rent: list[Decimal] = []  # free rent concessions (negative)
    annual_recoveries: list[Decimal]
    annual_turnover_vacancy: list[Decimal] = []  # market rent lost during vacant months (negative)
    annual_loss_to_lease: list[Decimal] = []     # contract vs market shortfall (negative)
    annual_ti: list[Decimal] = []                # tenant improvements (negative)
    annual_lc: list[Decimal] = []                # leasing commissions (negative)
    annual_ti_lc: list[Decimal]          # combined TI+LC costs (negative)
    # Contract rent on the day the results are read (not stored with the run)
    current_rent_rate: Decimal | None = None     # $/SF/yr, $/unit/mo, or the whole amount for a total-basis lease
    current_rent_annual: Decimal | None = None   # $ per year
    current_rent_frequency: str | None = None    # "annual" or "monthly"
    current_rent_basis: str | None = None        # "per_area" or "total"


class TenantRecoveryAuditEntry(BaseModel):
    """Monthly per-expense recovery audit row for a tenant/suite lease slice."""
    year: int
    period_start: date
    period_end: date
    suite_id: str
    suite_name: str
    lease_id: str
    tenant_name: str | None
    expense_category: str
    recovery_type: str
    annual_expense_before_gross_up: Decimal
    annual_expense_after_gross_up: Decimal
    actual_occupancy_pct: Decimal
    gross_up_reference_occupancy_pct: Decimal | None
    gross_up_factor: Decimal
    pro_rata_share_pct: Decimal
    base_year_stop_amount: Decimal | None
    expense_stop_per_sf: Decimal | None
    cap_per_sf_annual: Decimal | None
    floor_per_sf_annual: Decimal | None
    admin_fee_pct: Decimal | None
    annual_recovery_before_proration: Decimal
    monthly_recovery_before_free_rent: Decimal
    proration_factor: Decimal
    is_recovery_free_rent_abatement: bool
    monthly_recovery_after_free_rent: Decimal
    scenario_weight: Decimal
    weighted_monthly_recovery: Decimal
    recovery_pool: str | None = None
    share_denominator_area: Decimal | None = None   # area the pro rata share is taken over
    pool_deduction: Decimal = Decimal(0)            # excluded tenants' recoveries taken off the pool
    modified_gross_pool_per_sf: Decimal | None = None  # MG: pooled $/SF the stop is tested against


class LeaseExpirationEntry(BaseModel):
    """Lease expirations by year."""
    year: int
    expiring_leases: int
    expiring_area: Decimal
    pct_of_total_gla: Decimal
    weighted_avg_rent_per_sf: Decimal


class RentRollEntry(BaseModel):
    """Snapshot of current rent roll."""
    suite_name: str
    space_type: str
    area: Decimal
    tenant_name: str | None
    lease_start: date | None
    lease_end: date | None
    lease_type: str
    base_rent_per_unit: Decimal | None
    annual_rent: Decimal | None        # base_rent * area (annualized)
    recovery_type: str | None
    escalation_type: str | None


class InvestmentReturnsSummary(BaseModel):
    """Returns measured against an actual purchase price."""
    purchase_price: Decimal
    acquisition_costs: Decimal
    total_investment: Decimal
    npv_at_price: Decimal
    going_in_cap_rate: Decimal
    unlevered_irr: Decimal | None = None
    unlevered_equity_multiple: Decimal | None = None
    loan_amount: Decimal
    loan_fees: Decimal
    equity_invested: Decimal
    loan_payoff_at_sale: Decimal
    levered_irr: Decimal | None = None
    levered_equity_multiple: Decimal | None = None
    year1_cash_on_cash: Decimal | None = None
    avg_cash_on_cash: Decimal | None = None
    year1_dscr: Decimal | None = None
    min_dscr: Decimal | None = None
    year1_debt_yield: Decimal | None = None
    loan_to_value: Decimal | None = None
    unlevered_cash_flows: list[Decimal] = []
    levered_cash_flows: list[Decimal] = []
    unlevered_irr_status: str = "not_calculated"
    unlevered_irr_roots: list[Decimal] = []
    unlevered_mirr: Decimal | None = None
    unlevered_xirr: Decimal | None = None
    unlevered_xirr_status: str = "not_calculated"
    unlevered_xirr_roots: list[Decimal] = []
    levered_irr_status: str = "not_calculated"
    levered_irr_roots: list[Decimal] = []
    levered_mirr: Decimal | None = None
    levered_xirr: Decimal | None = None
    levered_xirr_status: str = "not_calculated"
    levered_xirr_roots: list[Decimal] = []


class SensitivityMatrix(BaseModel):
    """Present value by discount rate (rows) and exit cap rate (columns)."""
    discount_rates: list[Decimal]
    exit_cap_rates: list[Decimal]
    values: list[list[Decimal]]
    irr_by_exit_cap: list[Decimal | None]


class WhatIfResult(BaseModel):
    """Value of the last completed run repriced at one discount rate / exit cap. Not saved."""
    discount_rate: Decimal
    exit_cap_rate: Decimal
    value: Decimal
    value_per_area: Decimal | None
    area_unit: str
    terminal_value: Decimal
    irr: Decimal | None  # unlevered, only when the valuation has a purchase price
    saved_discount_rate: Decimal
    saved_exit_cap_rate: Decimal
    saved_value: Decimal
    change_vs_saved: Decimal


class NcreifForecastPeriod(BaseModel):
    period: str
    period_end: date
    beginning_market_value: Decimal
    ending_market_value: Decimal
    noi: Decimal
    capital_improvements: Decimal
    partial_sales: Decimal
    denominator: Decimal
    income_return: Decimal
    capital_return: Decimal
    total_return: Decimal


class NcreifForecast(BaseModel):
    methodology: str
    frequency: str
    ownership_pct: Decimal
    beginning_market_value_basis: Decimal
    valuation_method: str
    cumulative_time_weighted_return: Decimal
    annualized_time_weighted_return: Decimal | None
    periods: list[NcreifForecastPeriod]
    warnings: list[str]


class KeyMetricsSummary(BaseModel):
    """Top-level investment metrics."""
    npv: Decimal
    irr: Decimal | None
    going_in_cap_rate: Decimal
    exit_cap_rate: Decimal
    terminal_value: Decimal
    pv_of_cash_flows: Decimal
    pv_of_terminal_value: Decimal
    equity_multiple: Decimal | None
    avg_occupancy_pct: Decimal
    weighted_avg_lease_term_years: Decimal | None

    # Reversion breakdown
    terminal_noi_basis: Decimal | None = None
    terminal_gross_value: Decimal | None = None
    terminal_exit_costs_amount: Decimal | None = None
    terminal_transfer_tax_amount: Decimal | None = None
    terminal_transfer_tax_preset: str | None = None
    terminal_capital_deduction_amount: Decimal | None = None

    direct_cap_value: Decimal | None = None
    returns: InvestmentReturnsSummary | None = None

    # Year 1 metrics
    year1_gpi: Decimal
    year1_egi: Decimal
    year1_noi: Decimal
    year1_cfbd: Decimal


class ValuationRunResponse(BaseModel):
    """Full response from a valuation run."""
    valuation_id: str
    status: str
    error_message: str | None = None
    key_metrics: KeyMetricsSummary | None = None
    annual_cash_flows: list[AnnualCashFlowSummary] = []
    tenant_cash_flows: list[TenantCashFlowDetail] = []
    recovery_audit: list[TenantRecoveryAuditEntry] = []
    lease_expiration_schedule: list[LeaseExpirationEntry] = []
    rent_roll: list[RentRollEntry] = []
