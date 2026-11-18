"""The default parameters stay calibrated to Moody's CMM expected-loss grid (ACLI 2013 proposal)."""
import numpy as np

from src.engine.loan_risk.calibration import calibration_cells, fit_error, model_annual_el, target
from src.engine.loan_risk.params import RiskParameters


def test_defaults_reproduce_the_cmm_grid():
    params = RiskParameters(num_paths=300)
    # Whole calibration band: mean squared log error 0.11 when fitted (typical cell within a factor of 1.4)
    assert fit_error(params, calibration_cells()) < 0.2
    for dsc, ltv in [(1.4, 0.6), (1.0, 1.0), (0.8, 0.9), (2.0, 0.4)]:
        ratio = model_annual_el(params, dsc, ltv) / target(dsc, ltv)
        assert 0.5 < ratio < 2.0, (dsc, ltv, ratio)
    # Losses fall as coverage improves and rise with leverage
    assert model_annual_el(params, 0.8, 0.8) > model_annual_el(params, 1.4, 0.8)
    assert model_annual_el(params, 1.2, 0.9) > model_annual_el(params, 1.2, 0.5)
    assert np.isfinite(fit_error(params, [(1.2, 0.6)]))
