from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketLeasingProfileBase(BaseModel):
    space_type: str = Field(max_length=100)
    description: str | None = None
    comment: str | None = None

    market_rent_per_unit: Decimal = Field(gt=0)
    rent_growth_rate_pct: Decimal = Field(ge=0, le=1, default=Decimal("0.03"))

    # New tenant
    new_lease_term_months: int = Field(default=60, ge=1)
    new_tenant_ti_per_sf: Decimal = Field(default=Decimal("0"), ge=0)
    new_tenant_lc_pct: Decimal = Field(default=Decimal("0.06"), ge=0, le=1)
    new_tenant_free_rent_months: int = Field(default=0, ge=0)
    downtime_months: int = Field(default=3, ge=0)

    # Renewal
    renewal_probability: Decimal = Field(default=Decimal("0.65"), ge=0, le=1)
    renewal_lease_term_months: int = Field(default=60, ge=1)
    renewal_ti_per_sf: Decimal = Field(default=Decimal("0"), ge=0)
    renewal_lc_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    renewal_free_rent_months: int = Field(default=0, ge=0)
    renewal_rent_adjustment_pct: Decimal = Field(
        default=Decimal("0"), ge=-1, le=1,
        description="Renewal rent vs market: -0.05 = 5% below market"
    )

    # Structural vacancy
    general_vacancy_pct: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)
    credit_loss_pct: Decimal = Field(default=Decimal("0.01"), ge=0, le=1)

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

    @model_validator(mode="after")
    def validate_concession_mode(self) -> "MarketLeasingProfileBase":
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
    rent_growth_rate_pct: Decimal | None = Field(default=None, ge=0, le=1)
    new_lease_term_months: int | None = Field(default=None, ge=1)
    new_tenant_ti_per_sf: Decimal | None = Field(default=None, ge=0)
    new_tenant_lc_pct: Decimal | None = Field(default=None, ge=0, le=1)
    new_tenant_free_rent_months: int | None = Field(default=None, ge=0)
    downtime_months: int | None = Field(default=None, ge=0)
    renewal_probability: Decimal | None = Field(default=None, ge=0, le=1)
    renewal_lease_term_months: int | None = Field(default=None, ge=1)
    renewal_ti_per_sf: Decimal | None = Field(default=None, ge=0)
    renewal_lc_pct: Decimal | None = Field(default=None, ge=0, le=1)
    renewal_free_rent_months: int | None = Field(default=None, ge=0)
    renewal_rent_adjustment_pct: Decimal | None = Field(default=None, ge=-1, le=1)
    general_vacancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    credit_loss_pct: Decimal | None = Field(default=None, ge=0, le=1)
    concession_timing_mode: str | None = None
    concession_year1_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year2_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year3_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year4_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_year5_months: Decimal | None = Field(default=None, ge=0, le=12)
    concession_stabilized_months: Decimal | None = Field(default=None, ge=0, le=12)

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
    created_at: datetime
    updated_at: datetime
