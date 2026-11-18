from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.schemas.common import PropertyType


class AssumptionValues(BaseModel):
    """
    Portfolio-level assumption fields. Every field is optional; only fields that
    are set override the property's own model. Rates are fractions (0.03 = 3%).
    """

    model_config = ConfigDict(extra="forbid")

    # Valuation
    discount_rate: Decimal | None = Field(default=None, gt=0, lt=1)
    exit_cap_rate: Decimal | None = Field(default=None, gt=0, lt=1)
    exit_costs_pct: Decimal | None = Field(default=None, ge=0, lt=1)
    capital_reserves_per_unit: Decimal | None = Field(
        default=None, ge=0, description="In the property's own basis: $/SF/yr or $/unit/yr"
    )
    # House-wide defaults by basis: used for properties measured in SF or in units respectively
    capital_reserves_per_sf: Decimal | None = Field(default=None, ge=0, description="$/SF/yr, SF-measured properties")
    capital_reserves_per_unit_count: Decimal | None = Field(
        default=None, ge=0, description="$/unit/yr, unit-measured properties"
    )
    management_fee_pct: Decimal | None = Field(default=None, ge=0, lt=1, description="Share of EGI")
    direct_cap_rate: Decimal | None = Field(default=None, gt=0, lt=1)
    acquisition_costs_pct: Decimal | None = Field(default=None, ge=0, lt=1)
    stabilized_occupancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    # Market leasing (applied to every space type on the property)
    market_rent_change_pct: Decimal | None = Field(
        default=None, gt=-1, description="Change to current market rent, e.g. -0.05 = 5% lower"
    )
    market_rent_growth: Decimal | None = Field(default=None, ge=-1, le=1)
    general_vacancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    credit_loss_pct: Decimal | None = Field(default=None, ge=0, le=1)
    renewal_probability: Decimal | None = Field(default=None, ge=0, le=1)
    downtime_months: Decimal | None = Field(default=None, ge=0)
    new_lease_term_months: Decimal | None = Field(default=None, ge=1)
    renewal_lease_term_months: Decimal | None = Field(default=None, ge=1)
    new_ti_per_sf: Decimal | None = Field(default=None, ge=0)
    renewal_ti_per_sf: Decimal | None = Field(default=None, ge=0)
    new_lc_pct: Decimal | None = Field(default=None, ge=0, le=1)
    renewal_lc_pct: Decimal | None = Field(default=None, ge=0, le=1)
    new_free_rent_months: Decimal | None = Field(default=None, ge=0)
    renewal_free_rent_months: Decimal | None = Field(default=None, ge=0)
    # Growth
    expense_growth: Decimal | None = Field(default=None, ge=-1, le=1)
    other_income_growth: Decimal | None = Field(default=None, ge=-1, le=1)
    cpi_rate: Decimal | None = Field(default=None, ge=-1, le=1)


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------


class PortfolioCreate(BaseModel):
    name: str = Field(max_length=255)
    description: str | None = None
    property_ids: list[str] = []


class PortfolioUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None


class PortfolioPropertySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    property_type: PropertyType
    market: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    ownership_pct: Decimal = Decimal("1.0")
    property_ownership_pct: Decimal = Decimal("1.0")
    effective_from: date | None = None
    effective_to: date | None = None
    acquisition_cost: Decimal | None = None
    commitment: Decimal | None = None
    currency: str = "USD"


class PortfolioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None = None
    properties: list[PortfolioPropertySummary] = []
    created_at: datetime
    updated_at: datetime


class PortfolioMembership(BaseModel):
    property_ids: list[str]


class PortfolioInterestUpdate(BaseModel):
    ownership_pct: Decimal = Field(ge=0, le=1)
    effective_from: date | None = None
    effective_to: date | None = None
    acquisition_cost: Decimal | None = Field(default=None, ge=0)
    commitment: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)


# ---------------------------------------------------------------------------
# Assumption profiles
# ---------------------------------------------------------------------------


class RangeBounds(BaseModel):
    """Low and high of a field across properties of the type in the market (roughly the 10th and
    90th percentiles); the base is the field's value."""
    low: Decimal
    high: Decimal


def check_ranges(values: dict, ranges: dict) -> None:
    """Each range needs a base value inside it."""
    for key, r in ranges.items():
        if key not in AssumptionValues.model_fields:
            raise ValueError(f"Unknown assumption field {key}")
        low, high = (r.low, r.high) if isinstance(r, RangeBounds) else (Decimal(str(r["low"])), Decimal(str(r["high"])))
        try:
            AssumptionValues(**{key: low})
            AssumptionValues(**{key: high})
        except ValueError as exc:
            raise ValueError(f"{key}: range ends outside the field's allowed values") from exc
        base = values.get(key)
        if base is None:
            raise ValueError(f"{key}: a range needs a base value")
        if not low <= Decimal(str(base)) <= high:
            raise ValueError(f"{key}: base {base} must lie between low {low} and high {high}")


