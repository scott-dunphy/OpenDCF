from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.common import AreaUnit, PropertyType


class SuiteBase(BaseModel):
    suite_name: str = Field(max_length=100)
    floor: int | None = None
    area: Decimal = Field(gt=0)
    space_type: str = Field(max_length=100)
    is_available: bool = True
    comment: str | None = None
    market_leasing_profile_id: str | None = None


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
    area: Decimal | None = Field(default=None, gt=0)
    space_type: str | None = Field(default=None, max_length=100)
    is_available: bool | None = None
    comment: str | None = None
    market_leasing_profile_id: str | None = None


class SuiteRead(SuiteBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    created_at: datetime
    updated_at: datetime


class PropertyBase(BaseModel):
    name: str = Field(max_length=255)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=50)
    zip_code: str | None = Field(default=None, max_length=20)
    property_type: PropertyType
    total_area: Decimal = Field(gt=0, description="Total GLA in SF or total unit count")
    area_unit: AreaUnit
    year_built: int | None = Field(default=None, ge=1800, le=2100)
    analysis_start_date: date
    analysis_period_months: int = Field(default=120, ge=12, le=360)
    fiscal_year_end_month: int = Field(default=12, ge=1, le=12)
    comment: str | None = None


class PropertyCreate(PropertyBase):
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
    property_type: PropertyType | None = None
    total_area: Decimal | None = Field(default=None, gt=0)
    area_unit: AreaUnit | None = None
    year_built: int | None = Field(default=None, ge=1800, le=2100)
    analysis_start_date: date | None = None
    analysis_period_months: int | None = Field(default=None, ge=12, le=360)
    fiscal_year_end_month: int | None = Field(default=None, ge=1, le=12)
    comment: str | None = None


class PropertyRead(PropertyBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime
    suites: list[SuiteRead] = []


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
    created_at: datetime
    updated_at: datetime
