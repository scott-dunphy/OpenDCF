from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Denominator = Literal["property_area", "fixed_area", "occupied_area"]


class RecoveryPoolBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    expense_categories: list[str] = Field(
        default_factory=list, description="Expense categories recovered through this pool (each in one pool at most)",
    )
    denominator: Denominator = Field(
        default="property_area",
        description="Share denominator: property area less excluded suites, a fixed area, or occupied area",
    )
    fixed_area: Decimal | None = Field(default=None, gt=0, description="Denominator area for fixed_area")
    minimum_occupancy_pct: Decimal | None = Field(
        default=None, ge=0, le=1,
        description="occupied_area: the denominator is at least this share of the included area",
    )
    excluded_suite_ids: list[str] = Field(
        default_factory=list, description="Suites left out of the denominator (anchors, outparcels)",
    )
    deduct_excluded_recoveries: bool = Field(
        default=True,
        description="What excluded suites' leases pay toward the pool comes off it before the others share it",
    )

    @model_validator(mode="after")
    def check(self):
        if self.denominator == "fixed_area" and self.fixed_area is None:
            raise ValueError("fixed_area is required when the denominator is fixed_area")
        self.expense_categories = list(dict.fromkeys(c.strip() for c in self.expense_categories if c.strip()))
        self.excluded_suite_ids = list(dict.fromkeys(self.excluded_suite_ids))
        return self

    model_config = ConfigDict(json_schema_extra={"example": {
        "name": "Shop CAM", "expense_categories": ["cam"], "denominator": "property_area",
        "excluded_suite_ids": [], "deduct_excluded_recoveries": True,
    }})


class RecoveryPoolCreate(RecoveryPoolBase):
    pass


class RecoveryPoolUpdate(RecoveryPoolBase):
    pass


class RecoveryPoolRead(RecoveryPoolBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    created_at: datetime
    updated_at: datetime
