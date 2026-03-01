from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.common import ValuationStatus


class ValuationBase(BaseModel):
    name: str = Field(max_length=255)
    description: str | None = None
    comment: str | None = None
    discount_rate: Decimal = Field(gt=0, lt=1, description="e.g. 0.08 = 8%")
    exit_cap_rate: Decimal = Field(gt=0, lt=1, description="e.g. 0.065 = 6.5%")
    exit_cap_applied_to_year: int = Field(
        default=-1,
        description="-1 = forward year NOI (Hold Period + 1), or specific analysis year number"
    )
    exit_costs_pct: Decimal = Field(default=Decimal("0.02"), ge=0, lt=1)
    transfer_tax_preset: str = Field(
        default="none",
        description="Transfer tax preset code (none, custom_rate, la_city_ula, etc.)",
    )
    transfer_tax_custom_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    apply_stabilized_gross_up: bool = True
    stabilized_occupancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    capital_reserves_per_unit: Decimal = Field(
        default=Decimal("0.25"), ge=0,
        description="$/SF/yr or $/unit/yr capital reserves"
    )
    use_mid_year_convention: bool = False

    # Optional debt
    loan_amount: Decimal | None = Field(default=None, ge=0)
    interest_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    amortization_months: int | None = Field(default=None, ge=1)
    loan_term_months: int | None = Field(default=None, ge=1)
    io_period_months: int | None = Field(default=0, ge=0)


class ValuationCreate(ValuationBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Base Case Q1 2025",
                "discount_rate": "0.08",
                "exit_cap_rate": "0.065",
                "exit_cap_applied_to_year": -1,
                "exit_costs_pct": "0.02",
                "transfer_tax_preset": "none",
                "apply_stabilized_gross_up": True,
                "stabilized_occupancy_pct": "0.95",
                "capital_reserves_per_unit": "0.25",
                "use_mid_year_convention": False,
            }
        }
    )


class ValuationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    comment: str | None = None
    discount_rate: Decimal | None = Field(default=None, gt=0, lt=1)
    exit_cap_rate: Decimal | None = Field(default=None, gt=0, lt=1)
    exit_cap_applied_to_year: int | None = None
    exit_costs_pct: Decimal | None = Field(default=None, ge=0, lt=1)
    transfer_tax_preset: str | None = None
    transfer_tax_custom_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    apply_stabilized_gross_up: bool | None = None
    stabilized_occupancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    capital_reserves_per_unit: Decimal | None = Field(default=None, ge=0)
    use_mid_year_convention: bool | None = None
    loan_amount: Decimal | None = None
    interest_rate: Decimal | None = None
    amortization_months: int | None = None
    loan_term_months: int | None = None
    io_period_months: int | None = None


class ValuationRead(ValuationBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    status: ValuationStatus
    error_message: str | None = None
    result_npv: Decimal | None = None
    result_irr: Decimal | None = None
    result_going_in_cap_rate: Decimal | None = None
    result_exit_value: Decimal | None = None
    result_equity_multiple: Decimal | None = None
    created_at: datetime
    updated_at: datetime
