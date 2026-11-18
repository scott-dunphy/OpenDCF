from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from src.schemas.common import AreaUnit, MonthStart, PropertyType, first_of_next_month_unless_first


class SuiteBase(BaseModel):
    suite_name: str = Field(max_length=100)
    floor: int | None = None
    area: Decimal = Field(ge=0, description="0 for space with no area, e.g. an antenna or sign")
    space_type: str = Field(max_length=100)
    is_available: bool = True
    comment: str | None = None
    market_space_type: str | None = Field(default=None, max_length=100)  # re-lease as this space type
    absorption_start_date: date | None = Field(
        default=None,
        description="Lease-up: date leasing of vacant space begins (blank = when it becomes vacant)",
    )
    lease_up_months: int | None = Field(
        default=None,
        ge=0,
        le=120,
        description="Lease-up: months from leasing start to new-tenant commencement (blank = MLA downtime). "
        "Setting either lease-up field leases vacant space to a new tenant instead of the renewal blend.",
    )


class SuiteCreate(SuiteBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "suite_name": "Suite 100",
                "area": "5000",
                "space_type": "office",
                "floor": 1,
            }
        }
    )


class SuiteUpdate(BaseModel):
    suite_name: str | None = Field(default=None, max_length=100)
    floor: int | None = None
    area: Decimal | None = Field(default=None, ge=0)
    space_type: str | None = Field(default=None, max_length=100)
    is_available: bool | None = None
    comment: str | None = None
    market_space_type: str | None = Field(default=None, max_length=100)  # re-lease as this space type
    absorption_start_date: date | None = None
    lease_up_months: int | None = Field(default=None, ge=0, le=120)


class SuiteRead(SuiteBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    created_at: datetime
    updated_at: datetime


def _validate_storage_json(value: str | None) -> str | None:
    """Reject a self storage model that would not run (422 with the reason)."""
    if value:
        from pydantic import ValidationError

        from src.schemas.self_storage import SelfStorageOperatingModel

        try:
            SelfStorageOperatingModel.model_validate_json(value)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"]
                for e in exc.errors()
            )
            raise ValueError(f"Invalid self storage model: {problems}") from None
    return value


class PropertyBase(BaseModel):
    name: str = Field(max_length=255)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=50)
    zip_code: str | None = Field(default=None, max_length=20)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    market: str | None = Field(
        default=None,
        max_length=100,
        description="Market (e.g. MSA) used to match portfolio assumptions",
    )
    cbsa_code: str | None = Field(
        default=None,
        description="Census CBSA code (5 digits); filled from the ZIP code when left blank",
    )
    quality_score: Decimal | None = Field(
        default=None, ge=1, le=5,
        description="1-5, 5 = best, 3 = market base; positions assumption-library ranges",
    )

    @field_validator("cbsa_code")
    @classmethod
    def _known_cbsa(cls, v: str | None) -> str | None:
        from src.services import cbsa

        if v and cbsa.get(v.strip()) is None:
            raise ValueError(f"Unknown CBSA code {v}")
        return v.strip() if v else v
    external_id: str | None = Field(
        default=None,
        max_length=100,
        description="Source system id, e.g. PUBLISHED Property_ExternalID",
    )
    property_type: PropertyType
    total_area: Decimal = Field(gt=0, description="Total GLA in SF or total unit count")
    area_unit: AreaUnit
    year_built: int | None = Field(default=None, ge=1800, le=2100)
    analysis_start_date: date
    analysis_period_months: int = Field(
        default=120, ge=12, le=360, multiple_of=12, description="Whole years only"
    )
    fiscal_year_end_month: int = Field(default=12, ge=1, le=12)
    ownership_pct: Decimal = Field(
        default=Decimal("1.0"), ge=0, le=1, description="Ownership share (0-1), e.g. 0.5 = 50%"
    )
    comment: str | None = None
    amenities: dict[str, bool | int | float | str | None] = Field(default_factory=dict)
    # Operating models seed the property's first valuation; each valuation then owns its own
    marina_assumptions_json: str | None = Field(
        default=None, description="Marina operating model for the first valuation (slip classes, demand, revenue, costs)"
    )
    seniors_housing_assumptions_json: str | None = Field(
        default=None, description="Seniors housing operating model for the first valuation (unit mix, care tiers)"
    )
    self_storage_assumptions_json: str | None = Field(
        default=None, description="Self storage operating model for the first valuation (unit mix, rates, churn, ECRI)"
    )

    @field_validator("self_storage_assumptions_json")
    @classmethod
    def _valid_storage_model(cls, value):
        return _validate_storage_json(value)

    @field_validator("ownership_pct", mode="before")
    @classmethod
    def normalize_ownership_pct(cls, value):
        """
        Accept ownership as either fraction (0-1) or percent (0-100).
        Examples: 0.5 -> 0.5, 50 -> 0.5, "50%" -> 0.5
        """
        if value is None:
            return value

        percent_input = False
        if isinstance(value, str):
            v = value.strip()
            if v == "":
                return None
            if v.endswith("%"):
                percent_input = True
                v = v[:-1].strip()
            value = v

        d = Decimal(str(value))
        if percent_input or d > Decimal("1"):
            d = d / Decimal("100")

        if d < Decimal("0") or d > Decimal("1"):
            raise ValueError(
                "ownership_pct must be between 0 and 1 (or 0 and 100 when entered as percent)"
            )
        return d