class AssumptionScope(BaseModel):
    """Library scope and provenance shared by create, update and read."""
    cbsa_code: str | None = Field(default=None, description="Census CBSA code; matches the property's CBSA")
    state: str | None = Field(default=None, description="Two-letter state, for properties outside a CBSA")
    quality_score: int | None = Field(default=None, ge=1, le=5, description="Only for properties of this quality")
    as_of: date | None = None
    source: str | None = None

    @field_validator("cbsa_code")
    @classmethod
    def _known_cbsa(cls, v: str | None) -> str | None:
        from src.services import cbsa

        if v and cbsa.get(v.strip()) is None:
            raise ValueError(f"Unknown CBSA code {v}")
        return v.strip() if v else None

    @field_validator("state")
    @classmethod
    def _state(cls, v: str | None) -> str | None:
        from src.services import cbsa

        if not v:
            return None
        code = cbsa.state_code(v)
        if code is None:
            raise ValueError(f"Unknown state {v}")
        return code


class AssumptionProfileBase(AssumptionScope):
    name: str = Field(max_length=255)
    portfolio_id: str | None = Field(default=None, description="Null = applies house-wide")
    property_type: PropertyType | None = None
    market: str | None = Field(default=None, max_length=100)
    values: AssumptionValues
    ranges: dict[str, RangeBounds] = Field(default_factory=dict)
    comment: str | None = None

    @model_validator(mode="after")
    def _ranges(self):
        check_ranges(self.values.model_dump(exclude_none=True), self.ranges)
        return self


class AssumptionProfileCreate(AssumptionProfileBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Industrial — Dallas",
                "property_type": "industrial",
                "market": "Dallas-Fort Worth",
                "values": {"exit_cap_rate": "0.0575", "market_rent_growth": "0.035"},
            }
        }
    )


class AssumptionProfileUpdate(AssumptionScope):
    name: str | None = Field(default=None, max_length=255)
    portfolio_id: str | None = None
    property_type: PropertyType | None = None
    market: str | None = Field(default=None, max_length=100)
    values: AssumptionValues | None = None
    ranges: dict[str, RangeBounds] | None = None
    comment: str | None = None


class AssumptionProfileRead(AssumptionProfileBase):
    id: str
    cbsa_title: str | None = None
    created_at: datetime
    updated_at: datetime


class AssumptionSettingsRead(BaseModel):
    # field -> "higher" | "lower" | "none": the end of its range a quality-5 property takes
    directions: dict[str, Literal["higher", "lower", "none"]]


class AssumptionSettingsUpdate(BaseModel):
    directions: dict[str, Literal["higher", "lower", "none"]]

    @field_validator("directions")
    @classmethod
    def _known(cls, v: dict) -> dict:
        from src.engine.assumption_overrides import RESERVES_BY_BASIS

        unknown = sorted(set(v) - (set(AssumptionValues.model_fields) - set(RESERVES_BY_BASIS)))
        if unknown:
            raise ValueError(f"Unknown assumption fields: {', '.join(unknown)}")
        return v


class ResolvedRange(BaseModel):
    low: Decimal
    base: Decimal
    high: Decimal


class ResolvedAssumptionsRead(BaseModel):
    property_id: str
    property_type: str
    market: str | None
    cbsa_code: str | None = None
    cbsa_title: str | None = None
    quality_score: Decimal | None = None
    values: dict[str, Decimal]
    sources: dict[str, str]
    ranges: dict[str, ResolvedRange] = {}


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


class ScenarioOverride(BaseModel):
    property_type: PropertyType | None = None
    market: str | None = Field(default=None, max_length=100)
    mode: Literal["set", "shift"] = "shift"
    values: AssumptionValues


class PortfolioScenarioCreate(BaseModel):
    name: str = Field(max_length=255)
    description: str | None = None
    probability_pct: Decimal | None = Field(default=None, ge=0, le=1)
    overrides: list[ScenarioOverride] = []

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Downside: caps +50bp, rents -5%",
                "overrides": [
                    {
                        "mode": "shift",
                        "values": {"exit_cap_rate": "0.005", "market_rent_change_pct": "-0.05"},
                    },
                    {
                        "property_type": "office",
                        "mode": "set",
                        "values": {"renewal_probability": "0.5"},
                    },
                ],
            }
        }
    )


class PortfolioScenarioUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    probability_pct: Decimal | None = Field(default=None, ge=0, le=1)
    overrides: list[ScenarioOverride] | None = None


class PortfolioScenarioRead(BaseModel):
    id: str
    portfolio_id: str
    name: str
    description: str | None = None
    probability_pct: Decimal | None = None
    overrides: list[ScenarioOverride]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class PortfolioRunRequest(BaseModel):
    name: str | None = None
    scenario_ids: list[str] = []
    include_base: bool = True
    # Value each property from its latest valuation approved with a date of value on or before
    # this date (base = the approved value; scenarios change its frozen inputs). None = live.
    as_of: date | None = None


