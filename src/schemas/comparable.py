from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


AmenityValue = bool | int | float | str | None


class ComparableSaleBase(BaseModel):
    external_id: str | None = Field(default=None, max_length=100)
    property_name: str = Field(min_length=1, max_length=255)
    sale_date: date
    sale_price: Decimal = Field(gt=0)
    property_type: str = Field(min_length=1, max_length=50)
    property_subtype: str | None = Field(default=None, max_length=100)
    area: Decimal = Field(gt=0)
    area_unit: str = Field(default="sf", max_length=10)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=50)
    market: str | None = Field(default=None, max_length=100)
    submarket: str | None = Field(default=None, max_length=100)
    year_built: int | None = Field(default=None, ge=1800, le=2100)
    year_renovated: int | None = Field(default=None, ge=1800, le=2100)
    occupancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    normalized_noi: Decimal | None = Field(default=None, ge=0)
    amenities: dict[str, AmenityValue] = Field(default_factory=dict)
    is_distressed: bool = False
    is_portfolio_sale: bool = False
    is_partial_interest: bool = False
    financing_terms: str | None = None
    source: str = Field(min_length=1, max_length=255)
    source_url: str | None = None
    verification_status: Literal["unverified", "partially_verified", "verified"] = "unverified"
    notes: str | None = None


class ComparableSaleCreate(ComparableSaleBase):
    pass


class ComparableSaleUpdate(BaseModel):
    external_id: str | None = Field(default=None, max_length=100)
    property_name: str | None = Field(default=None, min_length=1, max_length=255)
    sale_date: date | None = None
    sale_price: Decimal | None = Field(default=None, gt=0)
    property_type: str | None = Field(default=None, min_length=1, max_length=50)
    property_subtype: str | None = Field(default=None, max_length=100)
    area: Decimal | None = Field(default=None, gt=0)
    area_unit: str | None = Field(default=None, max_length=10)
    city: str | None = None
    state: str | None = None
    market: str | None = None
    submarket: str | None = None
    year_built: int | None = Field(default=None, ge=1800, le=2100)
    year_renovated: int | None = Field(default=None, ge=1800, le=2100)
    occupancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    normalized_noi: Decimal | None = Field(default=None, ge=0)
    amenities: dict[str, AmenityValue] | None = None
    is_distressed: bool | None = None
    is_portfolio_sale: bool | None = None
    is_partial_interest: bool | None = None
    financing_terms: str | None = None
    source: str | None = Field(default=None, min_length=1, max_length=255)
    source_url: str | None = None
    verification_status: Literal["unverified", "partially_verified", "verified"] | None = None
    notes: str | None = None


class ComparableSaleRead(ComparableSaleBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def price_per_area(self) -> Decimal:
        return self.sale_price / self.area

    @computed_field
    @property
    def going_in_cap_rate(self) -> Decimal | None:
        return self.normalized_noi / self.sale_price if self.normalized_noi is not None else None


class ComparableSelectionWrite(BaseModel):
    included: bool = True
    weight: Decimal = Field(default=Decimal("1"), ge=0)
    adjustments: dict[str, Decimal] = Field(default_factory=dict)
    rationale: str | None = None


class ComparableSelectionRead(ComparableSelectionWrite):
    model_config = ConfigDict(from_attributes=True)
    id: str
    property_id: str
    sale_id: str
    sale: ComparableSaleRead


class ManualComparableRow(BaseModel):
    sale_id: str
    property_name: str
    raw_price_per_area: Decimal
    total_adjustment_pct: Decimal
    adjusted_price_per_area: Decimal
    selected_weight: Decimal
    normalized_weight: Decimal
    indicated_value: Decimal
    warnings: list[str] = []


class ManualComparableAnalysis(BaseModel):
    rows: list[ManualComparableRow]
    weighted_price_per_area: Decimal | None
    indicated_value: Decimal | None
    low_price_per_area: Decimal | None
    high_price_per_area: Decimal | None
    warnings: list[str] = []


class StatisticalValuationRequest(BaseModel):
    as_of_date: date | None = None
    occupancy_pct: Decimal | None = Field(default=None, ge=0, le=1)
    normalized_noi: Decimal | None = Field(default=None, ge=0)
    market_only: bool = False
    include_distressed: bool = False
    minimum_observations: int = Field(default=8, ge=5, le=100)


class StatisticalValuationResult(BaseModel):
    status: Literal["ok", "insufficient_data"]
    estimated_price_per_area: Decimal | None = None
    indicated_value: Decimal | None = None
    prediction_low: Decimal | None = None
    prediction_high: Decimal | None = None
    observation_count: int
    feature_count: int = 0
    confidence: Literal["low", "moderate", "high"] = "low"
    out_of_range_features: list[str] = []
    coefficients: dict[str, float] = {}
    model_rmse_log: float | None = None
    model_mape: float | None = None
    warnings: list[str] = []


class ReconciliationRequest(BaseModel):
    valuation_id: str | None = None
    statistical_price_per_area: Decimal | None = Field(default=None, gt=0)
    weights: dict[Literal["dcf", "direct_cap", "sales_comparison", "statistical"], Decimal]


class ReconciliationResult(BaseModel):
    indications: dict[str, Decimal]
    normalized_weights: dict[str, Decimal]
    reconciled_value: Decimal
    warnings: list[str] = []
