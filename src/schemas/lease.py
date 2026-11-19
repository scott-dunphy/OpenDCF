from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.common import EscalationType, LeaseType, RecoveryType, UponExpiration


class RentStepCreate(BaseModel):
    effective_date: date
    rent_per_unit: Decimal = Field(gt=0)
    comment: str | None = None


class RentStepRead(RentStepCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    lease_id: str


class FreeRentPeriodCreate(BaseModel):
    start_date: date
    end_date: date
    applies_to_base_rent: bool = True
    applies_to_recoveries: bool = False
    comment: str | None = None

    @model_validator(mode="after")
    def end_after_start(self) -> "FreeRentPeriodCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class FreeRentPeriodRead(FreeRentPeriodCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    lease_id: str


class LeaseExpenseRecoveryCreate(BaseModel):
    expense_category: str
    recovery_type: RecoveryType
    base_year_stop_amount: Decimal | None = None
    cap_per_sf_annual: Decimal | None = Field(default=None, ge=0)
    floor_per_sf_annual: Decimal | None = Field(default=None, ge=0)
    admin_fee_pct: Decimal | None = Field(default=None, ge=0, le=1)
    cap_group: str | None = Field(
        default=None, max_length=50,
        description="Categories with the same cap group share one cap on their combined recovery",
    )
    cap_growth_pct: Decimal | None = Field(
        default=None, ge=0, le=1, description="Recovery grows at most this much a year from the lease start year (an exercised option keeps the original lease start); with base-year-stop or modified gross members the cap limits the tenant's share of expenses and the stop comes off the capped amount",
    )
    expense_stop_per_sf: Decimal | None = Field(
        default=None, ge=0, description="Modified gross: this category alone recovers its $/SF/yr above this stop",
    )
    recoverable_pct: Decimal = Field(
        default=Decimal(1), ge=0, le=1, description="Share of the category's expense (after gross-up and pool deductions) that is recoverable, applied before the stop, pro rata share and cap/floor (e.g. 0.6 recovers 60%)",
    )
    comment: str | None = None


class LeaseExpenseRecoveryRead(LeaseExpenseRecoveryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    lease_id: str


class TenantBase(BaseModel):
    name: str = Field(max_length=255)
    credit_rating: str | None = Field(default=None, max_length=20)
    industry: str | None = Field(default=None, max_length=100)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    comment: str | None = None


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    credit_rating: str | None = Field(default=None, max_length=20)
    industry: str | None = Field(default=None, max_length=100)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    comment: str | None = None


class TenantRead(TenantBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str | None = None
    valuation_id: str | None = None
    created_at: datetime
    updated_at: datetime


class LeaseBase(BaseModel):
    tenant_id: str | None = None
    lease_type: LeaseType = LeaseType.IN_PLACE
    lease_start_date: date
    lease_end_date: date
    base_rent_per_unit: Decimal = Field(
        gt=0,
        description="$/SF/year for commercial leases; $/unit/month for multifamily/self-storage",
    )
    rent_basis: Literal["per_area", "total"] = Field(
        default="per_area",
        description="'per_area': rent is $ per SF (or unit) times area; 'total': rent is the whole space's $ amount "
        "(per year, or per month when monthly), e.g. an antenna on 0 SF",
    )
    rent_payment_frequency: Literal["annual", "monthly"] = Field(
        default="annual",
        description="'annual' ($/SF/yr commercial) or 'monthly' ($/unit/mo residential)",
    )
    escalation_type: EscalationType = Field(
        default=EscalationType.FLAT,
        description="flat=no escalation, pct_annual=fixed %, cpi=CPI-indexed, fixed_step=explicit schedule",
    )
    escalation_pct_annual: Decimal | None = Field(
        default=None, ge=0, le=1,
        description="Annual escalation rate (e.g. 0.03 = 3%). Required when escalation_type=pct_annual.",
    )
    cpi_floor: Decimal | None = Field(
        default=None, ge=0,
        description="Minimum annual CPI adjustment (e.g. 0.02 = 2% floor). Only applies when escalation_type=cpi.",
    )
    cpi_cap: Decimal | None = Field(
        default=None, ge=0,
        description="Maximum annual CPI adjustment (e.g. 0.05 = 5% cap). Only applies when escalation_type=cpi.",
    )
    recovery_type: RecoveryType = Field(
        default=RecoveryType.NNN,
        description="nnn=tenant pays all expenses, full_service_gross=no recovery, "
                    "modified_gross=expense stop, base_year_stop=tenant pays above base year",
    )
    pro_rata_share_pct: Decimal | None = Field(
        default=None, ge=0, le=1,
        description="Tenant's share of recoverable expenses (0-1). If omitted, auto-computed as suite_area/total_area.",
    )
    base_year: int | None = Field(
        default=None,
        description="Calendar year used as the base for base_year_stop recovery calculations.",
    )
    base_year_stop_amount: Decimal | None = Field(
        default=None, ge=0,
        description="Total expense amount ($) in the base year. Tenant pays their pro-rata share above this "
                    "threshold. Required for base_year_stop leases; defaults to Year 1 expense if omitted.",
    )
    expense_stop_per_sf: Decimal | None = Field(
        default=None, ge=0,
        description="$/SF/year above which tenant begins paying expenses (for modified_gross leases).",
    )
    pct_rent_breakpoint: Decimal | None = Field(
        default=None, ge=0,
        description="Total annual sales ($) threshold above which percentage rent applies. Requires pct_rent_rate.",
    )
    pct_rent_rate: Decimal | None = Field(
        default=None, ge=0, le=1,
        description="Overage percentage rate (e.g. 0.06 = 6% of sales above breakpoint).",
    )
    projected_annual_sales_per_sf: Decimal | None = Field(
        default=None, ge=0,
        description="Projected annual gross sales per SF (retail). Used to compute percentage rent overage.",
    )
    renewal_probability: Decimal | None = Field(
        default=None, ge=0, le=1,
        description="Override the market leasing profile renewal probability for this specific tenant.",
    )
    renewal_rent_spread_pct: Decimal | None = Field(
        default=None, ge=-1, le=2,
        description="Override renewal rent adjustment vs. market (e.g. -0.05 = 5% below market at renewal).",
    )
    exclude_from_general_vacancy: bool = Field(
        default=False, description="Credit tenant: exclude this lease's rent from general vacancy and credit loss.",
    )
    vacancy_exclusion_ends_at_rollover: bool = Field(
        default=True,
        description="published DCF software 'Exclude upon rollover': off carries the exclusion to the market leases that follow.",
    )
    prorate_rent_steps: bool = Field(
        default=False,
        description="Fixed-step leases: a mid-month step splits that month by days instead of starting next month.",
    )
    upon_expiration: UponExpiration = Field(
        default=UponExpiration.MARKET,
        description="market (probability blend), renew, vacate, option (contract option), reabsorb (stays vacant)",
    )
    option_rent_per_unit: Decimal | None = Field(
        default=None, gt=0, description="Option rent; blank = market rent x (1 + renewal adjustment)",
    )
    option_term_months: int | None = Field(default=None, ge=1, description="Option term; blank = MLA renewal term")
    option_ti_per_sf: Decimal = Field(default=Decimal("0"), ge=0)
    option_lc_pct: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    committed_ti_amount: Decimal = Field(
        default=Decimal("0"), ge=0, description="Contractual TI still to be paid, $ total (paid at lease start or analysis start)",
    )
    committed_lc_amount: Decimal = Field(default=Decimal("0"), ge=0, description="Contractual LC still to be paid, $ total")
    comment: str | None = None
    recovery_structure_id: str | None = None

    @model_validator(mode="after")
    def end_after_start(self) -> "LeaseBase":
        if self.lease_end_date <= self.lease_start_date:
            raise ValueError("lease_end_date must be after lease_start_date")
        return self


class LeaseCreate(LeaseBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "lease_start_date": "2025-01-01",
                "lease_end_date": "2029-12-31",
                "base_rent_per_unit": "32.50",
                "rent_payment_frequency": "annual",
                "escalation_type": "pct_annual",
                "escalation_pct_annual": "0.03",
                "recovery_type": "nnn",
            }
        }
    )


class LeaseUpdate(BaseModel):
    tenant_id: str | None = None
    lease_type: LeaseType | None = None
    lease_start_date: date | None = None
    lease_end_date: date | None = None
    base_rent_per_unit: Decimal | None = Field(default=None, gt=0)
    rent_basis: Literal["per_area", "total"] | None = None
    escalation_type: EscalationType | None = None
    escalation_pct_annual: Decimal | None = Field(default=None, ge=0, le=1)
    cpi_floor: Decimal | None = None
    cpi_cap: Decimal | None = None
    recovery_type: RecoveryType | None = None
    pro_rata_share_pct: Decimal | None = Field(default=None, ge=0, le=1)
    base_year: int | None = None
    base_year_stop_amount: Decimal | None = None
    expense_stop_per_sf: Decimal | None = None
    pct_rent_breakpoint: Decimal | None = None
    pct_rent_rate: Decimal | None = None
    projected_annual_sales_per_sf: Decimal | None = None
    renewal_probability: Decimal | None = Field(default=None, ge=0, le=1)
    renewal_rent_spread_pct: Decimal | None = None
    exclude_from_general_vacancy: bool | None = None
    vacancy_exclusion_ends_at_rollover: bool | None = None
    prorate_rent_steps: bool | None = None
    upon_expiration: UponExpiration | None = None
    option_rent_per_unit: Decimal | None = Field(default=None, gt=0)
    option_term_months: int | None = Field(default=None, ge=1)
    option_ti_per_sf: Decimal | None = Field(default=None, ge=0)
    option_lc_pct: Decimal | None = Field(default=None, ge=0, le=1)
    committed_ti_amount: Decimal | None = Field(default=None, ge=0)
    committed_lc_amount: Decimal | None = Field(default=None, ge=0)
    comment: str | None = None
    recovery_structure_id: str | None = None


class LeaseBulkUpdateItem(BaseModel):
    lease_id: str
    fields: LeaseUpdate


class LeaseBulkUpdateRequest(BaseModel):
    updates: list[LeaseBulkUpdateItem] = Field(min_length=1)
    atomic: bool = False


class LeaseBulkUpdateFailure(BaseModel):
    lease_id: str
    status_code: int
    detail: str


class LeaseBulkUpdateResponse(BaseModel):
    updated_count: int
    failed: list[LeaseBulkUpdateFailure] = Field(default_factory=list)


class LeaseExpenseRecoveryBulkUpsertItem(BaseModel):
    lease_id: str
    override_id: str | None = None
    fields: LeaseExpenseRecoveryCreate


class LeaseExpenseRecoveryBulkUpsertRequest(BaseModel):
    updates: list[LeaseExpenseRecoveryBulkUpsertItem] = Field(min_length=1)
    atomic: bool = False


class LeaseExpenseRecoveryBulkUpsertFailure(BaseModel):
    lease_id: str
    override_id: str | None = None
    status_code: int
    detail: str


class LeaseExpenseRecoveryBulkUpsertResponse(BaseModel):
    upserted_count: int
    failed: list[LeaseExpenseRecoveryBulkUpsertFailure] = Field(default_factory=list)


class LeaseRead(LeaseBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    rent_payment_frequency: str = "annual"  # rows saved before the create schema was restricted still read back
    suite_id: str
    created_at: datetime
    updated_at: datetime
    tenant: TenantRead | None = None
    rent_steps: list[RentStepRead] = []
    free_rent_periods: list[FreeRentPeriodRead] = []
    expense_recovery_overrides: list[LeaseExpenseRecoveryRead] = []
    recovery_structure_id: str | None = None
