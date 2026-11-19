"""Terminal value adjustments: forward free rent addback / deduction, forward TI and LC
without building capital, and selling costs on gross less the forward deductions."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.engine.dcf import calculate_terminal_value_breakdown
from src.services.valuation_service import ValuationService
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_dcf import make_annual_cfs, make_params
from tests.unit.test_growth_schedules import _flat_lease
from tests.unit.test_leasing_costs_and_loss_base import _run

D = Decimal

# Forward year: NOI 1,000,000; TI 100 + LC 50 + building capital 150; free rent 40,000
NOI, CAPITAL, LEASING, FREE_RENT = D(1_000_000), D(300), D(150), D(40_000)
GROSS = NOI / D("0.05")


def _tv(**flags):
    params = replace(make_params(exit_cap_rate=0.05, exit_costs_pct=0.02), **flags)
    return calculate_terminal_value_breakdown(
        make_annual_cfs([900_000] * 5), params, NOI, CAPITAL,
        forward_year_leasing_costs=LEASING, forward_year_free_rent=FREE_RENT,
    )


class TestBreakdown:
    def test_defaults_ignore_new_amounts(self):
        tv = _tv()
        assert tv.noi_basis == NOI
        assert tv.exit_costs_amount == GROSS * D("0.02")
        assert tv.capital_deduction_amount == 0
        assert tv.net_value == GROSS * D("0.98")

    def test_add_back_free_rent_raises_capitalized_noi(self):
        tv = _tv(exit_add_back_free_rent=True)
        gross = (NOI + FREE_RENT) / D("0.05")
        assert tv.noi_basis == NOI + FREE_RENT
        assert tv.gross_value == gross
        assert tv.net_value == gross * D("0.98")

    def test_deduct_forward_free_rent(self):
        tv = _tv(exit_deduct_forward_free_rent=True)
        assert tv.capital_deduction_amount == FREE_RENT
        assert tv.net_value == GROSS * D("0.98") - FREE_RENT

    def test_deduct_forward_leasing_costs_excludes_building_capital(self):
        tv = _tv(exit_deduct_forward_leasing_costs=True)
        assert tv.capital_deduction_amount == LEASING
        assert tv.net_value == GROSS * D("0.98") - LEASING

    def test_forward_capital_and_leasing_costs_deduct_ti_lc_once(self):
        tv = _tv(exit_deduct_forward_capital=True, exit_deduct_forward_leasing_costs=True)
        assert tv.capital_deduction_amount == CAPITAL
        assert tv.net_value == GROSS * D("0.98") - CAPITAL

    def test_costs_on_adjusted_gross_without_deductions_is_unchanged(self):
        assert _tv(exit_costs_on_adjusted_gross=True) == _tv()

    def test_costs_on_adjusted_gross_with_legacy_forward_capital(self):
        tv = _tv(exit_deduct_forward_capital=True, exit_costs_on_adjusted_gross=True)
        assert tv.exit_costs_amount == (GROSS - CAPITAL) * D("0.02")
        assert tv.net_value == (GROSS - CAPITAL) * D("0.98")

    def test_combination(self):
        tv = _tv(exit_add_back_free_rent=True, exit_deduct_forward_free_rent=True,
                 exit_deduct_forward_leasing_costs=True, exit_costs_on_adjusted_gross=True)
        gross = (NOI + FREE_RENT) / D("0.05")
        adjusted = gross - FREE_RENT - LEASING
        assert tv.capital_deduction_amount == FREE_RENT + LEASING
        assert tv.exit_costs_amount == adjusted * D("0.02")
        assert tv.net_value == adjusted * D("0.98")

    def test_add_back_does_not_apply_to_noi_override(self):
        tv = _tv(exit_add_back_free_rent=True, terminal_noi_override=D(800_000))
        assert tv.noi_basis == D(800_000)

    def test_add_back_uses_the_capitalized_year(self):
        cfs = make_annual_cfs([900_000] * 5)
        cfs[2] = replace(cfs[2], free_rent=D(-25_000))
        params = replace(make_params(exit_cap_rate=0.05, exit_cap_year=3, exit_costs_pct=0),
                         exit_add_back_free_rent=True)
        tv = calculate_terminal_value_breakdown(cfs, params, forward_year_free_rent=FREE_RENT)
        assert tv.noi_basis == D(925_000)


def _rollover_run(**params):
    # Lease ends Dec 2029; the new tenant starts July 2030 with 3 months free, TI and LC:
    # all in Year 6, the year after a 5-year hold
    market = _make_market(renewal_prob=D(0), credit_loss=D(0))
    return _run(_flat_lease(end_date=date(2029, 12, 31)), market=market, **params)


class TestEngine:
    def test_amounts_come_from_the_forward_year(self):
        fwd = _rollover_run(months=72).annual_cash_flows[5]
        assert fwd.free_rent < 0 and fwd.tenant_improvements < 0 and fwd.leasing_commissions < 0
        base = _rollover_run()
        assert base.terminal_noi_basis == fwd.net_operating_income

        added = _rollover_run(exit_add_back_free_rent=True)
        assert added.terminal_noi_basis == fwd.net_operating_income - fwd.free_rent

        deducted = _rollover_run(exit_deduct_forward_free_rent=True, exit_deduct_forward_leasing_costs=True)
        expected = -(fwd.free_rent + fwd.tenant_improvements + fwd.leasing_commissions)
        assert deducted.terminal_capital_deduction_amount == expected
        assert deducted.terminal_value == base.terminal_value - expected

    def test_deductions_survive_a_terminal_noi_override(self):
        r = _rollover_run(terminal_noi_override=D(400_000), exit_deduct_forward_leasing_costs=True)
        assert r.terminal_capital_deduction_amount > 0


@pytest.mark.parametrize("convention", [
    {"discounting_convention": "monthly"},
    {"use_mid_year_convention": True},
])
def test_sensitivity_cells_match_full_runs(convention):
    flags = dict(purchase_price=D("4000000"), exit_costs_pct=D("0.02"), exit_add_back_free_rent=True,
                 exit_deduct_forward_free_rent=True, exit_deduct_forward_leasing_costs=True,
                 exit_costs_on_adjusted_gross=True, **convention)
    base = _rollover_run(**flags)
    params = replace(_make_params(), **flags)
    rates, caps = [D("0.06"), D("0.07")], [D("0.055"), D("0.06")]
    grid = ValuationService._reprice(params, base, rates, caps)
    for i, rate in enumerate(rates):
        for j, cap in enumerate(caps):
            full = _rollover_run(**{**flags, "discount_rate": rate, "exit_cap_rate": cap})
            assert grid.values[i][j] == full.npv.quantize(D("0.01"))
            assert grid.terminal_values[j] == full.terminal_value.quantize(D("0.01"))
            assert grid.irr_by_exit_cap[j] == full.returns.unlevered_irr
