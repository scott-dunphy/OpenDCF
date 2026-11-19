from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    amount_basis: Literal["total", "per_area"] = Field(
        default="total",
        description="total = $ for the property; per_area = $/SF/yr (or $/unit/yr) times property total area",
    )
    variable_pct: Decimal = Field(
        default=Decimal("0"), ge=0, le=1,
        description="Share that varies with occupancy. 0 = use amount as entered; above 0 the amount is "
                    "stated at 100% occupancy and the variable share scales with occupancy.",
    )
    growth_rate_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    growth_schedule: list[Annotated[Decimal, Field(ge=-1, le=1)]] = Field(default_factory=list, description="Year-by-year rates (Year 1, 2, ...; last carries forward). Replaces the single rate when set.")
    amount_schedule: list[Annotated[Decimal, Field(ge=0)]] = Field(
        default_factory=list,
        description="Amounts by year (Year 1, 2, ...) in amount_basis. Replaces the base amount and growth for "
                    "those years; later years grow from the last amount at the growth rate.",
    )
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
    is_memo: bool = Field(
        default=False,
        description="Memo line (e.g. amortized capital billed to tenants): recoverable but not deducted as an "
                    "operating expense. Not allowed on a % of EGI line.",
    )

    @model_validator(mode="after")
    def _memo_not_pct_of_egi(self):
        if self.is_memo and self.is_pct_of_egi:
            raise ValueError("A % of EGI line cannot be a memo line")
        return self


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
    amount_basis: Literal["total", "per_area"] | None = None
    variable_pct: Decimal | None = Field(default=None, ge=0, le=1)
    growth_rate_pct: Decimal | None = Field(default=None, ge=0, le=1)
    growth_schedule: list[Annotated[Decimal, Field(ge=-1, le=1)]] | None = None
    amount_schedule: list[Annotated[Decimal, Field(ge=0)]] | None = None
    is_recoverable: bool | None = None
    is_gross_up_eligible: bool | None = None
    gross_up_vacancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    is_pct_of_egi: bool | None = None
    pct_of_egi: Decimal | None = Field(default=None, ge=0, le=1)
    is_memo: bool | None = None


class PropertyExpenseRead(PropertyExpenseBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    created_at: datetime
    updated_at: datetime
