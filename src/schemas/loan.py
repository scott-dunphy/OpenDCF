from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.engine.loan_risk.params import DRIVERS, RETIRED_KEYS, RiskParameters

DelinquencyStatus = Literal["current", "30", "60", "90_plus", "foreclosure", "reo"]


class MortgageLoanBase(BaseModel):
    property_id: str
    external_id: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=255)
    portfolio_id: str | None = None
    lien_position: int = Field(default=1, ge=1, le=9)
    sponsor: str | None = Field(default=None, max_length=255)
    recourse: bool = False

    origination_date: date
    original_balance: Decimal = Field(gt=0)
    maturity_date: date
    rate_type: Literal["fixed", "floating"] = "fixed"
    coupon: Decimal | None = Field(default=None, ge=0, lt=1)
    index_name: str | None = Field(default=None, max_length=30)
    spread: Decimal | None = Field(default=None, ge=-1, lt=1)
    index_floor: Decimal | None = Field(default=None, ge=0, lt=1)
    index_cap: Decimal | None = Field(default=None, ge=0, lt=1)
    amortization_months: int | None = Field(default=None, ge=0, le=600)
    io_months: int = Field(default=0, ge=0, le=600)
    extension_count: int = Field(default=0, ge=0, le=5)
    extension_months: int = Field(default=0, ge=0, le=60)

    reported_balance: Decimal | None = Field(default=None, ge=0)
    balance_as_of_date: date | None = None
    delinquency_status: DelinquencyStatus = "current"

    origination_value: Decimal | None = Field(default=None, ge=0)
    origination_noi: Decimal | None = None

    tape_noi: Decimal | None = None
    tape_value: Decimal | None = Field(default=None, ge=0)
    tape_value_date: date | None = None
    tape_occupancy: Decimal | None = Field(default=None, ge=0, le=1)
    tape_noi_growth: Decimal | None = Field(default=None, gt=-1, lt=1)
    tape_exit_cap_rate: Decimal | None = Field(default=None, gt=0, lt=1)

    comment: str | None = None


def _check_terms(m: Any) -> None:
    if m.maturity_date <= m.origination_date:
        raise ValueError("maturity_date must be after origination_date")
    if m.rate_type == "fixed" and m.coupon is None:
        raise ValueError("Fixed-rate loans need a coupon")
    if m.rate_type == "floating" and m.spread is None:
        raise ValueError("Floating-rate loans need a spread")


class MortgageLoanCreate(MortgageLoanBase):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "property_id": "<property id>",
            "external_id": "LN-1001",
            "origination_date": "2021-06-15",
            "original_balance": "25000000",
            "maturity_date": "2031-07-01",
            "rate_type": "fixed",
            "coupon": "0.0425",
            "amortization_months": 360,
            "io_months": 36,
            "reported_balance": "24650000",
            "balance_as_of_date": "2025-09-30",
        }
    })

    @model_validator(mode="after")
    def _validate(self) -> "MortgageLoanCreate":
        _check_terms(self)
        return self


class MortgageLoanUpdate(BaseModel):
    """Partial update; the merged loan is re-validated by the API."""
    model_config = ConfigDict(extra="forbid")

    property_id: str | None = None
    external_id: str | None = None
    name: str | None = None
    portfolio_id: str | None = None
    lien_position: int | None = Field(default=None, ge=1, le=9)
    sponsor: str | None = None
    recourse: bool | None = None
    origination_date: date | None = None
    original_balance: Decimal | None = Field(default=None, gt=0)
    maturity_date: date | None = None
    rate_type: Literal["fixed", "floating"] | None = None
    coupon: Decimal | None = None
    index_name: str | None = None
    spread: Decimal | None = None
    index_floor: Decimal | None = None
    index_cap: Decimal | None = None
    amortization_months: int | None = None
    io_months: int | None = None
    extension_count: int | None = None
    extension_months: int | None = None
    reported_balance: Decimal | None = None
    balance_as_of_date: date | None = None
    delinquency_status: DelinquencyStatus | None = None
    origination_value: Decimal | None = None
    origination_noi: Decimal | None = None
    tape_noi: Decimal | None = None
    tape_value: Decimal | None = None
    tape_value_date: date | None = None
    tape_occupancy: Decimal | None = None
    tape_noi_growth: Decimal | None = None
    tape_exit_cap_rate: Decimal | None = None
    comment: str | None = None


