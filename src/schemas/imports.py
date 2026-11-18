from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from src.schemas.common import MonthStart
from src.schemas.portfolio import AssumptionValues, RangeBounds


class ImportedRentStep(BaseModel):
    effective_date: date
    rent_per_unit: Decimal


class ImportedLease(BaseModel):
    external_id: str | None = None
    suite_name: str
    tenant_name: str | None = None
    lease_start_date: date
    lease_end_date: date
    base_rent_per_unit: Decimal
    rent_payment_frequency: Literal["annual", "monthly"] = "annual"
    escalation_type: str = "flat"
    escalation_pct_annual: Decimal | None = None
    cpi_floor: Decimal | None = None
    cpi_cap: Decimal | None = None
    recovery_type: str = "nnn"
    base_year: int | None = None
    expense_stop_per_sf: Decimal | None = None
    pro_rata_share_pct: Decimal | None = None
    free_rent_months: int = 0
    rent_steps: list[ImportedRentStep] = []
    pct_rent_breakpoint: Decimal | None = None
    pct_rent_rate: Decimal | None = None
    projected_annual_sales_per_sf: Decimal | None = None
    renewal_probability: Decimal | None = None
    lease_type: str = "in_place"
    upon_expiration: str | None = None
    market_profile_key: str | None = None


class ImportedSuite(BaseModel):
    suite_name: str
    area: Decimal
    space_type: str
    floor: int | None = None


class ImportedMarketProfile(BaseModel):
    key: str                      # external id / name used by leases
    space_type: str
    market_rent_per_unit: Decimal
    rent_growth_rate_pct: Decimal = Decimal("0.03")
    rent_growth_schedule: list[Decimal] = []
    new_lease_term_months: int = 60
    new_tenant_ti_per_sf: Decimal = Decimal(0)
    new_tenant_lc_pct: Decimal = Decimal("0.06")
    new_tenant_free_rent_months: int = 0
    downtime_months: int = 3
    renewal_probability: Decimal = Decimal("0.65")
    renewal_lease_term_months: int = 60
    renewal_ti_per_sf: Decimal = Decimal(0)
    renewal_lc_pct: Decimal = Decimal("0.03")
    renewal_free_rent_months: int = 0
    renewal_rent_adjustment_pct: Decimal = Decimal(0)
    general_vacancy_pct: Decimal = Decimal("0.05")
    credit_loss_pct: Decimal = Decimal("0.01")
    # Year-by-year values from yearly series (empty = the single value every year)
    general_vacancy_schedule: list[Decimal] = []
    credit_loss_schedule: list[Decimal] = []
    renewal_probability_schedule: list[Decimal] = []
    downtime_schedule: list[int] = []
    new_free_rent_schedule: list[Decimal] = []
    renewal_free_rent_schedule: list[Decimal] = []


class ImportedExpense(BaseModel):
    category: str
    description: str | None = None
    base_year_amount: Decimal
    growth_rate_pct: Decimal = Decimal("0.03")
    growth_schedule: list[Decimal] = []
    is_recoverable: bool = True
    is_gross_up_eligible: bool = False
    gross_up_vacancy_pct: Decimal | None = None
    is_pct_of_egi: bool = False
    pct_of_egi: Decimal | None = None


class ImportedOtherIncome(BaseModel):
    category: str
    description: str | None = None
    base_year_amount: Decimal
    growth_rate_pct: Decimal = Decimal("0.03")
    growth_schedule: list[Decimal] = []


class ImportedCapitalProject(BaseModel):
    description: str
    total_amount: Decimal
    start_date: date
    duration_months: int = 1


class ImportedValuation(BaseModel):
    discount_rate: Decimal | None = None
    exit_cap_rate: Decimal | None = None
    exit_costs_pct: Decimal | None = None
    purchase_price: Decimal | None = None
    loan_amount: Decimal | None = None
    interest_rate: Decimal | None = None
    amortization_months: int | None = None
    loan_term_months: int | None = None
    io_period_months: int | None = None
    loan_fees_pct: Decimal | None = None
    additional_loans: list[dict] = Field(default_factory=list)  # loans after the first (AdditionalLoan fields)


class ImportedProperty(BaseModel):
    external_id: str
    name: str
    property_type: str
    address_line1: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    market: str | None = None
    total_area: Decimal | None = None
    area_unit: str = "sf"
    year_built: int | None = None
    analysis_start_date: date
    analysis_period_months: int = 120
    fiscal_year_end_month: int = 12
    portfolio_name: str | None = None
    suites: list[ImportedSuite] = []
    leases: list[ImportedLease] = []
    market_profiles: list[ImportedMarketProfile] = []
    expenses: list[ImportedExpense] = []
    other_income: list[ImportedOtherIncome] = []
    capital_projects: list[ImportedCapitalProject] = []
    valuation: ImportedValuation | None = None
    # Self storage unit mix with sizes (src.schemas.self_storage); replaces suites and leases
    self_storage_assumptions_json: str | None = None
    warnings: list[str] = []


