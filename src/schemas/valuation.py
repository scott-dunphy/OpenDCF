from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

import src.engine
from src.schemas.common import MonthStart, ValuationStatus


class AdditionalLoan(BaseModel):
    """A loan besides the first (second mortgage, mezzanine), funded at close."""
    label: str | None = Field(default=None, max_length=100)
    loan_amount: Decimal = Field(gt=0)
    interest_rate: Decimal = Field(ge=0, lt=1)
    amortization_months: int | None = Field(default=None, ge=1, description="Blank = 360")
    loan_term_months: int | None = Field(default=None, ge=1, description="Blank = outstanding through the sale")
    io_period_months: int = Field(default=0, ge=0)
    loan_fees_pct: Decimal = Field(default=Decimal("0"), ge=0, lt=1)


class ValuationBase(BaseModel):
    name: str = Field(max_length=255)
    description: str | None = None
    comment: str | None = None
    analysis_start_date_override: MonthStart | None = Field(
        default=None,
        description="Analysis start for this valuation; a new valuation takes the property's default when not given.",
    )
    analysis_period_months_override: int | None = Field(
        default=None, ge=12, le=360, multiple_of=12,
        description="Hold period for this valuation (whole years); a new valuation takes the property's default when not given.",
    )
    basis_of_value: Literal["market_value", "investment_value", "lending_stress"] = Field(
        default="market_value",
        description="The value basis governing assumptions, evidence, and interpretation.",
    )
    intended_use: str | None = Field(default=None, max_length=255)
    risk_treatment: Literal["deterministic", "scenario_weighted", "stress"] = "deterministic"
    cash_flow_basis: Literal["nominal", "real"] = "nominal"
    discount_rate_basis: Literal["nominal", "real"] = "nominal"
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
    capital_reserves_growth_rate: Decimal = Field(
        default=Decimal("0"), ge=-1, le=1, description="Annual growth of capital reserves from Year 1"
    )
    use_mid_year_convention: bool = False
    terminal_timing: Literal["end_of_period", "mid_year"] = Field(
        default="end_of_period",
        description=(
            "Discount sale proceeds at the end of the hold (recommended) or at mid-year "
            "for legacy parity."
        ),
    )
    cpi_rate: Decimal | None = Field(
        default=None, ge=-1, le=1, description="CPI for CPI-escalated leases; None = 2.5%"
    )
    cpi_schedule: list[Annotated[Decimal, Field(ge=-1, le=1)]] = Field(
        default_factory=list,
        description="Year-by-year CPI (Year 1, 2, ...; last carries forward). Replaces cpi_rate when set.",
    )
    reduce_general_vacancy_by_downtime: bool = Field(
        default=False,
        description="Treat general vacancy as a total-vacancy target: modeled downtime/absorption counts toward it.",
    )
    vacancy_calculation_frequency: Literal["annual", "monthly"] = Field(
        default="annual",
        description="Calculate and floor general vacancy annually or separately in each month.",
    )
    vacancy_on_gross_revenue: bool = Field(
        default=False,
        description="Apply general vacancy and credit loss to gross revenue (rent, recoveries, other income) "
                    "instead of rent only, as published DCF software does by default.",
    )
    calendar_year_recoveries: bool = Field(
        default=False,
        description="Bill recoveries on calendar years while expenses inflate on fiscal years (published DCF software).",
    )
    exit_noi_full_occupancy: bool = Field(
        default=False,
        description="Capitalize reversion NOI adjusted for full occupancy: space vacant between leases earns "
                    "market rent and recoveries, general vacancy at the stabilized rate (published DCF software).",
    )
    exit_stabilized_vacancy_pct: Decimal = Field(
        default=Decimal("0"), ge=0, le=1, description="General vacancy in the full-occupancy reversion NOI",
    )

    # Optional debt
    loan_amount: Decimal | None = Field(default=None, ge=0)
    interest_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    amortization_months: int | None = Field(default=None, ge=1)
    loan_term_months: int | None = Field(default=None, ge=1)
    io_period_months: int | None = Field(default=0, ge=0)
    loan_fees_pct: Decimal = Field(default=Decimal("0"), ge=0, lt=1)
    additional_loans: list[AdditionalLoan] = Field(
        default_factory=list,
        description="Loans besides the first (second mortgage, mezzanine); debt service, balance and fees add up",
    )

    # Acquisition / returns
    purchase_price: Decimal | None = Field(
        default=None, gt=0,
        description="Acquisition price; when set, IRR and multiples are measured against it",
    )
    acquisition_costs_pct: Decimal = Field(default=Decimal("0"), ge=0, lt=1)
    direct_cap_rate: Decimal | None = Field(
        default=None, gt=0, lt=1, description="Cap rate applied to Year 1 NOI for a direct cap value"
    )
    exit_deduct_forward_capital: bool = Field(
        default=False, description="Deduct Year N+1 TI/LC/capex from net sale proceeds"
    )

    # Marina-specific assumptions (JSON string)
    marina_assumptions_json: str | None = None
    # Seniors housing assumptions (JSON string)
    seniors_housing_assumptions_json: str | None = None
    # Self storage operating model (unit mix, street and in-place rates, churn, ECRI)
    self_storage_assumptions_json: str | None = None

    @field_validator("self_storage_assumptions_json")
    @classmethod
    def _valid_storage_model(cls, value):
        from src.schemas.property import _validate_storage_json

        return _validate_storage_json(value)

    @model_validator(mode="after")
    def validate_rate_basis(self):
        if self.cash_flow_basis != self.discount_rate_basis:
            raise ValueError(
                "cash_flow_basis and discount_rate_basis must match; convert the rate or cash flows first"
            )
        return self