class PropertyCreate(PropertyBase):
    analysis_start_date: MonthStart = Field(
        default_factory=lambda: first_of_next_month_unless_first(date.today()),
        description="Analysis start date; a mid-month date moves to the 1st of the next month. Defaults to today.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "101 Market Street",
                "property_type": "office",
                "total_area": "50000",
                "area_unit": "sf",
                "analysis_start_date": "2025-01-01",
                "analysis_period_months": 120,
                "fiscal_year_end_month": 12,
                "city": "San Francisco",
                "state": "CA",
            }
        }
    )


class PropertyUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=50)
    zip_code: str | None = Field(default=None, max_length=20)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    market: str | None = Field(
        default=None,
        max_length=100,
        description="Market (e.g. MSA) used to match portfolio assumptions",
    )
    cbsa_code: str | None = Field(
        default=None,
        description="Census CBSA code (5 digits); empty string clears; refilled from a changed ZIP",
    )
    quality_score: Decimal | None = Field(
        default=None, ge=1, le=5,
        description="1-5, 5 = best, 3 = market base; positions assumption-library ranges",
    )

    @field_validator("cbsa_code")
    @classmethod
    def _known_cbsa(cls, v: str | None) -> str | None:
        from src.services import cbsa

        if v and cbsa.get(v.strip()) is None:
            raise ValueError(f"Unknown CBSA code {v}")
        return v.strip() if v else v
    external_id: str | None = Field(
        default=None,
        max_length=100,
        description="Source system id, e.g. PUBLISHED Property_ExternalID",
    )
    property_type: PropertyType | None = None
    total_area: Decimal | None = Field(default=None, gt=0)
    area_unit: AreaUnit | None = None
    year_built: int | None = Field(default=None, ge=1800, le=2100)
    analysis_start_date: MonthStart | None = None
    analysis_period_months: int | None = Field(default=None, ge=12, le=360, multiple_of=12)
    fiscal_year_end_month: int | None = Field(default=None, ge=1, le=12)
    ownership_pct: Decimal | None = Field(default=None, ge=0, le=1)
    comment: str | None = None
    amenities: dict[str, bool | int | float | str | None] | None = None
    @field_validator("ownership_pct", mode="before")
    @classmethod
    def normalize_ownership_pct(cls, value):
        """
        Accept ownership as either fraction (0-1) or percent (0-100).
        Examples: 0.5 -> 0.5, 50 -> 0.5, "50%" -> 0.5
        """
        if value is None:
            return value

        percent_input = False
        if isinstance(value, str):
            v = value.strip()
            if v == "":
                return None
            if v.endswith("%"):
                percent_input = True
                v = v[:-1].strip()
            value = v

        d = Decimal(str(value))
        if percent_input or d > Decimal("1"):
            d = d / Decimal("100")

        if d < Decimal("0") or d > Decimal("1"):
            raise ValueError(
                "ownership_pct must be between 0 and 1 (or 0 and 100 when entered as percent)"
            )
        return d


class PropertyRead(PropertyBase):
    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def cbsa_title(self) -> str | None:
        from src.services import cbsa

        return cbsa.title(self.cbsa_code)

    id: str
    created_at: datetime
    updated_at: datetime


class PropertyList(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    property_type: PropertyType
    total_area: Decimal
    area_unit: AreaUnit
    analysis_start_date: date
    analysis_period_months: int
    city: str | None = None
    state: str | None = None
    market: str | None = None
    external_id: str | None = None
    ownership_pct: Decimal = Decimal("1.0")
    created_at: datetime
    updated_at: datetime
    inputs_updated_at: datetime | None = None


class ValuationSnapshot(BaseModel):
    id: str
    name: str
    value: Decimal | None = None
    going_in_cap_rate: Decimal | None = None
    irr: Decimal | None = None  # only when a purchase price is set; otherwise IRR = discount rate
    purchase_price: Decimal | None = None
    last_run_at: datetime | None = None
    is_stale: bool = False
    stale_reason: Literal["inputs", "engine"] | None = None  # why it needs a re-run


class PropertySummary(BaseModel):
    id: str
    name: str
    property_type: PropertyType
    city: str | None = None
    state: str | None = None
    market: str | None = None
    total_area: Decimal
    area_unit: AreaUnit
    ownership_pct: Decimal = Decimal("1.0")
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    suite_count: int = 0
    valuation_count: int = 0
    inputs_updated_at: datetime | None = None
    primary_valuation: ValuationSnapshot | None = None
