from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SlipKind = Literal["wet_slip", "dry_stack", "mooring"]
UtilityServiceLevel = Literal[
    "none",
    "water_only",
    "thirty_amp",
    "fifty_amp",
    "hundred_amp",
    "metered",
]
TenureType = Literal["fee_simple", "leasehold"]


class MarinaSlipClassInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: SlipKind
    length_class: str = Field(min_length=1, max_length=100)
    utility_service_level: UtilityServiceLevel
    count: int = Field(ge=0)
    annual_contract_share: Decimal = Field(ge=0, le=1)
    seasonal_contract_share: Decimal = Field(ge=0, le=1)
    transient_share: Decimal = Field(ge=0, le=1)
    annual_contract_rate: Decimal = Field(ge=0)
    seasonal_contract_rate: Decimal = Field(ge=0)
    transient_daily_rate: Decimal = Field(ge=0)
    utility_fee_monthly: Decimal = Field(default=Decimal("0"), ge=0)
    utility_fee_transient_daily: Decimal = Field(default=Decimal("0"), ge=0)
    repair_service_revenue_per_occupied_day: Decimal = Field(default=Decimal("0"), ge=0)
    retail_fnb_revenue_per_occupied_day: Decimal = Field(default=Decimal("0"), ge=0)
    storage_fee_per_month: Decimal = Field(default=Decimal("0"), ge=0)
    launch_fee_per_transient_arrival: Decimal = Field(default=Decimal("0"), ge=0)
    avg_transient_stay_days: Decimal = Field(default=Decimal("2.0"), gt=0)
    base_annual_occupancy: Decimal = Field(default=Decimal("0.95"), ge=0, le=1)
    base_seasonal_occupancy: Decimal = Field(default=Decimal("0.70"), ge=0, le=1)
    base_transient_capture: Decimal = Field(default=Decimal("0.55"), ge=0, le=1)

    @model_validator(mode="after")
    def validate_shares(self) -> "MarinaSlipClassInput":
        total = self.annual_contract_share + self.seasonal_contract_share + self.transient_share
        if total > Decimal("1"):
            raise ValueError(
                "annual_contract_share + seasonal_contract_share + transient_share "
                "must be <= 1."
            )
        return self


class MarinaDemandInput(BaseModel):
    monthly_seasonality: list[Decimal] = Field(min_length=12, max_length=12)
    monthly_weather_shock_pct: list[Decimal] = Field(min_length=12, max_length=12)
    seasonal_active_months: list[int] = Field(default_factory=lambda: [4, 5, 6, 7, 8, 9, 10])
    annual_occupancy_growth_pct: Decimal = Field(default=Decimal("0.00"), ge=-1, le=1)
    seasonal_occupancy_growth_pct: Decimal = Field(default=Decimal("0.00"), ge=-1, le=1)
    waitlist_start_count: Decimal = Field(default=Decimal("0"), ge=0)
    waitlist_conversion_pct: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)
    waitlist_new_demand_per_year: Decimal = Field(default=Decimal("0"), ge=0)
    annual_rate_growth_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    seasonal_rate_growth_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    transient_rate_growth_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    ancillary_growth_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    transient_weather_sensitivity: Decimal = Field(default=Decimal("1.00"), ge=0, le=2)
    vacancy_collection_loss_pct: Decimal = Field(default=Decimal("0.00"), ge=0, le=1)
    management_fee_pct: Decimal = Field(default=Decimal("0.00"), ge=0, le=1)

    @model_validator(mode="after")
    def validate_months(self) -> "MarinaDemandInput":
        for month in self.seasonal_active_months:
            if month < 1 or month > 12:
                raise ValueError("seasonal_active_months must contain values between 1 and 12.")
        return self


class MarinaFuelDockInput(BaseModel):
    enabled: bool = True
    fuel_sales_per_occupied_day: Decimal = Field(default=Decimal("25"), ge=0)
    fuel_margin_pct: Decimal = Field(default=Decimal("0.22"), ge=0, le=1)
    annual_growth_pct: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)


class MarinaAdditionalRevenueLineInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    annual_fixed: Decimal = Field(ge=0)
    per_occupied_day: Decimal = Field(default=Decimal("0"), ge=0)
    growth_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)


class MarinaOperatingCostLineInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    annual_fixed: Decimal = Field(ge=0)
    per_occupied_day: Decimal = Field(default=Decimal("0"), ge=0)
    growth_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)


class MarinaCyclicalCostInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_amount: Decimal = Field(ge=0)
    first_year: int = Field(ge=1)
    every_n_years: int = Field(ge=1)
    growth_pct: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    probability_pct: Decimal = Field(default=Decimal("1.0"), ge=0, le=1)
    treat_as_capex: bool = False


class MarinaLegalTenureInput(BaseModel):
    tenure_type: TenureType = "fee_simple"
    annual_ground_lease: Decimal = Field(default=Decimal("0"), ge=0)
    ground_lease_growth_pct: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    annual_submerged_land_lease: Decimal = Field(default=Decimal("0"), ge=0)
    submerged_land_lease_growth_pct: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    annual_permit_concession_fees: Decimal = Field(default=Decimal("0"), ge=0)
    permit_growth_pct: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    remaining_lease_years: int | None = Field(default=None, ge=1)
    lease_extension_probability: Decimal = Field(default=Decimal("0.70"), ge=0, le=1)
    reversion_value_loss_pct: Decimal = Field(default=Decimal("1.00"), ge=0, le=1)
    expiry_warning_horizon_years: int = Field(default=5, ge=1)


class MarinaCapexLifecycleInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    asset_type: str = Field(min_length=1, max_length=100)
    base_amount: Decimal = Field(ge=0)
    first_year: int = Field(ge=1)
    every_n_years: int = Field(ge=1)
    growth_pct: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    deferred_maintenance_catchup_year: int | None = Field(default=None, ge=1)
    deferred_maintenance_amount: Decimal = Field(default=Decimal("0"), ge=0)


class MarinaDebtInput(BaseModel):
    loan_amount: Decimal | None = Field(default=None, ge=0)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=1)
    amortization_months: int | None = Field(default=None, ge=1)
    term_months: int | None = Field(default=None, ge=1)
    io_period_months: int = Field(default=0, ge=0)
    minimum_dscr: Decimal = Field(default=Decimal("1.30"), ge=0)
    maximum_ltv: Decimal = Field(default=Decimal("0.65"), ge=0, le=1)
    minimum_debt_yield: Decimal = Field(default=Decimal("0.09"), ge=0, le=1)


class MarinaValuationAssumptionsInput(BaseModel):
    hold_years: int = Field(ge=1, le=60)
    discount_rate: Decimal = Field(gt=0, lt=1)
    exit_cap_rate: Decimal = Field(gt=0, lt=1)
    exit_costs_pct: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    use_mid_year_convention: bool = False
    terminal_noi_growth_pct: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    dock_replacement_reserve_per_slip_year: Decimal = Field(default=Decimal("0"), ge=0)
    reserve_growth_pct: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    initial_purchase_price: Decimal | None = Field(default=None, ge=0)
    levered_discount_rate: Decimal | None = Field(default=None, ge=0, lt=1)


class MarinaScenarioInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    occupancy_multiplier: Decimal = Field(default=Decimal("1.00"), ge=0, le=2)
    rate_multiplier: Decimal = Field(default=Decimal("1.00"), ge=0, le=3)
    opex_multiplier: Decimal = Field(default=Decimal("1.00"), ge=0, le=3)
    weather_shock_additive_pct: Decimal = Field(default=Decimal("0.00"), ge=0, le=1)
    exit_cap_rate_shift_bps: int = 0


class MarinaSensitivityInput(BaseModel):
    discount_rates: list[Decimal] = Field(min_length=1)
    exit_cap_rates: list[Decimal] = Field(min_length=1)
    occupancy_multipliers: list[Decimal] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ranges(self) -> "MarinaSensitivityInput":
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


