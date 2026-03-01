from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PropertyOtherIncomeCreate(BaseModel):
    category: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=255)
    comment: str | None = None
    base_year_amount: Decimal = Field(ge=0)
    growth_rate_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "category": "parking",
                "description": "Garage parking income",
                "base_year_amount": "200000",
                "growth_rate_pct": "0.03",
            }
        }
    )


class PropertyOtherIncomeUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=100)
    description: str | None = None
    comment: str | None = None
    base_year_amount: Decimal | None = Field(default=None, ge=0)
    growth_rate_pct: Decimal | None = Field(default=None, ge=0, le=1)


class PropertyOtherIncomeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    category: str
    description: str | None
    comment: str | None
    base_year_amount: Decimal
    growth_rate_pct: Decimal
    created_at: datetime
    updated_at: datetime