class ImportedAssumptionProfile(BaseModel):
    name: str
    portfolio_name: str | None = None
    property_type: str | None = None
    market: str | None = None
    values: AssumptionValues
    ranges: dict[str, RangeBounds] = {}
    cbsa_code: str | None = None
    state: str | None = None
    quality_score: int | None = None
    as_of: date | None = None
    source: str | None = None
    comment: str | None = None


class ImportedLoan(BaseModel):
    """One row of a lender's loan tape."""
    external_id: str
    property_ref: str | None = None        # property external id (in the workbook or already in Ares)
    # Collateral description, used to create a tape-only property when no property matches
    property_name: str | None = None
    property_type: str | None = None
    market: str | None = None
    address_line1: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    total_area: Decimal | None = None
    area_unit: str = "sf"

    name: str | None = None
    portfolio_name: str | None = None
    lien_position: int = 1
    sponsor: str | None = None
    recourse: bool = False
    origination_date: date
    original_balance: Decimal
    maturity_date: date
    rate_type: str = "fixed"
    coupon: Decimal | None = None
    index_name: str | None = None
    spread: Decimal | None = None
    index_floor: Decimal | None = None
    index_cap: Decimal | None = None
    amortization_months: int | None = None
    io_months: int = 0
    extension_count: int = 0
    extension_months: int = 0
    reported_balance: Decimal | None = None
    balance_as_of_date: date | None = None
    delinquency_status: str = "current"
    origination_value: Decimal | None = None
    origination_noi: Decimal | None = None
    tape_noi: Decimal | None = None
    tape_value: Decimal | None = None
    tape_value_date: date | None = None
    tape_occupancy: Decimal | None = None
    tape_noi_growth: Decimal | None = None
    tape_exit_cap_rate: Decimal | None = None
    warnings: list[str] = []


class ImportPayload(BaseModel):
    properties: list[ImportedProperty] = []
    assumption_profiles: list[ImportedAssumptionProfile] = []
    loans: list[ImportedLoan] = []


class SheetReport(BaseModel):
    sheet: str
    view: str | None = None
    format: Literal["xl4adw", "plain"]
    recognized_as: str | None = None
    rows: int
    mapped_columns: dict[str, str] = {}      # header -> Ares field
    unmapped_columns: list[str] = []


class PropertyPreview(BaseModel):
    external_id: str
    name: str
    property_type: str
    market: str | None = None
    total_area: Decimal | None = None
    suites: int
    leases: int
    market_profiles: int
    expenses: int
    other_income: int
    capital_projects: int
    has_valuation: bool
    warnings: list[str] = []


class LoanPreview(BaseModel):
    external_id: str
    property_ref: str | None = None
    property_name: str | None = None
    property_link: Literal["workbook", "existing", "new"]   # where the collateral comes from
    lien_position: int
    original_balance: Decimal
    reported_balance: Decimal | None = None
    origination_date: date
    maturity_date: date
    rate_type: str
    rate: Decimal | None = None          # coupon (fixed) or spread (floating)
    delinquency_status: str
    has_tape_collateral: bool
    warnings: list[str] = []


class ImportOptions(BaseModel):
    default_property_type: str = "office"
    analysis_start_date: MonthStart | None = None
    analysis_period_months: int = Field(default=120, ge=12, le=360, multiple_of=12)
    # Optional manual mapping: {sheet name: {column header: Ares field}}
    column_mapping: dict[str, dict[str, str]] = {}


class ImportJobRead(BaseModel):
    id: str
    filename: str
    status: str
    created_at: datetime
    sheets: list[SheetReport] = []
    properties: list[PropertyPreview] = []
    loans: list[LoanPreview] = []
    assumption_profiles: int = 0
    warnings: list[str] = []
    errors: list[str] = []
    created_property_ids: list[str] = []
    created_loan_count: int = 0
    portfolio_id: str | None = None


class ImportCommitRequest(BaseModel):
    portfolio_id: str | None = Field(default=None, description="Add imported properties to this portfolio")
    portfolio_name: str | None = Field(
        default=None, description="Create a portfolio with this name (or reuse one with the same name)"
    )
    replace_existing: bool = Field(
        default=False,
        description="Replace properties previously imported with the same external id",
    )
    create_valuations: bool = True  # ignored: every imported property gets a valuation holding its model
