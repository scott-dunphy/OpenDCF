from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

STANDARD_EXPENSE_CATEGORIES = (
    "real_estate_taxes",
    "insurance",
    "cam",
    "utilities",
    "management_fee",
    "repairs_maintenance",
    "general_admin",
    "other",
)


class PropertyExpenseBase(BaseModel):
    category: str = Field(
        min_length=1,
        max_length=50,
        description=(
            "Expense category. Standard options include: "
            + ", ".join(STANDARD_EXPENSE_CATEGORIES)
            + ". Custom categories are allowed."
        ),
    )
    description: str | None = None
    comment: str | None = None
    base_year_amount: Decimal = Field(ge=0)
    growth_rate_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    is_recoverable: bool = True
    is_gross_up_eligible: bool = False
    gross_up_vacancy_pct: Decimal | None = Field(
        default=None, ge=0, le=1,
        description="Gross up variable expenses to this occupancy level (e.g. 0.95)"
    )
    is_pct_of_egi: bool = False
    pct_of_egi: Decimal | None = Field(
        default=None, ge=0, le=1,
        description="For management fee: express as % of EGI instead of fixed amount"
    )


class PropertyExpenseCreate(PropertyExpenseBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "category": "real_estate_taxes",
                "base_year_amount": "150000",
                "growth_rate_pct": "0.03",
                "is_recoverable": True,
            }
        }
    )


class PropertyExpenseUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = None
    comment: str | None = None
    base_year_amount: Decimal | None = Field(default=None, ge=0)
    growth_rate_pct: Decimal | None = Field(default=None, ge=0, le=1)
    is_recoverable: bool | None = None
    is_gross_up_eligible: bool | None = None
    gross_up_vacancy_pct: Decimal | None = None
    is_pct_of_egi: bool | None = None
    pct_of_egi: Decimal | None = None


class PropertyExpenseRead(PropertyExpenseBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    created_at: datetime
    updated_at: datetime
