"""
Collateral Monte Carlo: run the full property valuation on every simulated path.

Scenario drivers (see loan_risk.params.DRIVERS) get yearly deviations from the
property's own assumptions:

    dev[y] = persistence x dev[y-1] + volatility x shock[y],   dev[0] = 0

Shocks are correlated across drivers (driver_correlation) and shared across
properties in layers, so properties in the same market move together:

- inflation, SOFR, 10-year Treasury: one economy-wide shock per path
- leasing drivers: sqrt(market_share) x market shock + sqrt(1 - market_share) x property shock,
  where a market shock (property type and market) is itself
  sqrt(global_share) x national shock + sqrt(1 - global_share) x local shock
- cap rate: the same, with a property-type shock and cap_rate_type_share

Recessions are an economy-wide regime (see RiskParameters): in a recession
year every driver takes an extra shock (rents and renewals down, vacancy,
concessions, downtime and cap rates up, rates down), centred so the average
driver path is still the base case. Mean value is not the base value: value is
convex in the cap rate, so summaries report mean value against base. Recession
years are the same for every property on a path, and the first year is drawn
from the long-run recession share.

Every draw comes from a random stream named by (seed, layer), and every path
draws MAX_YEARS years, so a property's paths do not depend on which other
properties are simulated or on the horizon: the national and market shocks on
path k are the same for every property.

`path_case` turns one path into ordinary engine inputs (year-by-year rent
growth, vacancy, credit loss, renewal, downtime, expense / other income / CPI
growth, scaled TI and free rent, and the exit cap rate) and `run_paths` values
them with the normal engine, so each path is a complete valuation.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

import numpy as np

from src.engine.growth import rate_for_year
from src.engine.loan_risk.params import DRIVERS, RiskParameters
from src.engine.property_cashflow import run_valuation
from src.engine.types import (
    RecoveryPoolInput,
    CapitalProjectInput,
    ExpenseInput,
    LeaseInput,
    MarketAssumptions,
    OtherIncomeInput,
    SuiteInput,
    ValuationParams,
)

MAX_YEARS = 40
IDX = {d: i for i, d in enumerate(DRIVERS)}
LEASING = [IDX[d] for d in ("rent_growth", "vacancy", "renewal", "downtime", "concessions")]
MACRO = [IDX[d] for d in ("inflation", "sofr", "treasury_10y")]
CAP = IDX["cap_rate"]


# =========================================================================
# Scenario generation
# =========================================================================

def _rng(seed: int, label: str) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(label.encode())])


def correlation_factor(params: RiskParameters) -> np.ndarray:
    """Cholesky factor of the driver correlation matrix (raises if it is not positive definite)."""
    c = np.asarray(params.driver_correlation, dtype=float)
    if c.shape != (len(DRIVERS), len(DRIVERS)):
        raise ValueError(f"driver_correlation must be {len(DRIVERS)} x {len(DRIVERS)}")
    return np.linalg.cholesky(c)


def _layer(params: RiskParameters, chol: np.ndarray, label: str) -> np.ndarray:
    """Correlated standard normal shocks for one layer: paths x MAX_YEARS x drivers."""
    z = _rng(params.seed, label).standard_normal((params.num_paths, MAX_YEARS, len(DRIVERS)))
    return z @ chol.T


def driver_shocks(params: RiskParameters, property_key: str, property_type: str, market: str | None) -> np.ndarray:
    """Combined yearly shocks for one property (paths x MAX_YEARS x drivers), unit variance."""
    chol = correlation_factor(params)
    national = _layer(params, chol, "national")
    by_type = _layer(params, chol, f"type:{property_type}")
    by_market = _layer(params, chol, f"market:{property_type}|{(market or '').strip().lower()}")
    own = _layer(params, chol, f"property:{property_key}")
    g, m, c = params.global_share, params.market_share, params.cap_rate_type_share
    z = np.empty_like(own)
    z[..., LEASING] = (np.sqrt(m) * (np.sqrt(g) * national + np.sqrt(1 - g) * by_market)
                       + np.sqrt(1 - m) * own)[..., LEASING]
    z[..., CAP] = (np.sqrt(c) * (np.sqrt(g) * national + np.sqrt(1 - g) * by_type) + np.sqrt(1 - c) * own)[..., CAP]
    z[..., MACRO] = national[..., MACRO]
    return z


def recession_years(params: RiskParameters) -> np.ndarray:
    """Economy-wide recession indicator, paths x MAX_YEARS (1 = recession year); today is not one."""
    u = _rng(params.seed, "recession").random((params.num_paths, MAX_YEARS))
    state = np.zeros((params.num_paths, MAX_YEARS))
    prev = u[:, 0] < recession_share(params)          # first year drawn from the long-run share
    state[:, 0] = prev
    for y in range(1, MAX_YEARS):
        prev = np.where(prev, u[:, y] < params.recession_persistence, u[:, y] < params.recession_probability)
        state[:, y] = prev
    return state


def recession_share(params: RiskParameters) -> float:
    """Long-run share of years in recession."""
    q, s = params.recession_probability, params.recession_persistence
    return q / (1 - s + q) if (1 - s + q) > 0 else 0.0


def deviations(params: RiskParameters, shocks: np.ndarray) -> np.ndarray:
    """Yearly deviations, paths x (MAX_YEARS + 1) x drivers; index 0 is today (zero)."""
    vol = np.array([params.vol(d) for d in DRIVERS])
    phi = np.array([params.persistence(d) for d in DRIVERS])
    jump = params.recession_severity * np.array([params.recession_shock.get(d, 0.0) for d in DRIVERS])
    regime = recession_years(params) - recession_share(params)          # centred: mean path unchanged
    dev = np.zeros((shocks.shape[0], MAX_YEARS + 1, len(DRIVERS)))
    rg = IDX["rent_growth"]
    rent_gap = np.zeros(shocks.shape[0])          # cumulative rent level deviation
    for y in range(1, MAX_YEARS + 1):
        dev[:, y] = phi * dev[:, y - 1] + vol * shocks[:, y - 1] + jump * regime[:, y - 1, None]
        dev[:, y, rg] -= params.rent_level_reversion * rent_gap
        rent_gap += dev[:, y, rg]
    return dev


def property_deviations(params: RiskParameters, property_key: str, property_type: str,
                        market: str | None) -> np.ndarray:
    return deviations(params, driver_shocks(params, property_key, property_type, market))


def monthly(dev_annual: np.ndarray, months: int) -> np.ndarray:
    """Linear interpolation of yearly values (paths x years+1) to months 0..months."""
    x = np.arange(months + 1) / 12.0
    xp = np.arange(dev_annual.shape[1])
    return np.stack([np.interp(x, xp, row) for row in dev_annual])


# =========================================================================
# One path -> engine inputs
# =========================================================================

@dataclass(frozen=True)
class EngineCase:
    """Engine inputs for one property without database rows (picklable for worker processes)."""
    analysis_start: date
    analysis_period_months: int
    fiscal_year_end_month: int
    property_type: str
    suites: list[SuiteInput]
    leases: list[LeaseInput]
    market: dict[str, MarketAssumptions]
    expenses: list[ExpenseInput]
    params: ValuationParams
    capital_projects: list[CapitalProjectInput]
    other_income: list[OtherIncomeInput]
    cpi_assumption: Decimal = Decimal("0.025")
    cpi_schedule: tuple[Decimal, ...] = ()
    recovery_pools: tuple[RecoveryPoolInput, ...] = ()

    @property
    def years(self) -> int:
        return -(-self.analysis_period_months // 12)

    def run(self, include_monthly: bool = False):
        return run_valuation(
            property_start_date=self.analysis_start,
            analysis_period_months=self.analysis_period_months,
            fiscal_year_end_month=self.fiscal_year_end_month,
            suites=self.suites,
            leases=self.leases,
            market_assumptions=self.market,
            expenses=self.expenses,
            params=self.params,
            property_type=self.property_type,
            capital_projects=self.capital_projects,
            other_income_items=self.other_income,
            cpi_assumption=self.cpi_assumption,
            cpi_schedule=self.cpi_schedule,
            include_monthly=include_monthly,
            recovery_pools=self.recovery_pools,
        )


def _d(x: float) -> Decimal:
    return Decimal(f"{x:.6f}")


def _shifted(rate: Decimal, schedule: tuple, devs: np.ndarray, n: int, lo: float = -1.0, hi: float = 1.0) -> tuple:
    """Year-by-year values for years 1..n: the base value for each year plus that year's deviation."""
    return tuple(_d(min(hi, max(lo, float(rate_for_year(rate, schedule, y)) + devs[y]))) for y in range(1, n + 1))


