from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketLeasingProfileBase(BaseModel):
    space_type: str = Field(max_length=100)
    description: str | None = None
    comment: str | None = None

    market_rent_per_unit: Decimal = Field(gt=0)
    rent_basis: Literal["per_area", "total"] = Field(
        default="per_area",
        description="'per_area': rent is $ per SF (or unit) times area; 'total': rent is the whole space's $ amount "
        "(per year, or per month when monthly), e.g. an antenna on 0 SF",
    )
    rent_growth_rate_pct: Decimal = Field(ge=0, le=1, default=Decimal("0.03"))
    rent_growth_schedule: list[Annotated[Decimal, Field(ge=-1, le=1)]] = Field(default_factory=list, description="Year-by-year rates (Year 1, 2, ...; last carries forward). Replaces the single rate when set.")

    # New tenant
    new_lease_term_months: int = Field(default=60, ge=1)
    new_tenant_ti_per_sf: Decimal = Field(default=Decimal("0"), ge=0)
    new_tenant_lc_pct: Decimal = Field(default=Decimal("0.06"), ge=0, le=1)
    new_tenant_lc_per_sf: Decimal = Field(default=Decimal("0"), ge=0, description="$/SF, on top of the % of lease rent")
    new_tenant_lc_pct_by_lease_year: list[Annotated[Decimal, Field(ge=0, le=1)]] = Field(
        default_factory=list, description="% of each lease year's rent: year 1 = the first 12 months of the lease; the last rate carries forward. Replaces the single %")
    new_tenant_free_rent_months: int = Field(default=0, ge=0)
    downtime_months: int = Field(default=3, ge=0)

    # Renewal
    renewal_probability: Decimal = Field(default=Decimal("0.65"), ge=0, le=1)
    renewal_lease_term_months: int = Field(default=60, ge=1)
    renewal_ti_per_sf: Decimal = Field(default=Decimal("0"), ge=0)
    renewal_lc_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    renewal_lc_per_sf: Decimal = Field(default=Decimal("0"), ge=0, description="$/SF, on top of the % of lease rent")
    renewal_lc_pct_by_lease_year: list[Annotated[Decimal, Field(ge=0, le=1)]] = Field(
        default_factory=list, description="% of each lease year's rent: year 1 = the first 12 months of the lease; the last rate carries forward. Replaces the single %")
    renewal_free_rent_months: int = Field(default=0, ge=0)
    renewal_rent_adjustment_pct: Decimal = Field(
        default=Decimal("0"), ge=-1, le=1,
        description="Renewal rent vs market: -0.05 = 5% below market"
    )
    leasing_cost_growth_rate: Decimal = Field(
        default=Decimal("0"), ge=-1, le=1,
        description="Annual growth of TI and LC $/SF from Year 1 to the year a lease starts",
    )
    renewal_rent_rule: Literal["market", "greater_of_prior", "lesser_of_prior"] = Field(
        default="market",
        description="Renewal rent: market (x renewal adjustment), or the greater / lesser of that and the "
                    "expiring lease's last contract rent (steps and escalations included, free rent ignored)",
    )
    round_start_to_month: bool = Field(
        default=False,
        description="Market leases that would start mid-month after downtime start on the 1st of the next "
                    "month; the extra days stay vacant. Probability-tree renewals (no downtime) are not moved.",
    )
    rollover_method: Literal["probability_tree", "blended"] = Field(
        default="probability_tree",
        description="probability_tree: renewal and new tenant modeled as weighted branches. blended: one "
                    "lease with probability-weighted downtime (rounded to whole months), rent, free rent, "
                    "TI and LC, as published DCF software market leasing does.",
    )
    lease_escalation_pct: Decimal | None = Field(
        default=None, ge=-1, le=1,
        description="Annual increase on market leases; blank = the market rent growth rate when the lease starts",
    )
    lease_escalation_per_unit: Decimal | None = Field(
        default=None, ge=0,
        description="Fixed annual increase on market leases in $/SF (or $/unit), e.g. 0.50 = $0.50/SF/yr. "
                    "Replaces the % escalation; leave one of the two blank.",
    )
    lc_includes_escalations: bool = Field(
        default=True,
        description="Leasing commissions on escalated rent (published DCF software step rent); off = base rent only (published DCF software CPI rent)",
    )
    lease_rent_steps: list[tuple[Annotated[int, Field(ge=2)], Annotated[Decimal, Field(ge=-1, le=1)]]] = Field(
        default_factory=list,
        description="Rent increases on market leases at given lease months, on top of the annual escalation: "
                    "[[61, 0.10]] = up 10% from month 61 (published DCF software changing base rent)",
    )
    exclude_from_general_vacancy: bool = Field(
        default=False,
        description="Exclude every lease in suites under this profile from general vacancy and credit loss",
    )

    # Structural vacancy
    general_vacancy_pct: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)
    credit_loss_pct: Decimal = Field(default=Decimal("0.01"), ge=0, le=1)

    # Year-by-year values (Year 1, 2, ...; last carries forward); each replaces its single field
    general_vacancy_schedule: list[Annotated[Decimal, Field(ge=0, le=1)]] = Field(default_factory=list, description="General vacancy by analysis year")
    credit_loss_schedule: list[Annotated[Decimal, Field(ge=0, le=1)]] = Field(default_factory=list, description="Credit loss by analysis year")
    renewal_probability_schedule: list[Annotated[Decimal, Field(ge=0, le=1)]] = Field(
        default_factory=list, description="Renewal probability by the analysis year a lease expires")
    downtime_schedule: list[Annotated[int, Field(ge=0, le=120)]] = Field(
        default_factory=list, description="Downtime months by the analysis year a lease expires")
    new_free_rent_schedule: list[Annotated[Decimal, Field(ge=0, le=120)]] = Field(
        default_factory=list, description="New tenant free rent months by the analysis year the lease starts")
    renewal_free_rent_schedule: list[Annotated[Decimal, Field(ge=0, le=120)]] = Field(
        default_factory=list, description="Renewal free rent months by the analysis year the lease starts")
    leasing_cost_growth_schedule: list[Annotated[Decimal, Field(ge=-1, le=1)]] = Field(
        default_factory=list, description="TI and LC $/SF growth by year")

    # Unit-type concession timing controls (multifamily/self-storage)
    concession_timing_mode: str = Field(
        default="blended",
        description="Concession timing mode: blended or timed.",
    )
    concession_year1_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year2_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year3_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year4_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year5_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_stabilized_months: Decimal | None = Field(default=None, ge=0, le=12)
    next_profile_id: str | None = Field(
        default=None, description="MLA chaining: profile used when a speculative lease under this one expires",
    )
    recovery_structure_id: str | None = Field(
        default=None,
        description="Recovery structure for market leases under this profile; blank copies the expiring lease's "
                    "recovery type, overrides, stop and pro rata share (NNN for space never leased)",
    )

    @model_validator(mode="after")
    def validate_concession_mode(self) -> "MarketLeasingProfileBase":
        if self.lease_escalation_pct is not None and self.lease_escalation_per_unit is not None:
            raise ValueError("Set lease_escalation_pct or lease_escalation_per_unit, not both")
        mode = (self.concession_timing_mode or "blended").lower().strip()
        if mode not in {"blended", "timed"}:
            raise ValueError("concession_timing_mode must be 'blended' or 'timed'")
        self.concession_timing_mode = mode
        return self


