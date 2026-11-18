"""
Calibrate the collateral scenarios and the term default function (Nelder-Mead).

1. Values: recession severity, rent level reversion and cap rate volatility are
   fitted so the simulated national value index spreads like the desmoothed
   NCREIF Property Index over 5 and 10 years.
2. Losses: with those scenarios fixed, the default coefficients, the distressed
   sale discount (liquidation_cost_pct) and the workout carrying cost are fitted
   to Moody's CMM mean annual expected loss grid (mean squared log error).

Prints the fitted values and the comparisons; copy the values into
RiskParameters' defaults.

    python scripts/calibrate_default_model.py [num_paths]
"""
import json
import sys
from dataclasses import replace

import numpy as np

from src.engine.loan_risk.calibration import (
    NPI_PROPERTY_SPECIFIC_SD,
    NPI_VALUE_DISPERSION,
    calibration_cells,
    fit_error,
    index_value_dispersion,
    model_annual_el,
    property_specific_sd,
    target,
    value_fit_error,
)
from src.engine.loan_risk.params import RiskParameters

DEFAULT_NAMES = ("default_intercept", "default_dscr_coef", "default_ltv_coef", "liquidation_cost_pct",
                 "workout_carry_pct")


def value_params(base: RiskParameters, x: np.ndarray) -> RiskParameters:
    vol = dict(base.driver_volatility, cap_rate=float(x[2]))
    return replace(base, recession_severity=float(x[0]), rent_level_reversion=float(x[1]), driver_volatility=vol,
                   cap_rate_type_share=float(x[3]))


def value_objective(base: RiskParameters, x: np.ndarray) -> float:
    if x[0] < 0 or not 0 <= x[1] <= 1 or x[2] < 0 or not 0 <= x[3] <= 1:
        return 1e6
    return value_fit_error(value_params(base, x))


def default_params(base: RiskParameters, x: np.ndarray) -> RiskParameters:
    return replace(base, **dict(zip(DEFAULT_NAMES, map(float, x))))


def default_objective(base: RiskParameters, cells, x: np.ndarray) -> float:
    if x[1] > 0 or x[2] < 0 or not 0 <= x[3] <= 0.5 or not 0 <= x[4] <= 0.15:   # DSCR lowers PD, LTV raises it
        return 1e6
    return fit_error(default_params(base, x), cells)


def nelder_mead(f, x0, step, iters=120, tol=1e-4):
    pts = [np.array(x0, float)] + [np.array(x0, float) + np.eye(len(x0))[i] * step[i] for i in range(len(x0))]
    vals = [f(p) for p in pts]
    for it in range(iters):
        order = np.argsort(vals)
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        print(f"iter {it:3d}  error {vals[0]:.4f}  {np.round(pts[0], 3).tolist()}", flush=True)
        if vals[-1] - vals[0] < tol:
            break
        centroid = np.mean(pts[:-1], axis=0)
        reflected = centroid + (centroid - pts[-1])
        fr = f(reflected)
        if fr < vals[0]:
            expanded = centroid + 2 * (centroid - pts[-1])
            fe = f(expanded)
            pts[-1], vals[-1] = (expanded, fe) if fe < fr else (reflected, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = reflected, fr
        else:
            contracted = centroid + 0.5 * (pts[-1] - centroid)
            fc = f(contracted)
            if fc < vals[-1]:
                pts[-1], vals[-1] = contracted, fc
            else:
                pts = [pts[0] + 0.5 * (p - pts[0]) for p in pts]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
    best = int(np.argmin(vals))
    return pts[best], vals[best]


def main() -> None:
    paths = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    base = RiskParameters(num_paths=paths)

    x, err = nelder_mead(lambda x: value_objective(replace(base, num_paths=4000), x),
                         [1.27, 0.8, 0.0068, 0.73], [0.2, 0.1, 0.001, 0.1])
    base = value_params(base, x)
    print(json.dumps({"recession_severity": float(x[0]), "rent_level_reversion": float(x[1]),
                      "cap_rate_volatility": float(x[2]), "cap_rate_type_share": float(x[3]), "error": err}, indent=2))
    print(f"property-specific yearly sd: NPI {NPI_PROPERTY_SPECIFIC_SD:.3f}  model "
          f"{property_specific_sd(replace(base, num_paths=4000)):.3f}")
    sim = index_value_dispersion(replace(base, num_paths=4000))
    for y, (lo, hi) in NPI_VALUE_DISPERSION.items():
        print(f"{y:2d}y  NPI p5 {lo:+.2f} p95 {hi:+.2f}   model p5 {sim[y][0]:+.2f} p95 {sim[y][1]:+.2f}")

    cells = calibration_cells()
    x, err = nelder_mead(lambda x: default_objective(base, cells, x),
                         [-1.6, -6.5, 5.2, 0.15, 0.03], [1.0, 1.0, 1.0, 0.05, 0.02], iters=200)
    fitted = default_params(base, x)
    print(json.dumps({"fitted": dict(zip(DEFAULT_NAMES, map(float, x))), "error": err, "paths": paths}, indent=2))
    print("DSC   LTV   CMM %   model %")
    for d, l in cells:
        print(f"{d:4.1f} {l:5.0%} {100 * target(d, l):6.2f}  {100 * model_annual_el(fitted, d, l):7.3f}")


if __name__ == "__main__":
    main()