class MortgageLoanRead(MortgageLoanBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class LoanScheduleRow(BaseModel):
    period: int
    payment_date: date
    beginning_balance: Decimal
    interest: Decimal
    principal: Decimal
    balloon: Decimal
    ending_balance: Decimal


class LoanScheduleRead(BaseModel):
    loan_id: str
    as_of_date: date
    payments_made: int
    scheduled_balance: Decimal
    balance: Decimal
    balance_difference_pct: Decimal
    rate: Decimal
    remaining_term_months: int
    remaining_io_months: int
    remaining_amortization_months: int
    wal_years: Decimal
    warnings: list[str]
    rows: list[LoanScheduleRow]


# --- Risk parameter sets ----------------------------------------------------------

def _validate_params(v: dict[str, Any]) -> dict[str, Any]:
    """Reject unknown keys and fill omitted ones with the engine defaults (keys from older versions are dropped)."""
    v = {k: x for k, x in v.items() if k not in RETIRED_KEYS}
    known = set(RiskParameters().to_dict())
    unknown = set(v) - known
    if unknown:
        raise ValueError(f"Unknown parameters: {', '.join(sorted(unknown))}")
    merged = {**RiskParameters().to_dict(), **v}
    if not 100 <= int(merged["num_paths"]) <= 50000:
        raise ValueError("num_paths must be between 100 and 50,000")
    if set(merged["driver_volatility"]) - set(DRIVERS) or set(merged["driver_persistence"]) - set(DRIVERS):
        raise ValueError(f"Driver settings must use: {', '.join(DRIVERS)}")
    corr = np.asarray(merged["driver_correlation"], dtype=float)
    if corr.shape != (len(DRIVERS), len(DRIVERS)) or not np.allclose(corr, corr.T) \
            or not np.allclose(np.diag(corr), 1) or np.abs(corr).max() > 1:
        raise ValueError(f"driver_correlation must be a symmetric {len(DRIVERS)} x {len(DRIVERS)} matrix "
                         "with ones on the diagonal and entries between -1 and 1")
    if np.linalg.eigvalsh(corr).min() <= 1e-8:
        raise ValueError("driver_correlation is not a valid correlation matrix (not positive definite); "
                         "some of the correlations contradict each other")
    if set(merged["recession_shock"]) - set(DRIVERS):
        raise ValueError(f"recession_shock must use: {', '.join(DRIVERS)}")
    if float(merged["recession_severity"]) < 0:
        raise ValueError("recession_severity cannot be negative")
    for k in ("global_share", "market_share", "cap_rate_type_share", "recession_probability",
              "recession_persistence", "rent_level_reversion"):
        if not 0 <= float(merged[k]) <= 1:
            raise ValueError(f"{k} must be between 0 and 1")
    return merged


class RiskParameterSetBase(BaseModel):
    name: str = Field(max_length=255)
    comment: str | None = None
    params: dict[str, Any] = {}

    @field_validator("params")
    @classmethod
    def _params(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_params(v)


class RiskParameterSetCreate(RiskParameterSetBase):
    is_default: bool = False


class RiskParameterSetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    comment: str | None = None
    params: dict[str, Any] | None = None

    @field_validator("params")
    @classmethod
    def _params(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if v is None else _validate_params(v)


class RiskParameterSetRead(BaseModel):
    id: str
    name: str
    version: int
    is_default: bool
    comment: str | None
    params: dict[str, Any]
    created_at: datetime
    updated_at: datetime


# --- Runs -----------------------------------------------------------------------------

class LoanRiskRunCreate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    as_of_date: date
    portfolio_id: str | None = None
    parameter_set_id: str | None = Field(default=None, description="Defaults to the default parameter set")


class LoanRiskRunListItem(BaseModel):
    id: str
    name: str | None
    as_of_date: date
    portfolio_id: str | None
    parameter_set_id: str | None
    parameter_set_version: int | None
    status: str
    progress: Decimal
    error_message: str | None
    created_at: datetime
    loan_count: int | None = None
    total_balance: float | None = None
    expected_loss: float | None = None


class LoanRiskRunRead(LoanRiskRunListItem):
    params: dict[str, Any]
    results: dict[str, Any] | None = None


# --- Audit -------------------------------------------------------------------------------

class RiskParameterSetVersionRead(BaseModel):
    version: int
    name: str
    comment: str | None
    params: dict[str, Any]
    created_at: datetime


class AuditLogRead(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    property_id: str | None
    action: str
    changes: dict[str, list[Any]]
    source: str | None
    created_at: datetime
