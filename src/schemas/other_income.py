from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class PropertyOtherIncomeCreate(BaseModel):
    category: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=255)
    comment: str | None = None
    base_year_amount: Decimal = Field(ge=0)
    growth_rate_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    growth_schedule: list[Annotated[Decimal, Field(ge=-1, le=1)]] = Field(default_factory=list, description="Year-by-year rates (Year 1, 2, ...; last carries forward). Replaces the single rate when set.")
    amount_schedule: list[Annotated[Decimal, Field(ge=0)]] = Field(
        default_factory=list,
        description="$ by year (Year 1, 2, ...). Replaces the base amount and growth for those years; later "
                    "years grow from the last amount at the growth rate.",
    )

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
    growth_schedule: list[Annotated[Decimal, Field(ge=-1, le=1)]] | None = None
    amount_schedule: list[Annotated[Decimal, Field(ge=0)]] | None = None


class PropertyOtherIncomeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    category: str
    description: str | None
    comment: str | None
    base_year_amount: Decimal
    growth_rate_pct: Decimal
    growth_schedule: list[Decimal] = []
    amount_schedule: list[Decimal] = []
    created_at: datetime
    updated_at: datetime