class MarketLeasingProfileCreate(MarketLeasingProfileBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "space_type": "office",
                "market_rent_per_unit": "35.00",
                "rent_growth_rate_pct": "0.03",
                "new_lease_term_months": 60,
                "new_tenant_ti_per_sf": "50.00",
                "new_tenant_lc_pct": "0.06",
                "new_tenant_free_rent_months": 3,
                "downtime_months": 6,
                "renewal_probability": "0.65",
                "renewal_lease_term_months": 60,
                "renewal_ti_per_sf": "20.00",
                "renewal_lc_pct": "0.03",
                "renewal_free_rent_months": 1,
                "renewal_rent_adjustment_pct": "-0.05",
                "general_vacancy_pct": "0.05",
                "credit_loss_pct": "0.01",
            }
        }
    )


class MarketLeasingProfileUpdate(BaseModel):
    description: str | None = None
    comment: str | None = None
    market_rent_per_unit: Decimal | None = Field(default=None, gt=0)
    rent_basis: Literal["per_area", "total"] | None = None
    rent_growth_rate_pct: Decimal | None = Field(default=None, ge=0, le=1)
    rent_growth_schedule: list[Annotated[Decimal, Field(ge=-1, le=1)]] | None = None
    new_lease_term_months: int | None = Field(default=None, ge=1)
    new_tenant_ti_per_sf: Decimal | None = Field(default=None, ge=0)
    new_tenant_lc_pct: Decimal | None = Field(default=None, ge=0, le=1)
    new_tenant_lc_per_sf: Decimal | None = Field(default=None, ge=0)
    new_tenant_lc_pct_by_lease_year: list[Annotated[Decimal, Field(ge=0, le=1)]] | None = None
    new_tenant_free_rent_months: int | None = Field(default=None, ge=0)
    downtime_months: int | None = Field(default=None, ge=0)
    renewal_probability: Decimal | None = Field(default=None, ge=0, le=1)
    renewal_lease_term_months: int | None = Field(default=None, ge=1)
    renewal_ti_per_sf: Decimal | None = Field(default=None, ge=0)
    renewal_lc_pct: Decimal | None = Field(default=None, ge=0, le=1)
    renewal_lc_per_sf: Decimal | None = Field(default=None, ge=0)
    renewal_lc_pct_by_lease_year: list[Annotated[Decimal, Field(ge=0, le=1)]] | None = None
    renewal_free_rent_months: int | None = Field(default=None, ge=0)
    renewal_rent_adjustment_pct: Decimal | None = Field(default=None, ge=-1, le=1)
    leasing_cost_growth_rate: Decimal | None = Field(default=None, ge=-1, le=1)
    rollover_method: Literal["probability_tree", "blended"] | None = None
    renewal_rent_rule: Literal["market", "greater_of_prior", "lesser_of_prior"] | None = None
    round_start_to_month: bool | None = None
    lease_escalation_pct: Decimal | None = Field(default=None, ge=-1, le=1)
    lease_escalation_per_unit: Decimal | None = Field(default=None, ge=0)
    lc_includes_escalations: bool | None = None
    lease_rent_steps: list[tuple[Annotated[int, Field(ge=2)], Annotated[Decimal, Field(ge=-1, le=1)]]] | None = None
    exclude_from_general_vacancy: bool | None = None
    general_vacancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    credit_loss_pct: Decimal | None = Field(default=None, ge=0, le=1)
    general_vacancy_schedule: list[Annotated[Decimal, Field(ge=0, le=1)]] | None = None
    credit_loss_schedule: list[Annotated[Decimal, Field(ge=0, le=1)]] | None = None
    renewal_probability_schedule: list[Annotated[Decimal, Field(ge=0, le=1)]] | None = None
    downtime_schedule: list[Annotated[int, Field(ge=0, le=120)]] | None = None
    new_free_rent_schedule: list[Annotated[Decimal, Field(ge=0, le=120)]] | None = None
    renewal_free_rent_schedule: list[Annotated[Decimal, Field(ge=0, le=120)]] | None = None
    leasing_cost_growth_schedule: list[Annotated[Decimal, Field(ge=-1, le=1)]] | None = None
    concession_timing_mode: str | None = None
    concession_year1_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year2_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year3_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year4_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year5_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_stabilized_months: Decimal | None = Field(default=None, ge=0, le=12)
    next_profile_id: str | None = None
    recovery_structure_id: str | None = None  # "" or null clears it

    @model_validator(mode="after")
    def validate_concession_mode(self) -> "MarketLeasingProfileUpdate":
        if self.concession_timing_mode is None:
            return self
        mode = self.concession_timing_mode.lower().strip()
        if mode not in {"blended", "timed"}:
            raise ValueError("concession_timing_mode must be 'blended' or 'timed'")
        self.concession_timing_mode = mode
        return self


class MarketLeasingProfileRead(MarketLeasingProfileBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    valuation_id: str
    created_at: datetime
    updated_at: datetime
