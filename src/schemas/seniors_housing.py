from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AcuityLevel = Literal["independent_living", "assisted_living", "memory_care", "skilled_nursing"]
UnitType = Literal["studio", "one_br", "two_br", "semi_private", "private", "cottage"]
PayerType = Literal["private_pay", "medicare", "medicaid", "medicare_advantage", "insurance"]


class SHCareLevelTierInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    monthly_surcharge: Decimal = Field(ge=0)
    pct_of_residents: Decimal = Field(ge=0, le=1)


class SHUnitTypeInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    acuity: AcuityLevel
    unit_type: UnitType
    count: int = Field(ge=0)
    avg_sf: Decimal = Field(ge=0)
    monthly_base_fee: Decimal = Field(ge=0)
    second_person_fee_monthly: Decimal = Field(default=Decimal("0"), ge=0)
    second_person_pct: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    community_fee: Decimal = Field(default=Decimal("0"), ge=0)
    avg_length_of_stay_months: Decimal = Field(default=Decimal("24"), gt=0)
    stabilized_occupancy: Decimal = Field(default=Decimal("0.90"), ge=0, le=1)
    annual_turnover_rate: Decimal = Field(default=Decimal("0.40"), ge=0, le=1)
    care_level_tiers: list[SHCareLevelTierInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_care_level_mix(self) -> "SHUnitTypeInput":
        total = sum((tier.pct_of_residents for tier in self.care_level_tiers), Decimal("0"))
        if total > Decimal("1"):
            raise ValueError("care_level_tiers pct_of_residents must sum to <= 1.")
        return self


class SHSNFPayerMixInput(BaseModel):
    payer: PayerType
    pct_of_days: Decimal = Field(ge=0, le=1)
    daily_rate: Decimal = Field(ge=0)
    annual_rate_growth: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)


class SHAncillaryRevenueInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    annual_fixed: Decimal = Field(default=Decimal("0"), ge=0)
    per_occupied_unit_month: Decimal = Field(default=Decimal("0"), ge=0)
    growth_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    applies_to_acuity: list[AcuityLevel] = Field(default_factory=list)


class SHExpenseLineInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)
    annual_fixed: Decimal = Field(default=Decimal("0"), ge=0)
    per_occupied_unit_month: Decimal = Field(default=Decimal("0"), ge=0)
    pct_of_revenue: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    growth_pct: Decimal | None = Field(default=None, ge=0, le=1, description="Blank = valuation expense_growth_rate")
    is_variable: bool = True
    applies_to_acuity: list[AcuityLevel] = Field(default_factory=list)


class SHCapexInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    annual_per_unit: Decimal = Field(default=Decimal("0"), ge=0)
    annual_fixed: Decimal = Field(default=Decimal("0"), ge=0)
    growth_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)


class SHOccupancyRampInput(BaseModel):
    start_occupancy: Decimal = Field(default=Decimal("0.30"), ge=0, le=1)
    monthly_absorption_units: Decimal = Field(default=Decimal("5"), ge=0)
    stabilization_month: int | None = Field(default=None, ge=1)


class SHDebtInput(BaseModel):
    loan_amount: Decimal | None = Field(default=None, ge=0)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=1)
    amortization_months: int | None = Field(default=None, ge=1)
    term_months: int | None = Field(default=None, ge=1)
    io_period_months: int = Field(default=0, ge=0)
    minimum_dscr: Decimal = Field(default=Decimal("1.30"), ge=0)
    maximum_ltv: Decimal = Field(default=Decimal("0.65"), ge=0, le=1)


class SHValuationAssumptionsInput(BaseModel):
    hold_years: int = Field(ge=1, le=60)
    discount_rate: Decimal = Field(gt=0, lt=1)
    exit_cap_rate: Decimal = Field(gt=0, lt=1)
    exit_costs_pct: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    use_mid_year_convention: bool = False
    terminal_noi_growth_pct: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    fee_growth_rate: Decimal = Field(default=Decimal("0.04"), ge=0, le=1)
    expense_growth_rate: Decimal = Field(default=Decimal("0.035"), ge=0, le=1)
    initial_purchase_price: Decimal | None = Field(default=None, ge=0)
    levered_discount_rate: Decimal | None = Field(default=None, ge=0, lt=1)


class SHScenarioInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    occupancy_multiplier: Decimal = Field(default=Decimal("1.00"), ge=0, le=2)
    rate_multiplier: Decimal = Field(default=Decimal("1.00"), ge=0, le=3)
    opex_multiplier: Decimal = Field(default=Decimal("1.00"), ge=0, le=3)
    exit_cap_rate_shift_bps: int = 0


class SHSensitivityInput(BaseModel):
    discount_rates: list[Decimal] = Field(min_length=1)
    exit_cap_rates: list[Decimal] = Field(min_length=1)
    occupancy_multipliers: list[Decimal] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ranges(self) -> "SHSensitivityInput":
        for rate in self.discount_rates:
            if rate <= Decimal("0") or rate >= Decimal("1"):
                raise ValueError("sensitivity discount_rates values must be > 0 and < 1.")
        for cap in self.exit_cap_rates:
            if cap <= Decimal("0") or cap >= Decimal("1"):
                raise ValueError("sensitivity exit_cap_rates values must be > 0 and < 1.")
        for occ in self.occupancy_multipliers:
            if occ < Decimal("0"):
                raise ValueError("sensitivity occupancy_multipliers values must be >= 0.")
        return self


class SHValuationRunRequest(BaseModel):
    as_of_date: date
    community_name: str = Field(min_length=1, max_length=200)
    unit_types: list[SHUnitTypeInput] = Field(min_length=1)
    snf_payer_mix: list[SHSNFPayerMixInput] = Field(default_factory=list)
    ancillary_revenue: list[SHAncillaryRevenueInput] = Field(default_factory=list)
    expenses: list[SHExpenseLineInput] = Field(default_factory=list)
    capex: list[SHCapexInput] = Field(default_factory=list)
    valuation: SHValuationAssumptionsInput
    occupancy_ramp: SHOccupancyRampInput | None = None
    debt: SHDebtInput | None = None
    scenarios: list[SHScenarioInput] = Field(default_factory=list)
    sensitivity: SHSensitivityInput | None = None

    @model_validator(mode="after")
    def validate_snf_payer_mix(self) -> "SHValuationRunRequest":
        total = sum((payer.pct_of_days for payer in self.snf_payer_mix), Decimal("0"))
        if total > Decimal("1"):
            raise ValueError("snf_payer_mix pct_of_days must sum to <= 1.")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "as_of_date": "2026-01-01",
                "community_name": "Sunrise Senior Living",
                "unit_types": [
                    {
                        "name": "AL Studio",
                        "acuity": "assisted_living",
                        "unit_type": "studio",
                        "count": 40,
                        "avg_sf": "350",
                        "monthly_base_fee": "5400",
                        "second_person_fee_monthly": "1200",
                        "second_person_pct": "0.10",
                        "community_fee": "5400",
                        "avg_length_of_stay_months": "22",
                        "stabilized_occupancy": "0.88",
                        "annual_turnover_rate": "0.45",
                        "care_level_tiers": [
                            {"name": "Level 1 - Minimal", "monthly_surcharge": "500", "pct_of_residents": "0.30"},
                            {"name": "Level 2 - Moderate", "monthly_surcharge": "1200", "pct_of_residents": "0.45"},
                            {"name": "Level 3 - High", "monthly_surcharge": "2200", "pct_of_residents": "0.25"},
                        ],
                    },
                    {
                        "name": "MC Private",
                        "acuity": "memory_care",
                        "unit_type": "private",
                        "count": 24,
                        "avg_sf": "300",
                        "monthly_base_fee": "6800",
                        "community_fee": "6800",
                        "avg_length_of_stay_months": "20",
                        "stabilized_occupancy": "0.85",
                        "annual_turnover_rate": "0.40",
                    },
                ],
                "expenses": [
                    {"name": "Nursing & Caregiving", "category": "labor", "annual_fixed": "800000", "per_occupied_unit_month": "1800"},
                    {"name": "Dietary Staff", "category": "labor", "annual_fixed": "200000"},
                    {"name": "Food & Dietary Costs", "category": "food", "per_occupied_unit_month": "350"},
                    {"name": "Management Fee", "category": "management_fee", "pct_of_revenue": "0.05"},
                ],
                "capex": [
                    {"name": "Capital Reserves", "annual_per_unit": "400"},
                ],
                "valuation": {
                    "hold_years": 10,
                    "discount_rate": "0.09",
                    "exit_cap_rate": "0.075",
                    "fee_growth_rate": "0.04",
                    "expense_growth_rate": "0.035",
                    "initial_purchase_price": "22000000",
                },
            }
        }
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class SHUnitTypeAnnualDetailRead(BaseModel):
    unit_type_name: str
    acuity: str
    unit_type: str
    unit_count: int
    occupied_units: Decimal
    occupancy_pct: Decimal
    base_rent_revenue: Decimal
    care_level_revenue: Decimal
    second_person_revenue: Decimal
    community_fee_revenue: Decimal
    snf_payer_revenue: Decimal
    total_revenue: Decimal