def path_case(case: EngineCase, dev: np.ndarray, params: RiskParameters) -> EngineCase:
    """Engine inputs for one path. `dev` is (MAX_YEARS + 1) x drivers for this path."""
    n = min(case.years + 2, MAX_YEARS)   # analysis years plus the forward year used for the exit value
    rg, vac, ren = dev[:, IDX["rent_growth"]], dev[:, IDX["vacancy"]], dev[:, IDX["renewal"]]
    down, infl = dev[:, IDX["downtime"]], dev[:, IDX["inflation"]]
    conc = float(np.exp(dev[1:case.years + 1, IDX["concessions"]].mean()))
    credit = vac * params.credit_loss_vacancy_sensitivity

    market = {}
    for key, m in case.market.items():
        market[key] = replace(
            m,
            rent_growth_schedule=_shifted(m.rent_growth_rate, m.rent_growth_schedule, rg, n),
            general_vacancy_schedule=_shifted(m.general_vacancy_pct, m.general_vacancy_schedule, vac, n, 0.0, 0.95),
            credit_loss_schedule=_shifted(m.credit_loss_pct, m.credit_loss_schedule, credit, n, 0.0, 0.5),
            renewal_probability_schedule=_shifted(m.renewal_probability, m.renewal_probability_schedule, ren, n,
                                                  0.0, 1.0),
            downtime_schedule=tuple(
                max(0, round(float(rate_for_year(m.downtime_months, m.downtime_schedule, y)) * float(np.exp(down[y]))))
                for y in range(1, n + 1)
            ),
            new_ti_per_sf=_d(float(m.new_ti_per_sf) * conc),
            renewal_ti_per_sf=_d(float(m.renewal_ti_per_sf) * conc),
            new_free_rent_months=max(0, round(m.new_free_rent_months * conc)),
            renewal_free_rent_months=max(0, round(m.renewal_free_rent_months * conc)),
            new_free_rent_schedule=tuple(_d(max(0.0, float(v) * conc)) for v in m.new_free_rent_schedule),
            renewal_free_rent_schedule=tuple(_d(max(0.0, float(v) * conc)) for v in m.renewal_free_rent_schedule),
        )
    expenses = [
        e if e.is_pct_of_egi else replace(e, growth_schedule=_shifted(e.growth_rate, e.growth_schedule, infl, n))
        for e in case.expenses
    ]
    other_income = [
        replace(o, growth_schedule=_shifted(o.growth_rate, o.growth_schedule, infl, n)) for o in case.other_income
    ]
    cpi_schedule = _shifted(case.cpi_assumption, case.cpi_schedule, infl, n)
    vp = case.params
    exit_cap = max(params.cap_rate_floor, float(vp.exit_cap_rate) + dev[min(case.years, MAX_YEARS), CAP])
    return replace(
        case, market=market, expenses=expenses, other_income=other_income, cpi_schedule=cpi_schedule,
        params=replace(vp, exit_cap_rate=_d(exit_cap)),
    )


