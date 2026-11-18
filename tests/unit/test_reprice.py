"""Sensitivity repricing of one self storage run matches full runs at each rate / exit cap."""
from dataclasses import replace
from decimal import Decimal

import pytest

from src.services.valuation_service import ValuationService
from tests.unit.test_self_storage import _model, _params, _run

D = Decimal


@pytest.mark.parametrize("convention", [
    {"discounting_convention": "monthly"},
    {"use_mid_year_convention": True},
])
def test_storage_cells_match_full_runs(convention):
    params = _params(purchase_price=D("3000000"), exit_deduct_forward_capital=True, **convention)
    base = _run(_model(), months=36, params=params)
    rates, caps = [D("0.08"), D("0.09"), D("0.10")], [D("0.07"), D("0.08"), D("0.09")]
    grid = ValuationService._reprice(params, base, rates, caps)
    for i, rate in enumerate(rates):
        for j, cap in enumerate(caps):
            full = _run(_model(), months=36, params=replace(params, discount_rate=rate, exit_cap_rate=cap))
            assert grid.values[i][j] == full.npv.quantize(D("0.01"))
            assert grid.terminal_values[j] == full.terminal_value.quantize(D("0.01"))
            assert grid.irr_by_exit_cap[j] == full.returns.unlevered_irr
