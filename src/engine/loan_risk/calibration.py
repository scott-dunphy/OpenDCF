"""
Calibration target for the term default function: Moody's CMM expected losses.

ACLI's 2013 proposal to the NAIC (the source of the CM1-CM5 categories) ran
Moody's Commercial Mortgage Metrics on hypothetical loans over a DSC x LTV
grid and published the mean annual expected loss for 25-year amortization,
averaged over office, industrial, retail and multifamily:
https://content.naic.org/sites/default/files/committee_related_documents/committees_e_capad_lrbc_exposures_acli_proprosal.pdf
(page 15). Losses were blended over remaining maturities of 2-10 years
(weights from life insurer holdings), discounted at 5% and divided by the
average remaining maturity.

`model_annual_el` runs the same hypothetical loans through this engine so the
default function's coefficients can be fitted to the grid
(scripts/calibrate_default_model.py).

Only cells whose implied cap rate (NOI / value) is realistic are used: a cell
such as DSC 2.0 at 120% LTV implies a 20% cap rate, which CMM priced from
historical data but which this engine's cap rate process does not describe.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from src.engine.loan_risk.params import RiskParameters
from src.engine.loan_risk.simulation import CollateralInput, LoanInput, simulate

GRID_DSC = (0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0)
GRID_LTV = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2)
# Mean annual expected loss (%), rows = DSC, columns = LTV
CMM_ANNUAL_EL_PCT = (
    (0.70, 0.73, 0.76, 0.81, 0.90, 1.03, 1.22, 1.46, 1.72),
    (0.59, 0.61, 0.64, 0.69, 0.78, 0.90, 1.07, 1.28, 1.52),
    (0.43, 0.45, 0.48, 0.53, 0.60, 0.71, 0.86, 1.03, 1.21),
    (0.29, 0.30, 0.33, 0.37, 0.43, 0.52, 0.62, 0.75, 0.88),
    (0.18, 0.19, 0.21, 0.25, 0.30, 0.36, 0.43, 0.52, 0.60),
    (0.12, 0.13, 0.14, 0.17, 0.21, 0.25, 0.30, 0.35, 0.41),
    (0.08, 0.09, 0.10, 0.12, 0.15, 0.18, 0.21, 0.25, 0.28),
    (0.05, 0.06, 0.07, 0.09, 0.11, 0.13, 0.15, 0.18, 0.20),
    (0.04, 0.05, 0.05, 0.06, 0.08, 0.09, 0.11, 0.13, 0.15),
)
# Remaining maturity (years): (weight, discount factor at 5%)
MATURITY_BLEND = {2: (0.25, 0.952381), 4: (0.19, 0.907029), 6: (0.19, 0.863838), 8: (0.12, 0.822702),
                  10: (0.25, 0.783526)}

COUPON = 0.07            # roughly the life company commitment rate over the modeled period
AMORTIZATION_MONTHS = 300
VALUE = 10_000_000.0
NOI_GROWTH = 0.02
CAP_RANGE = (0.045, 0.11)


def annual_constant(rate: float = COUPON, months: int = AMORTIZATION_MONTHS) -> float:
    r = rate / 12
    return 12 * r / (1 - (1 + r) ** -months)


def target(dsc: float, ltv: float) -> float:
    return CMM_ANNUAL_EL_PCT[GRID_DSC.index(dsc)][GRID_LTV.index(ltv)] / 100


def implied_cap(dsc: float, ltv: float) -> float:
    return dsc * ltv * annual_constant()


def calibration_cells() -> list[tuple[float, float]]:
    lo, hi = CAP_RANGE
    return [(d, l) for d in GRID_DSC for l in GRID_LTV if lo <= implied_cap(d, l) <= hi]


def _loan(balance: float, months: int) -> LoanInput:
    r = COUPON / 12
    payment = balance * r / (1 - (1 + r) ** -AMORTIZATION_MONTHS)
    begin, principal = np.zeros(months), np.zeros(months)
    b = balance
    for m in range(months):
        begin[m] = b
        principal[m] = payment - b * r
        b -= principal[m]
    return LoanInput(loan_id="cal", collateral_key="cal", balance=balance, begin_balance=begin,
                     principal=principal, coupon=COUPON)


def model_annual_el(params: RiskParameters, dsc: float, ltv: float) -> float:
    """This engine's mean annual expected loss for a grid cell, blended as in the ACLI study."""
    balance = ltv * VALUE
    noi = dsc * balance * annual_constant()
    months = 12 * (max(MATURITY_BLEND) + 4)
    monthly_noi = noi / 12 * (1 + NOI_GROWTH) ** (np.arange(months) // 12)
    col = CollateralInput(key="cal", property_type="office", market="calibration", monthly_noi=monthly_noi,
                          current_value=VALUE, exit_cap_rate=noi / VALUE)
    blended, years = 0.0, 0.0
    for m, (weight, discount) in MATURITY_BLEND.items():
        res = simulate([col], [_loan(balance, 12 * m)], params)[0][0]
        blended += weight * res.expected_loss * discount
        years += weight * m
    return blended / years


def fit_error(params: RiskParameters, cells: list[tuple[float, float]]) -> float:
    """Mean squared log error against the CMM grid."""
    errors = [np.log(max(model_annual_el(params, d, l), 1e-6)) - np.log(target(d, l)) for d, l in cells]
    return float(np.mean(np.square(errors)))


def with_coefficients(params: RiskParameters, coef: tuple[float, float, float]) -> RiskParameters:
    return replace(params, default_intercept=coef[0], default_dscr_coef=coef[1], default_ltv_coef=coef[2])


# =========================================================================
# Property value history: NCREIF Property Index
# =========================================================================
# Target dispersion of the national property value index, from NCREIF NPI quarterly capital
# returns 1978Q1-2026Q2 (office, industrial, retail, residential and other types; pulled 2026-10-24),
# desmoothed for appraisal lag (Geltner, quarterly AR(1) 0.79). Each entry is the spread of the
# log change in value over the horizon, measured from the median: (5th percentile, 95th percentile).
# The desmoothed index fell 44% in 1988-92, 51% in 2007-09 and 38% in 2022-23.
NPI_VALUE_DISPERSION = {5: (-0.54, 0.32), 10: (-0.46, 0.49)}
# Property-specific value moves: standard deviation of a single property's yearly value change
# relative to its property type's national index. NCREIF's cross-section of quarterly appreciation
# within each type has a median standard deviation of about 4-5.5%, so about 9-11% a year, part of
# which is appraisal noise; 8% is used.
NPI_PROPERTY_SPECIFIC_SD = 0.08
INDEX_TYPES = ("office", "industrial", "retail", "multifamily")
INDEX_MARKETS = 8
INDEX_CAP = 0.06


def index_value_dispersion(params: RiskParameters, years: tuple[int, ...] = (5, 10)) -> dict[int, tuple[float, float]]:
    """
    Dispersion of a simulated national value index, comparable to NPI_VALUE_DISPERSION.
    The index is the average value of tape-style properties spread over four property types
    and several markets, so property-specific moves largely diversify away, as in the NPI.
    """
    from src.engine.collateral_mc import CAP, property_deviations
    from src.engine.loan_risk.simulation import _tape_noi_factor

    months = 12 * (max(years) + 1)
    total = np.zeros((params.num_paths, len(years)))
    n = 0
    for ptype in INDEX_TYPES:
        for m in range(INDEX_MARKETS):
            dev = property_deviations(params, f"index-{ptype}-{m}", ptype, f"market-{m}")
            factor = _tape_noi_factor(params, dev, months)
            for i, y in enumerate(years):
                fwd = factor[:, 12 * y:12 * y + 12].mean(axis=1)
                cap = np.maximum(params.cap_rate_floor, INDEX_CAP + dev[:, y, CAP])
                total[:, i] += fwd * INDEX_CAP / cap
            n += 1
    logv = np.log(total / n)
    out = {}
    for i, y in enumerate(years):
        med = np.median(logv[:, i])
        out[y] = (float(np.percentile(logv[:, i], 5) - med), float(np.percentile(logv[:, i], 95) - med))
    return out


def property_specific_sd(params: RiskParameters, markets: int = 12) -> float:
    """Standard deviation of a property's yearly log value change relative to its type's index."""
    from src.engine.collateral_mc import CAP, property_deviations
    from src.engine.loan_risk.simulation import _tape_noi_factor

    years = 6
    logs = []
    for m in range(markets):
        dev = property_deviations(params, f"spec-{m}", "office", f"market-{m}")
        factor = _tape_noi_factor(params, dev, 12 * (years + 1))
        cap = np.maximum(params.cap_rate_floor, INDEX_CAP + dev[:, 1:years + 1, CAP])
        fwd = np.stack([factor[:, 12 * y:12 * y + 12].mean(axis=1) for y in range(1, years + 1)], axis=1)
        logs.append(np.log(fwd * INDEX_CAP / cap))
    index = np.log(np.mean(np.exp(logs), axis=0))
    return float(np.mean([np.diff(v - index, axis=1).std() for v in logs]))


def value_fit_error(params: RiskParameters) -> float:
    """Squared error of the simulated index dispersion and property-specific moves against the NPI."""
    sim = index_value_dispersion(params, tuple(NPI_VALUE_DISPERSION))
    err = sum((s - t) ** 2 for y, tgt in NPI_VALUE_DISPERSION.items() for s, t in zip(sim[y], tgt))
    return float(err + (property_specific_sd(params) - NPI_PROPERTY_SPECIFIC_SD) ** 2)
