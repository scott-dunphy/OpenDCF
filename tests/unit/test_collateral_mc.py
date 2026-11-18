"""Collateral Monte Carlo: scenario generation and full-engine valuation of each path."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from src.engine.collateral_mc import (
    CAP,
    IDX,
    MAX_YEARS,
    EngineCase,
    deviations,
    driver_shocks,
    monthly,
    path_case,
    property_deviations,
    recession_share,
    recession_years,
    run_paths,
)
from src.engine.loan_risk.params import DRIVERS, RiskParameters
from src.engine.types import SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_growth_schedules import _expense, _flat_lease

D = Decimal


def _case(**kw) -> EngineCase:
    suites = [SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office"),
              SuiteInput(suite_id="S2", suite_name="200", area=D("5000"), space_type="office")]
    leases = [_flat_lease(end_date=date(2027, 6, 30)),
              _flat_lease(lease_id="L2", suite_id="S2", area=D("5000"), end_date=date(2029, 12, 31))]
    base = dict(
        analysis_start=date(2025, 1, 1), analysis_period_months=120, fiscal_year_end_month=12,
        property_type="office", suites=suites, leases=leases, market={"office": _make_market()},
        expenses=[_expense()], params=_make_params(), capital_projects=[], other_income=[],
    )
    base.update(kw)
    return EngineCase(**base)


def zero_vol(**kw) -> RiskParameters:
    return replace(RiskParameters(num_paths=4), driver_volatility={d: 0.0 for d in DRIVERS}, recession_severity=0.0,
                   **kw)


class TestScenarios:
    def test_zero_volatility_path_is_the_deterministic_valuation(self):
        case = _case()
        params = zero_vol()
        devs = property_deviations(params, "p1", "office", "Dallas")
        assert not devs.any()
        base = case.run()
        res = run_paths(case, devs[:2], params, include_monthly=True)
        assert res.npv[0] == pytest.approx(float(base.npv), abs=0.01)
        assert res.annual_noi[1, 3] == pytest.approx(float(base.annual_cash_flows[3].net_operating_income), abs=0.01)
        assert res.monthly_noi.shape == (2, 120)

    def test_reproducible_and_shared_layers(self):
        params = RiskParameters(num_paths=200)
        a1 = driver_shocks(params, "p1", "office", "Dallas")
        assert np.array_equal(a1, driver_shocks(params, "p1", "office", "Dallas"))
        b = driver_shocks(params, "p2", "office", "Dallas")
        c = driver_shocks(params, "p3", "retail", "Chicago")
        macro = [IDX["inflation"], IDX["sofr"], IDX["treasury_10y"]]
        # Economy-wide drivers are identical for every property on a path
        assert np.array_equal(a1[..., macro], b[..., macro]) and np.array_equal(a1[..., macro], c[..., macro])
        # Same market moves together more than a different type and market
        rg = IDX["rent_growth"]
        same = np.corrcoef(a1[..., rg].ravel(), b[..., rg].ravel())[0, 1]
        other = np.corrcoef(a1[..., rg].ravel(), c[..., rg].ravel())[0, 1]
        assert same == pytest.approx(0.6, abs=0.05)              # market_share
        assert other == pytest.approx(0.6 * 0.5, abs=0.05)       # market_share x global_share
        same_cap = np.corrcoef(a1[..., CAP].ravel(), b[..., CAP].ravel())[0, 1]
        assert same_cap == pytest.approx(0.8, abs=0.05)          # cap_rate_type_share

    def test_driver_correlation_is_recovered(self):
        params = RiskParameters(num_paths=2000)
        z = driver_shocks(params, "p1", "office", "Dallas").reshape(-1, len(DRIVERS))
        c = np.corrcoef(z.T)
        target = np.array(params.driver_correlation)
        assert np.allclose(np.diag(np.cov(z.T)), 1, atol=0.03)
        assert c[IDX["rent_growth"], IDX["vacancy"]] == pytest.approx(target[IDX["rent_growth"], IDX["vacancy"]],
                                                                      abs=0.03)
        assert c[IDX["sofr"], IDX["treasury_10y"]] == pytest.approx(0.7, abs=0.03)
        # Rates are economy-wide; a property's cap rate is only partly the national shock, which
        # dilutes the 0.5 in the matrix by sqrt(cap_rate_type_share x global_share)
        assert c[CAP, IDX["treasury_10y"]] == pytest.approx(0.5 * np.sqrt(0.8 * 0.5), abs=0.03)

    def test_persistence(self):
        params = RiskParameters(num_paths=3000, recession_severity=0.0)
        dev = property_deviations(params, "p1", "office", "Dallas")
        sofr = dev[:, 1:, IDX["sofr"]]
        phi = params.persistence("sofr")
        # Stationary standard deviation vol / sqrt(1 - phi^2)
        assert sofr[:, -1].std() == pytest.approx(params.vol("sofr") / np.sqrt(1 - phi ** 2), rel=0.08)
        assert dev.shape == (3000, MAX_YEARS + 1, len(DRIVERS))

    def test_recessions(self):
        params = RiskParameters(num_paths=4000)
        regime = recession_years(params)
        # Long-run share of recession years q / (1 - s + q) = 0.1 / 0.5
        assert regime[:, 10:].mean() == pytest.approx(recession_share(params), abs=0.01) == pytest.approx(0.2)
        # Stationary from year 0, not starting calm
        assert regime[:, 0].mean() == pytest.approx(recession_share(params), abs=0.02)
        # Same recession years for every property on a path; centred, so the average path is unchanged
        a = property_deviations(params, "p1", "office", "Dallas")
        b = property_deviations(params, "p2", "retail", "Chicago")
        calm = property_deviations(replace(params, recession_severity=0.0), "p1", "office", "Dallas")
        assert np.array_equal(recession_years(params), regime)
        rg = IDX["rent_growth"]
        assert abs(a[:, 1:, rg].mean()) < 0.002 and abs(b[:, 1:, rg].mean()) < 0.002
        # Fatter downside: the worst rent growth and cap rate paths get worse
        assert np.percentile(a[:, 5, rg], 1) < np.percentile(calm[:, 5, rg], 1)
        assert np.percentile(a[:, 5, CAP], 99) > np.percentile(calm[:, 5, CAP], 99)
        hit = regime[:, 0] == 1           # recession in year 1 on these paths
        assert a[hit, 1, rg].mean() < a[~hit, 1, rg].mean() - 0.03

    def test_rent_level_reversion(self):
        # A one-off rent growth shock is permanent in the rent level without reversion and fades with it
        params = replace(zero_vol(num_paths=1), driver_persistence={d: 0.0 for d in DRIVERS})
        shocks = np.zeros((1, MAX_YEARS, len(DRIVERS)))
        shocks[0, 0, IDX["rent_growth"]] = 1.0
        vol = dict(params.driver_volatility, rent_growth=0.10)
        flat = deviations(replace(params, driver_volatility=vol), shocks)[0, 1:, IDX["rent_growth"]]
        back = deviations(replace(params, driver_volatility=vol, rent_level_reversion=0.5), shocks)[0, 1:, IDX["rent_growth"]]
        assert flat.sum() == pytest.approx(0.10)
        assert back[:2].tolist() == pytest.approx([0.10, -0.05]) and back.sum() == pytest.approx(0.0, abs=1e-6)

    def test_monthly_interpolation(self):
        m = monthly(np.array([[0.0, 0.12, 0.24]]), 24)
        assert m[0, 6] == pytest.approx(0.06) and m[0, 24] == pytest.approx(0.24)


class TestPathCase:
    def test_deviations_flow_into_engine_inputs(self):
        case = _case()
        dev = np.zeros((MAX_YEARS + 1, len(DRIVERS)))
        dev[1:, IDX["rent_growth"]] = 0.01
        dev[1:, IDX["vacancy"]] = 0.05
        dev[1:, IDX["downtime"]] = np.log(2)
        dev[1:, IDX["concessions"]] = np.log(1.5)
        dev[1:, IDX["inflation"]] = 0.02
        dev[10, CAP] = 0.01
        pc = path_case(case, dev, RiskParameters())
        m = pc.market["office"]
        assert m.rent_growth_schedule[2] == D("0.04")
        assert m.general_vacancy_schedule[0] == D("0.10")
        assert m.credit_loss_schedule[0] == D("0.0225")           # 1% + 0.25 x 5 points
        assert m.downtime_schedule[0] == 12                       # 6 months x 2
        assert m.new_ti_per_sf == D("75") and m.new_free_rent_months == round(3 * 1.5)
        assert pc.expenses[0].growth_schedule[1] == D("0.05")
        assert pc.params.exit_cap_rate == case.params.exit_cap_rate + D("0.01")

        hurt = run_paths(case, dev[None], RiskParameters(), include_monthly=False)
        base = run_paths(case, np.zeros((1, MAX_YEARS + 1, len(DRIVERS))), RiskParameters(), include_monthly=False)
        assert hurt.npv[0] < base.npv[0] and hurt.exit_cap[0] > base.exit_cap[0]
