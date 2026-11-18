"""
Monte Carlo parameters for collateral simulation and the mortgage loan book.

The defaults are a starting point meant to be calibrated against market
history and the lender's own loss history; every value is editable on the
admin page and saved as a versioned parameter set. Rates and volatilities are
annual decimals.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

# Simulated drivers, in the order used by the volatility, persistence and correlation settings.
# Each moves year by year around the property's own assumption:
#   rent_growth   market rent growth rate (added, e.g. +0.01 = 1 point faster growth)
#   vacancy       general vacancy rate (added; credit loss moves with it)
#   renewal       renewal probability (added)
#   downtime      downtime months (multiplied by exp(deviation))
#   concessions   TI and free rent (multiplied by exp(deviation))
#   inflation     expense growth, other income growth and CPI (added)
#   cap_rate      cap rate, including the exit cap rate (added)
#   sofr          SOFR around its forward curve (added; floating rates and floating refinancing)
#   treasury_10y  10-year Treasury around its curve (added; fixed-rate refinancing)
DRIVERS = ("rent_growth", "vacancy", "renewal", "downtime", "concessions", "inflation", "cap_rate", "sofr",
           "treasury_10y")

DEFAULT_DRIVER_VOLATILITY = {
    "rent_growth": 0.020, "vacancy": 0.015, "renewal": 0.050, "downtime": 0.20, "concessions": 0.15,
    "inflation": 0.010, "cap_rate": 0.0040, "sofr": 0.0075, "treasury_10y": 0.0060,
}
# Year-to-year persistence of each deviation (0 = new every year, 1 = permanent)
DEFAULT_DRIVER_PERSISTENCE = {
    "rent_growth": 0.5, "vacancy": 0.7, "renewal": 0.5, "downtime": 0.5, "concessions": 0.6,
    "inflation": 0.6, "cap_rate": 0.85, "sofr": 0.8, "treasury_10y": 0.85,
}
# Correlation of the yearly shocks (rows/columns in DRIVERS order)
DEFAULT_DRIVER_CORRELATION = [
    #  rent   vac    renew  down   conc   infl   cap    sofr   ust10
    [1.00, -0.60, 0.40, -0.40, -0.50, 0.30, -0.40, 0.00, 0.00],   # rent_growth
    [-0.60, 1.00, -0.40, 0.50, 0.50, 0.00, 0.40, 0.00, 0.00],     # vacancy
    [0.40, -0.40, 1.00, -0.30, -0.30, 0.00, -0.20, 0.00, 0.00],   # renewal
    [-0.40, 0.50, -0.30, 1.00, 0.40, 0.00, 0.20, 0.00, 0.00],     # downtime
    [-0.50, 0.50, -0.30, 0.40, 1.00, 0.00, 0.20, 0.00, 0.00],     # concessions
    [0.30, 0.00, 0.00, 0.00, 0.00, 1.00, 0.20, 0.30, 0.40],       # inflation
    [-0.40, 0.40, -0.20, 0.20, 0.20, 0.20, 1.00, 0.30, 0.50],     # cap_rate
    [0.00, 0.00, 0.00, 0.00, 0.00, 0.30, 0.30, 1.00, 0.70],       # sofr
    [0.00, 0.00, 0.00, 0.00, 0.00, 0.40, 0.50, 0.70, 1.00],       # treasury_10y
]

# Extra yearly shock to each driver in a recession year (driver units, before recession_severity)
DEFAULT_RECESSION_SHOCK = {
    "rent_growth": -0.04, "vacancy": 0.03, "renewal": -0.08, "downtime": 0.30, "concessions": 0.25,
    "inflation": -0.01, "cap_rate": 0.0075, "sofr": -0.0100, "treasury_10y": -0.0050,
}

# Keys from earlier versions, ignored when old parameter sets are loaded
RETIRED_KEYS = {
    "noi_volatility", "default_noi_volatility", "systematic_weight", "rollover_volatility_scale",
    "cap_rate_volatility", "cap_rate_mean_reversion", "noi_cap_correlation", "index_volatility",
    "index_mean_reversion", "maturity_payoff_max_ltv", "global_weight", "term_default_mode",
    "term_default_dscr", "term_default_ltv", "term_default_quarters",
}


# Settings fitted by scripts/calibrate_default_model.py. Saved parameter sets from before the
# calibration get these refreshed (other settings are kept).
CALIBRATED_KEYS = (
    "recession_severity", "rent_level_reversion", "cap_rate_type_share", "default_intercept",
    "default_dscr_coef", "default_ltv_coef", "liquidation_cost_pct", "workout_carry_pct",
)
# Earlier calibration kept as a named alternative: scenarios widened until losses alone matched the
# Moody's CMM grid (no rent reversion or carrying costs). Wider than NCREIF history.
CMM_WIDE_PRESET_NAME = "CMM fit, wide scenarios"
CMM_WIDE_PRESET = {
    "recession_severity": 1.39, "rent_level_reversion": 0.0, "cap_rate_type_share": 0.8,
    "default_intercept": -6.60, "default_dscr_coef": -0.22, "default_ltv_coef": 0.81,
    "liquidation_cost_pct": 0.08, "workout_carry_pct": 0.0, "cap_rate_volatility": 0.0040,
}


@dataclass
class RiskParameters:
    num_paths: int = 1000
    seed: int = 1234

    # Collateral scenarios: yearly deviations follow dev[y] = persistence x dev[y-1] + volatility x shock[y],
    # with shocks correlated across drivers by driver_correlation.
    driver_volatility: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_DRIVER_VOLATILITY))
    driver_persistence: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_DRIVER_PERSISTENCE))
    driver_correlation: list[list[float]] = field(default_factory=lambda: [r[:] for r in DEFAULT_DRIVER_CORRELATION])
    # Who shares a shock: inflation and rates are economy-wide. Leasing drivers are a market shock
    # (market_share, by property type and market) plus a property-specific shock; cap rates are a
    # property-type shock (cap_rate_type_share) plus a property-specific one. global_share of each
    # market / property-type shock is national.
    global_share: float = 0.5
    market_share: float = 0.6
    cap_rate_type_share: float = 0.8
    credit_loss_vacancy_sensitivity: float = 0.25   # credit loss change per point of vacancy change
    # Recessions: an economy-wide regime. Each year a recession starts with recession_probability and
    # an ongoing one continues with recession_persistence; every recession year adds
    # recession_severity x recession_shock to each driver's deviation. The shock is centred on the
    # long-run share of recession years, so the average path is still the base case.
    recession_probability: float = 0.10
    recession_persistence: float = 0.60
    recession_severity: float = 1.39      # fitted to the CMM grid with the default coefficients
    recession_shock: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_RECESSION_SHOCK))
    # Share of the accumulated rent level deviation that rent growth closes each year: market rents
    # drift back toward their base-case level, so a downturn's rent losses are partly recovered
    rent_level_reversion: float = 0.0
    # Tape-only collateral (no property model): NOI = revenue - expenses with this expense ratio
    tape_expense_ratio: float = 0.40
    tape_base_vacancy: float = 0.05
    tape_avg_lease_years: float = 5.0   # market moves reach revenue as leases roll over this term
    cap_rate_floor: float = 0.03

    # Rate curves: [[years, rate], ...]
    index_curve: list[list[float]] = field(default_factory=lambda: [[0.0, 0.04], [30.0, 0.04]])
    treasury_curve: list[list[float]] = field(default_factory=lambda: [[0.0, 0.0425], [30.0, 0.0425]])
    index_curve_as_of: str | None = None
    # Replace the curves with today's from FRED when a run starts (needs FRED_API_KEY); off keeps
    # the saved curves, e.g. for a rate scenario
    use_live_rates: bool = True

    # Term default (Moody's CMM style): at each quarter end a path defaults with the quarterly share of
    # annual PD = logistic(intercept + dscr_coef x ln(DSCR) + ltv_coef x LTV), where DSCR is trailing-
    # 12-month NOI / annualized debt service and LTV is total debt / value on that path. Calibrated to
    # the CMM expected-loss grid in the 2013 ACLI proposal to the NAIC
    # (scripts/calibrate_default_model.py).
    # Fitted together with recession_severity (600 paths, 41 cells): typical cell within a factor of 1.4.
    default_intercept: float = -6.60
    default_dscr_coef: float = -0.22
    default_ltv_coef: float = 0.81

    # Maturity: the loan refinances if the largest new loan (LTV, DSCR, debt yield) covers it; the
    # sponsor can pay down a shortfall up to max_equity_paydown_pct of value; otherwise it extends
    # (if an option remains and its tests pass), the borrower sells if the sale repays all the
    # property's debt, or it defaults. Fixed-rate loans refinance at the
    # 10-year Treasury + refi_spread_fixed, floating-rate loans at SOFR + refi_spread.
    refi_max_ltv: float = 0.75
    refi_min_dscr: float = 1.25
    refi_min_debt_yield: float = 0.08
    refi_spread: float = 0.025
    refi_spread_fixed: float = 0.020
    refi_amortization_months: int = 360
    max_equity_paydown_pct: float = 0.15
    sale_cost_pct: float = 0.02         # costs of an ordinary sale when the borrower sells to repay at maturity
    extension_min_dscr: float = 1.10
    extension_max_ltv: float = 0.80

    # Loss given default
    liquidation_lag_months: int = 18
    liquidation_lag_by_type: dict[str, int] = field(default_factory=lambda: {"office": 24})
    liquidation_cost_pct: float = 0.08
    workout_cost_pct: float = 0.03      # legal, receiver and special servicing, % of balance at default
    # Carrying costs while the loan is resolved that NOI does not cover (deferred maintenance, leasing,
    # protective advances), % of collateral value at default per year of the liquidation lag
    workout_carry_pct: float = 0.02
    workout_noi_to_lender_pct: float = 1.0
    advance_interest: bool = True

    # Fair value: expected cash flows discounted at the index curve plus this spread
    fair_value_spread: float = 0.01

    def vol(self, driver: str) -> float:
        return self.driver_volatility.get(driver, DEFAULT_DRIVER_VOLATILITY[driver])

    def persistence(self, driver: str) -> float:
        return self.driver_persistence.get(driver, DEFAULT_DRIVER_PERSISTENCE[driver])

    def liquidation_lag(self, property_type: str) -> int:
        return self.liquidation_lag_by_type.get(property_type, self.liquidation_lag_months)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskParameters":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