# =========================================================================
# Valuing paths (runs in worker processes)
# =========================================================================

@dataclass
class PathResults:
    npv: np.ndarray                 # value today on each path
    irr: np.ndarray                 # unlevered IRR (nan without a purchase price)
    exit_cap: np.ndarray
    annual_noi: np.ndarray          # paths x analysis years
    monthly_noi: np.ndarray | None  # paths x months (when requested)


def run_paths(case: EngineCase, devs: np.ndarray, params: RiskParameters, include_monthly: bool) -> PathResults:
    """Value each path (devs: paths x (MAX_YEARS + 1) x drivers) with the full engine."""
    n = devs.shape[0]
    npv = np.zeros(n)
    irr = np.full(n, np.nan)
    exit_cap = np.zeros(n)
    annual = np.zeros((n, case.years), dtype=np.float64)
    monthly_noi = np.zeros((n, case.analysis_period_months), dtype=np.float32) if include_monthly else None
    for i in range(n):
        pc = path_case(case, devs[i], params)
        r = pc.run(include_monthly)
        npv[i] = float(r.npv)
        if r.irr is not None and case.params.purchase_price:   # without a price the IRR is the discount rate
            irr[i] = float(r.irr)
        exit_cap[i] = float(pc.params.exit_cap_rate)
        noi = [float(cf.net_operating_income) for cf in r.annual_cash_flows][: case.years]
        annual[i, : len(noi)] = noi
        if include_monthly:
            m = [float(cf.net_operating_income) for cf in r.monthly_cash_flows][: case.analysis_period_months]
            monthly_noi[i, : len(m)] = m
    return PathResults(npv=npv, irr=irr, exit_cap=exit_cap, annual_noi=annual, monthly_noi=monthly_noi)


def run_paths_chunk(case: EngineCase, devs: np.ndarray, params_dict: dict, include_monthly: bool) -> PathResults:
    """Process-pool entry point."""
    return run_paths(case, devs, RiskParameters.from_dict(params_dict), include_monthly)
