from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.common import RecoveryType


class RecoveryStructureItemBase(BaseModel):
    expense_category: str = Field(min_length=1, max_length=50)
    recovery_type: RecoveryType
    base_year_stop_amount: Decimal | None = None
    cap_per_sf_annual: Decimal | None = Field(default=None, ge=0)
    floor_per_sf_annual: Decimal | None = Field(default=None, ge=0)
    admin_fee_pct: Decimal | None = Field(default=None, ge=0, le=1)
    comment: str | None = None


class RecoveryStructureItemCreate(RecoveryStructureItemBase):
    pass


class RecoveryStructureItemRead(RecoveryStructureItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    recovery_structure_id: str


class RecoveryStructureCreate(BaseModel):
    name: str = Field(max_length=255)
    description: str | None = None
    comment: str | None = None
    default_recovery_type: RecoveryType = RecoveryType.NNN
    items: list[RecoveryStructureItemCreate] = []

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Standard NNN with CAM Cap",
                "default_recovery_type": "nnn",
                "items": [
                    {"expense_category": "cam", "recovery_type": "nnn",
                     "cap_per_sf_annual": "12.00", "admin_fee_pct": "0.15"}
                ]
            }
        }
    )


class RecoveryStructureUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    comment: str | None = None
    default_recovery_type: RecoveryType | None = None


class RecoveryStructureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    name: str
    description: str | None
    comment: str | None
    default_recovery_type: str
    created_at: datetime
    updated_at: datetime
    items: list[RecoveryStructureItemRead] = []
