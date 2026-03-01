from datetime import date
from decimal import Decimal

from pydantic import BaseModel


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
    levered_cash_flow: Decimal


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
    lease_expiration_schedule: list[LeaseExpirationEntry] = []
    rent_roll: list[RentRollEntry] = []