class MarinaValuationRunRequest(BaseModel):
    as_of_date: date
    slip_classes: list[MarinaSlipClassInput] = Field(min_length=1)
    demand: MarinaDemandInput
    additional_revenue_lines: list[MarinaAdditionalRevenueLineInput] = Field(default_factory=list)
    operating_cost_lines: list[MarinaOperatingCostLineInput] = Field(min_length=1)
    cyclical_costs: list[MarinaCyclicalCostInput] = Field(default_factory=list)
    legal_tenure: MarinaLegalTenureInput = Field(default_factory=MarinaLegalTenureInput)
    capex_lifecycle: list[MarinaCapexLifecycleInput] = Field(default_factory=list)
    valuation: MarinaValuationAssumptionsInput
    fuel_dock: MarinaFuelDockInput = Field(default_factory=MarinaFuelDockInput)
    debt: MarinaDebtInput | None = None
    scenarios: list[MarinaScenarioInput] = Field(default_factory=list)
    sensitivity: MarinaSensitivityInput | None = None
    include_debt_sizing: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "as_of_date": "2026-01-01",
                "slip_classes": [
                    {
                        "name": "Wet 30-45",
                        "kind": "wet_slip",
                        "length_class": "30-45 ft",
                        "utility_service_level": "fifty_amp",
                        "count": 180,
                        "annual_contract_share": "0.60",
                        "seasonal_contract_share": "0.20",
                        "transient_share": "0.20",
                        "annual_contract_rate": "7600",
                        "seasonal_contract_rate": "4200",
                        "transient_daily_rate": "58",
                    }
                ],
                "demand": {
                    "monthly_seasonality": [
                        "0.70",
                        "0.75",
                        "0.90",
                        "1.00",
                        "1.15",
                        "1.25",
                        "1.30",
                        "1.20",
                        "1.00",
                        "0.90",
                        "0.80",
                        "0.75",
                    ],
                    "monthly_weather_shock_pct": [
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                    ],
                },
                "operating_cost_lines": [{"name": "dock_labor", "annual_fixed": "620000"}],
                "valuation": {
                    "hold_years": 7,
                    "discount_rate": "0.095",
                    "exit_cap_rate": "0.0825",
                },
                "include_debt_sizing": True,
            }
        }
    )


class MarinaSlipClassRevenueRead(BaseModel):
    slip_class_name: str
    kind: str
    count: int
    annual_contract_revenue: Decimal
    seasonal_contract_revenue: Decimal
    transient_revenue: Decimal
    utility_revenue: Decimal
    repair_service_revenue: Decimal
    retail_fnb_revenue: Decimal
    storage_revenue: Decimal
    launch_fee_revenue: Decimal
    total_revenue: Decimal
    occupied_days: Decimal
    avg_occupancy_pct: Decimal


class MarinaAnnualCashFlowRead(BaseModel):
    year: int
    annual_contract_revenue: Decimal
    seasonal_contract_revenue: Decimal
    transient_revenue: Decimal
    utility_service_revenue: Decimal
    fuel_margin_revenue: Decimal
    repair_service_revenue: Decimal
    retail_fnb_revenue: Decimal
    storage_revenue: Decimal
    launch_fee_revenue: Decimal
    additional_revenue: Decimal
    potential_gross_revenue: Decimal
    vacancy_collection_loss: Decimal
    effective_gross_income: Decimal
    management_fee: Decimal
    operating_expenses: Decimal
    legal_tenure_costs: Decimal
    reserve_costs: Decimal
    cyclical_opex: Decimal
    noi: Decimal
    capex: Decimal
    cash_flow_before_debt: Decimal
    debt_service: Decimal
    balloon_payment: Decimal
    levered_cash_flow: Decimal
    avg_occupancy_pct: Decimal
    waitlist_end_count: Decimal
    slip_class_detail: list[MarinaSlipClassRevenueRead] = []


class MarinaCovenantViewYearRead(BaseModel):
    year: int
    debt_service: Decimal
    dscr: Decimal | None
    ending_loan_balance: Decimal
    ltv: Decimal | None
    debt_yield: Decimal | None


class MarinaValuationResultRead(BaseModel):
    annual_cash_flows: list[MarinaAnnualCashFlowRead]
    terminal_noi: Decimal
    terminal_value_gross: Decimal
    terminal_value_net: Decimal
    terminal_value_after_tenure_risk: Decimal
    pv_unlevered_cash_flows: Decimal
    pv_unlevered_terminal: Decimal
    npv_unlevered: Decimal
    irr_unlevered: Decimal | None
    pv_levered_cash_flows: Decimal
    npv_levered: Decimal
    irr_levered: Decimal | None
    enterprise_value: Decimal
    equity_value: Decimal
    covenants: list[MarinaCovenantViewYearRead]


class MarinaScenarioResultRead(BaseModel):
    scenario_name: str
    result: MarinaValuationResultRead


class MarinaSensitivityPointRead(BaseModel):
    discount_rate: Decimal
    exit_cap_rate: Decimal
    occupancy_multiplier: Decimal
    npv_unlevered: Decimal
    npv_levered: Decimal


class MarinaDebtSizingResultRead(BaseModel):
    recommended_loan_amount: Decimal
    max_loan_by_dscr: Decimal
    max_loan_by_ltv: Decimal
    max_loan_by_debt_yield: Decimal
    binding_constraint: str


class MarinaValuationRunResponse(BaseModel):
    valuation: MarinaValuationResultRead
    scenario_results: list[MarinaScenarioResultRead] = []
    sensitivity_points: list[MarinaSensitivityPointRead] = []
    debt_sizing: MarinaDebtSizingResultRead | None = None