class SHExpenseLineAnnualDetailRead(BaseModel):
    name: str
    category: str
    amount: Decimal
    per_unit_month: Decimal
    acuity_breakdown: dict[str, Decimal] = {}


class SHAncillaryLineAnnualDetailRead(BaseModel):
    name: str
    amount: Decimal


class SHCapexLineAnnualDetailRead(BaseModel):
    name: str
    amount: Decimal


class SHAnnualCashFlowRead(BaseModel):
    year: int
    base_rent_revenue: Decimal
    care_level_revenue: Decimal
    second_person_revenue: Decimal
    community_fee_revenue: Decimal
    snf_payer_revenue: Decimal
    ancillary_revenue: Decimal
    potential_gross_revenue: Decimal
    effective_gross_income: Decimal
    total_labor: Decimal
    total_food_dietary: Decimal
    total_insurance: Decimal
    total_marketing: Decimal
    total_utilities: Decimal
    total_property_tax: Decimal
    total_medical_supplies: Decimal
    management_fee: Decimal
    total_other_expenses: Decimal
    total_operating_expenses: Decimal
    noi: Decimal
    ebitdarm: Decimal
    total_capex: Decimal
    cash_flow_before_debt: Decimal
    debt_service: Decimal
    balloon_payment: Decimal
    levered_cash_flow: Decimal
    total_units: int
    occupied_units: Decimal
    avg_occupancy_pct: Decimal
    rev_por: Decimal
    rev_par: Decimal
    operating_expense_ratio: Decimal
    noi_margin: Decimal
    unit_type_detail: list[SHUnitTypeAnnualDetailRead] = []
    expense_detail: list[SHExpenseLineAnnualDetailRead] = []
    ancillary_detail: list[SHAncillaryLineAnnualDetailRead] = []
    capex_detail: list[SHCapexLineAnnualDetailRead] = []


class SHValuationResultRead(BaseModel):
    annual_cash_flows: list[SHAnnualCashFlowRead]
    terminal_noi: Decimal
    terminal_value_gross: Decimal
    terminal_value_net: Decimal
    pv_unlevered_cash_flows: Decimal
    pv_unlevered_terminal: Decimal
    npv_unlevered: Decimal
    irr_unlevered: Decimal | None
    going_in_cap_rate: Decimal | None
    pv_levered_cash_flows: Decimal
    npv_levered: Decimal
    irr_levered: Decimal | None
    equity_value: Decimal


class SHScenarioResultRead(BaseModel):
    scenario_name: str
    result: SHValuationResultRead


class SHSensitivityPointRead(BaseModel):
    discount_rate: Decimal
    exit_cap_rate: Decimal
    occupancy_multiplier: Decimal
    npv_unlevered: Decimal
    npv_levered: Decimal


class SHValuationRunResponse(BaseModel):
    valuation: SHValuationResultRead
    scenario_results: list[SHScenarioResultRead] = []
    sensitivity_points: list[SHSensitivityPointRead] = []