class ValuationCreate(ValuationBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Base Case Q1 2025",
                "analysis_start_date_override": "2025-01-01",
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
    analysis_start_date_override: MonthStart | None = None
    analysis_period_months_override: int | None = Field(default=None, ge=12, le=360, multiple_of=12)
    basis_of_value: Literal["market_value", "investment_value", "lending_stress"] | None = None
    intended_use: str | None = Field(default=None, max_length=255)
    risk_treatment: Literal["deterministic", "scenario_weighted", "stress"] | None = None
    cash_flow_basis: Literal["nominal", "real"] | None = None
    discount_rate_basis: Literal["nominal", "real"] | None = None
    discount_rate: Decimal | None = Field(default=None, gt=0, lt=1)
    exit_cap_rate: Decimal | None = Field(default=None, gt=0, lt=1)
    exit_cap_applied_to_year: int | None = None
    exit_costs_pct: Decimal | None = Field(default=None, ge=0, lt=1)
    transfer_tax_preset: str | None = None
    transfer_tax_custom_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    apply_stabilized_gross_up: bool | None = None
    stabilized_occupancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    capital_reserves_per_unit: Decimal | None = Field(default=None, ge=0)
    capital_reserves_growth_rate: Decimal | None = Field(default=None, ge=-1, le=1)
    use_mid_year_convention: bool | None = None
    terminal_timing: Literal["end_of_period", "mid_year"] | None = None
    cpi_rate: Decimal | None = Field(default=None, ge=-1, le=1)
    cpi_schedule: list[Annotated[Decimal, Field(ge=-1, le=1)]] | None = None
    reduce_general_vacancy_by_downtime: bool | None = None
    vacancy_calculation_frequency: Literal["annual", "monthly"] | None = None
    vacancy_on_gross_revenue: bool | None = None
    calendar_year_recoveries: bool | None = None
    exit_noi_full_occupancy: bool | None = None
    exit_stabilized_vacancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    loan_amount: Decimal | None = Field(default=None, ge=0)
    interest_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    amortization_months: int | None = Field(default=None, ge=1)
    loan_term_months: int | None = Field(default=None, ge=1)
    io_period_months: int | None = Field(default=None, ge=0)
    loan_fees_pct: Decimal | None = Field(default=None, ge=0, lt=1)
    additional_loans: list[AdditionalLoan] | None = None
    purchase_price: Decimal | None = Field(default=None, gt=0)
    acquisition_costs_pct: Decimal | None = Field(default=None, ge=0, lt=1)
    direct_cap_rate: Decimal | None = Field(default=None, gt=0, lt=1)
    exit_deduct_forward_capital: bool | None = None
    marina_assumptions_json: str | None = None
    seniors_housing_assumptions_json: str | None = None
    self_storage_assumptions_json: str | None = None

    @field_validator("self_storage_assumptions_json")
    @classmethod
    def _valid_storage_model(cls, value):
        from src.schemas.property import _validate_storage_json

        return _validate_storage_json(value)


class ValuationRead(ValuationBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    status: ValuationStatus
    error_message: str | None = None
    ai_permission_mode: Literal["confirm", "always_allow"] = "confirm"
    result_npv: Decimal | None = None
    result_irr: Decimal | None = None
    result_going_in_cap_rate: Decimal | None = None
    result_exit_value: Decimal | None = None
    result_equity_multiple: Decimal | None = None
    result_levered_irr: Decimal | None = None
    result_direct_cap_value: Decimal | None = None
    last_run_at: datetime | None = None
    inputs_updated_at: datetime | None = None  # any of its inputs changed
    result_engine_version: int | None = None  # engine version its results were calculated with
    prior_valuation_id: str | None = None  # rolled forward from
    # draft | in_review | approved; anything but draft is frozen to snapshot_id
    review_status: Literal["draft", "in_review", "approved"] = "draft"
    snapshot_id: str | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def engine_outdated(self) -> bool:
        """Its results came from an older engine version; a re-run may change them."""
        return self.status == ValuationStatus.COMPLETED and src.engine.engine_outdated(self.result_engine_version)


class ReviewAction(BaseModel):
    """Submit / approve / reopen: who, and why or any note."""
    name: str = Field(min_length=1, max_length=120, description="Person taking the action")
    note: str | None = Field(default=None, max_length=4000)


class ValuationSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    valuation_id: str
    status: Literal["in_review", "approved", "reopened"]
    result_npv: Decimal | None = None
    value_date: date
    engine_version: str
    submitted_by: str
    submitted_at: datetime
    submit_note: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    approve_note: str | None = None
    reopened_by: str | None = None
    reopened_at: datetime | None = None
    reopen_reason: str | None = None


class SnapshotVerification(BaseModel):
    snapshot_id: str
    engine_version_frozen: str
    engine_version_now: str
    stored_npv: Decimal | None
    rerun_npv: Decimal | None
    matches: bool
    error: str | None = None
