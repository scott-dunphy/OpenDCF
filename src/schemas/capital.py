from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PropertyCapitalProjectCreate(BaseModel):
    description: str = Field(max_length=255)
    comment: str | None = None
    total_amount: Decimal = Field(gt=0)
    start_date: date
    duration_months: int = Field(ge=1)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "description": "Unit Renovation Program",
                "total_amount": "500000",
                "start_date": "2025-07-01",
                "duration_months": 15,
            }
        }
    )


class PropertyCapitalProjectUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=255)
    comment: str | None = None
    total_amount: Decimal | None = Field(default=None, gt=0)
    start_date: date | None = None
    duration_months: int | None = Field(default=None, ge=1)


class PropertyCapitalProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    description: str
    comment: str | None
    total_amount: Decimal
    start_date: date
    duration_months: int
    created_at: datetime
    updated_at: datetime