class PropertyRunResult(BaseModel):
    property_id: str
    property_name: str
    property_type: str
    market: str | None = None
    ownership_pct: Decimal
    ownership_effective_from: date | None = None
    ownership_effective_to: date | None = None
    acquisition_cost: Decimal | None = None
    commitment: Decimal | None = None
    currency: str = "USD"
    rerun: bool = True  # False = stored result used (scenarios not applied)
    error: str | None = None
    # As-of runs: the approved valuation used and its date of value
    valuation_id: str | None = None
    valuation_name: str | None = None
    value_date: date | None = None
    warnings: list[str] = []  # e.g. overrides the property's model has no use for
    value: Decimal | None = None  # DCF value (100%)
    share_value: Decimal | None = None  # value x ownership
    year1_noi: Decimal | None = None
    share_year1_noi: Decimal | None = None
    going_in_cap_rate: Decimal | None = None
    irr: Decimal | None = None
    levered_irr: Decimal | None = None
    terminal_value: Decimal | None = None
    direct_cap_value: Decimal | None = None
    annual_noi: dict[int, Decimal] = {}  # calendar year -> NOI (100%), summed by month
    annual_cfbd: dict[int, Decimal] = {}
    monthly_noi: dict[str, Decimal] = {}
    monthly_cfbd: dict[str, Decimal] = {}
    monthly_capital: dict[str, Decimal] = {}
    monthly_debt_service: dict[str, Decimal] = {}
    quarterly_market_value: dict[str, Decimal] = {}
    resolved_assumptions: dict[str, Decimal] = {}


class GroupRollup(BaseModel):
    key: str
    property_count: int
    share_value: Decimal
    share_year1_noi: Decimal
    implied_cap_rate: Decimal | None = None
    value_weighted_irr: Decimal | None = None


class ScenarioResult(BaseModel):
    scenario_id: str | None = None  # None = base case
    scenario_name: str
    excluded_count: int = 0  # properties with no value (no approved valuation as of the date, errors)
    probability_pct: Decimal | None = None
    total_value: Decimal
    total_share_value: Decimal
    total_share_year1_noi: Decimal
    implied_cap_rate: Decimal | None = None
    value_weighted_irr: Decimal | None = None
    portfolio_xirr: Decimal | None = None
    portfolio_xirr_status: str = "not_calculated"
    minimum_cumulative_cash: Decimal = Decimal(0)
    required_liquidity: Decimal = Decimal(0)
    concentration_hhi: Decimal | None = None
    largest_property_pct: Decimal | None = None
    portfolio_time_weighted_return: Decimal | None = None
    quarterly_time_weighted_returns: dict[str, Decimal] = {}
    risk_alerts: list[str] = []
    change_vs_base_pct: Decimal | None = None
    property_value_attribution: dict[str, Decimal] = {}
    by_property_type: list[GroupRollup] = []
    by_market: list[GroupRollup] = []
    by_type_and_market: list[GroupRollup] = []
    share_annual_noi: dict[int, Decimal] = {}
    share_annual_cfbd: dict[int, Decimal] = {}
    share_monthly_cash_flow: dict[str, Decimal] = {}
    share_monthly_noi: dict[str, Decimal] = {}
    share_monthly_capital: dict[str, Decimal] = {}
    share_monthly_debt_service: dict[str, Decimal] = {}
    properties: list[PropertyRunResult] = []


class PortfolioRunRead(BaseModel):
    id: str
    portfolio_id: str
    name: str | None = None
    as_of: date | None = None
    created_at: datetime
    scenarios: list[ScenarioResult]
    probability_weighted_value: Decimal | None = None
    probability_weighted_year1_noi: Decimal | None = None


class PortfolioRunListItem(BaseModel):
    id: str
    portfolio_id: str
    name: str | None = None
    as_of: date | None = None
    created_at: datetime
    scenario_names: list[str]


class PortfolioDisposition(BaseModel):
    property_id: str
    sale_date: date
    sale_price: Decimal | None = Field(
        default=None, gt=0, description="100% gross sale price; blank uses forecast market value"
    )
    sale_cost_pct: Decimal = Field(default=Decimal("0.02"), ge=0, lt=1)


class AllocationSensitivityRequest(BaseModel):
    scenario_id: str | None = None
    dispositions: list[PortfolioDisposition] = Field(min_length=1)


class AllocationBucket(BaseModel):
    key: str
    share_value: Decimal
    allocation_pct: Decimal


class DispositionResult(BaseModel):
    property_id: str
    property_name: str
    sale_date: date
    gross_sale_price: Decimal
    ownership_share_proceeds: Decimal
    sale_costs: Decimal
    net_share_proceeds: Decimal
    forecast_value_used: bool


class AllocationSensitivityResult(BaseModel):
    scenario_id: str | None = None
    scenario_name: str
    as_of_date: date
    beginning_share_value: Decimal
    remaining_share_value: Decimal
    net_sale_proceeds: Decimal
    portfolio_xirr_before: Decimal | None = None
    portfolio_xirr_after: Decimal | None = None
    required_liquidity_before: Decimal
    required_liquidity_after: Decimal
    concentration_hhi_before: Decimal | None = None
    concentration_hhi_after: Decimal | None = None
    largest_property_pct_before: Decimal | None = None
    largest_property_pct_after: Decimal | None = None
    by_property_type: list[AllocationBucket]
    by_market: list[AllocationBucket]
    dispositions: list[DispositionResult]
    warnings: list[str] = []
