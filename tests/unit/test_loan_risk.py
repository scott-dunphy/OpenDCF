"""Monte Carlo default/loss engine and loan ratings."""
from dataclasses import replace
from decimal import Decimal

import numpy as np
import pytest

from src.engine.loan_risk.params import DEFAULT_DRIVER_VOLATILITY, DRIVERS, RiskParameters
from src.engine.loan_risk.ratings import (
    idealized_rate,
    moodys_rating,
    naic_cm_category,
    naic_dsc,
    naic_ltv,
    MOODYS_IDEALIZED_EL_PCT,
)
from src.engine.loan_risk.simulation import CollateralInput, LoanInput, default_probability, simulate


def zero_vol(**kw) -> RiskParameters:
    """No randomness: every path is the base case, so outcomes can be checked by hand."""
    base = RiskParameters(
        num_paths=20, driver_volatility={d: 0.0 for d in DRIVERS}, index_curve=[[0, 0.04], [30, 0.04]],
        default_intercept=-50.0,   # no term defaults unless a test turns them on
        recession_severity=0.0,
        treasury_curve=[[0, 0.0425], [30, 0.0425]], fair_value_spread=0.01,
    )
    return replace(base, **kw)


def flat_collateral(annual_noi=1_000_000.0, value=12_500_000.0, months=240, key="p1", ptype="industrial"):
    return CollateralInput(key=key, property_type=ptype, monthly_noi=np.full(months, annual_noi / 12),
                           current_value=value)


def io_loan(balance, months, rate=0.06, key="p1", loan_id="L1", **kw):
    return LoanInput(loan_id=loan_id, collateral_key=key, balance=balance,
                     begin_balance=np.full(months, balance), principal=np.zeros(months),
                     coupon=rate, **kw)


class TestDeterministic:
    def test_safe_loan_never_defaults_and_fair_value_is_pv_of_contract(self):
        params = zero_vol()
        loans, port = simulate([flat_collateral()], [io_loan(6_000_000.0, 60)], params)
        r = loans[0]
        assert r.pd_cumulative == 0 and r.expected_loss == 0 and r.lgd is None
        disc = 1 / (1 + 0.05 / 12)
        expected = sum(30_000 * disc ** t for t in range(1, 61)) + 6_000_000 * disc ** 60
        assert r.fair_value == pytest.approx(expected, rel=1e-9)
        assert port.expected_loss_amount == 0

    def test_maturity_default_and_loss_by_hand(self):
        # LTV 92%: refinance covers 75% of value and the sponsor pays down at most 15% more -> defaults at month 36
        # 10% sale costs: a sale ($11.25M net) cannot repay the loan, so the borrower defaults
        params = zero_vol(liquidation_lag_months=12, liquidation_lag_by_type={}, liquidation_cost_pct=0.25,
                          workout_cost_pct=0.03, sale_cost_pct=0.10, workout_carry_pct=0.02)
        loans, _ = simulate([flat_collateral()], [io_loan(11_500_000.0, 36)], params)
        r = loans[0]
        assert r.pd_cumulative == 1 and r.pd_maturity == 1 and r.pd_term == 0
        assert r.pd_by_year == [0, 0, 1]
        exposure = 11_500_000 * (1 + 0.06 * 12 / 12 + 0.03)   # balance + a year's advanced interest + workout costs
        # value net of costs + 12 months of NOI - a year's carrying costs at 2% of value
        proceeds = 12_500_000 * 0.75 + 1_000_000 - 12_500_000 * 0.02
        assert r.expected_loss_amount == pytest.approx(exposure - proceeds, rel=1e-9)
        assert r.lgd == pytest.approx((exposure - proceeds) / 11_500_000, rel=1e-9)

    def test_refinance_shortfall_cured_by_equity(self):
        # LTV 85%: refinance proceeds (75% of value) fall short by 10% of value, within the 15% paydown limit
        r = simulate([flat_collateral()], [io_loan(10_625_000.0, 36)], zero_vol())[0][0]
        assert r.pd_cumulative == 0

    def test_term_default_rate_follows_the_conditional_pd(self):
        # Flat NOI and value: DSCR 1.667 ($1M / $600K interest) and LTV 80% on every path, so each year
        # a path defaults with the annual PD from the logistic function
        params = zero_vol(num_paths=20000, default_intercept=-4.0, default_dscr_coef=-3.0, default_ltv_coef=3.0)
        r = simulate([flat_collateral()], [io_loan(10_000_000.0, 120)], params)[0][0]
        p = default_probability(params, np.array([1_000_000 / 600_000]), np.array([0.8]))[0]
        assert p == pytest.approx(1 / (1 + np.exp(4.0 + 3.0 * np.log(1_000_000 / 600_000) - 2.4)))
        for year in (1, 3, 5):
            assert r.pd_by_year[year - 1] == pytest.approx(1 - (1 - p) ** year, abs=0.006)
        assert r.pd_term == r.pd_cumulative - r.pd_maturity

    def test_higher_leverage_defaults_more(self):
        params = zero_vol(num_paths=5000, default_intercept=-4.0)
        safe = simulate([flat_collateral()], [io_loan(6_000_000.0, 120)], params)[0][0]
        risky = simulate([flat_collateral()], [io_loan(11_000_000.0, 120)], params)[0][0]
        assert risky.pd_term > safe.pd_term

    def test_extension_then_default(self):
        params = zero_vol(extension_min_dscr=1.0, extension_max_ltv=0.95, sale_cost_pct=0.10)
        loan = io_loan(11_500_000.0, 36, extension_count=1, extension_months=12)
        r = simulate([flat_collateral()], [loan], params)[0][0]
        assert r.pd_maturity == 1
        assert r.pd_by_year == [0, 0, 0, 1]                   # extended a year, then defaults

    def test_existing_delinquency_is_in_default(self):
        loan = io_loan(6_000_000.0, 60, delinquency_status="foreclosure")
        r = simulate([flat_collateral()], [loan], zero_vol())[0][0]
        assert r.pd_cumulative == 1 and r.pd_one_year == 1

    def test_junior_absorbs_loss_first(self):
        params = zero_vol(liquidation_cost_pct=0.25, sale_cost_pct=0.10)   # a sale cannot repay the stack
        senior = io_loan(7_000_000.0, 36, loan_id="A", lien_position=1)
        junior = io_loan(4_500_000.0, 36, loan_id="B", lien_position=2)
        res = {r.loan_id: r for r in simulate([flat_collateral()], [senior, junior], params)[0]}
        assert res["A"].pd_cumulative == 1 and res["B"].pd_cumulative == 1
        assert res["A"].expected_loss == 0
        assert res["B"].expected_loss > 0


class TestStochastic:
    def test_same_seed_same_result_and_paths_vary(self):
        params = RiskParameters(num_paths=500)
        col, loan = flat_collateral(ptype="office"), io_loan(9_000_000.0, 84)
        a = simulate([col], [loan], params)[0][0]
        b = simulate([col], [loan], params)[0][0]
        assert a.expected_loss_amount == b.expected_loss_amount
        c = simulate([col], [loan], replace(params, seed=99))[0][0]
        assert c.expected_loss_amount != a.expected_loss_amount
        assert 0 < a.pd_cumulative < 1

    def test_more_volatility_more_default(self):
        col, loan = flat_collateral(ptype="office"), io_loan(8_000_000.0, 84)
        def scaled(k):
            return RiskParameters(num_paths=1000, driver_volatility={d: v * k for d, v in DEFAULT_DRIVER_VOLATILITY.items()})
        low = simulate([col], [loan], scaled(0.5))[0][0]
        high = simulate([col], [loan], scaled(1.5))[0][0]
        assert high.pd_cumulative > low.pd_cumulative
        assert high.expected_loss > low.expected_loss

    def test_portfolio_loss_is_sum_of_loans(self):
        cols = [flat_collateral(key="p1", ptype="office"), flat_collateral(key="p2", ptype="retail")]
        loans = [io_loan(9_000_000.0, 60, key="p1", loan_id="L1"),
                 io_loan(9_500_000.0, 72, key="p2", loan_id="L2")]
        res, port = simulate(cols, loans, RiskParameters(num_paths=500))
        assert port.expected_loss_amount == pytest.approx(sum(r.expected_loss_amount for r in res))
        assert port.var["p99"] >= port.var["p95"] >= 0
        assert port.expected_shortfall_99 >= port.var["p99"]
        assert sum(port.histogram["counts"]) == 500

    def test_expected_shortfall_averages_worst_one_percent(self):
        """With fewer than 1% of paths losing, p99 is 0; ES99 must still be the worst-1% mean."""
        from dataclasses import replace
        from src.engine.loan_risk.simulation import portfolio_losses
        res, _ = simulate([flat_collateral(ptype="office")], [io_loan(8_000_000.0, 84)], RiskParameters(num_paths=100))
        losses = np.zeros(1000)
        losses[:5] = 1_000_000.0
        port = portfolio_losses([replace(res[0], losses=losses)])
        assert port.var["p99"] == 0
        assert port.expected_shortfall_99 == pytest.approx(500_000.0)


class TestRatings:
    def test_moodys_interpolation_and_mapping(self):
        assert idealized_rate(MOODYS_IDEALIZED_EL_PCT["Baa2"], 2.5) == pytest.approx((0.2585 + 0.4565) / 200)
        assert idealized_rate(MOODYS_IDEALIZED_EL_PCT["Baa2"], 15) == pytest.approx(0.0198)
        assert moodys_rating(0.0, 5) == "Aaa"
        assert moodys_rating(0.01, 5) == "Baa3"       # Baa2 5y = 0.869%, Baa3 = 1.6775%
        assert moodys_rating(0.60, 5) == "Ca"

    def test_naic_matrix(self):
        D = Decimal
        assert naic_cm_category(D("1.60"), D("0.60")) == "CM1"
        assert naic_cm_category(D("1.20"), D("0.80")) == "CM2"
        assert naic_cm_category(D("1.00"), D("0.80")) == "CM3"
        assert naic_cm_category(D("0.90"), D("0.90")) == "CM4"
        assert naic_cm_category(D("0.90"), D("1.10")) == "CM5"
        assert naic_cm_category(D("1.80"), D("1.20")) == "CM2"
        assert naic_cm_category(D("1.60"), D("0.60"), senior=False) == "CM2"
        assert naic_cm_category(D("1.60"), D("0.60"), "90_plus") == "CM6"
        assert naic_cm_category(D("1.60"), D("0.60"), "foreclosure") == "CM7"

    def test_naic_standardized_dsc_and_rounding(self):
        # 300-month amortization of $10M at 6% = $773,162/yr; 1,159,000 / 773,162 = 1.4990
        assert naic_dsc(Decimal("1159000"), Decimal("10000000"), Decimal("0.06")) == Decimal("1.49")
        assert naic_ltv(Decimal("7450000"), Decimal("10000000")) == Decimal("0.75")


class TestTapeCollateral:
    def test_market_moves_reach_revenue_as_leases_roll(self):
        from src.engine.collateral_mc import IDX, MAX_YEARS
        from src.engine.loan_risk.simulation import _tape_noi_factor

        params = RiskParameters(tape_avg_lease_years=5, tape_expense_ratio=0.4)
        dev = np.zeros((1, MAX_YEARS + 1, len(DRIVERS)))
        assert np.allclose(_tape_noi_factor(params, dev, 120), 1.0)
        dev[0, 1, IDX["rent_growth"]] = 0.10           # market rents 10% higher from year 1 on
        f = _tape_noi_factor(params, dev, 120)
        revenue = lambda rolled: 1 + 0.10 * rolled / 5  # noqa: E731 - one fifth of leases re-lease each year
        assert f[0, 0] == pytest.approx((revenue(1) - 0.4) / 0.6)          # year 1: one tranche
        assert f[0, 12 * 3] == pytest.approx((revenue(4) - 0.4) / 0.6)     # year 4
        assert f[0, 12 * 6] == pytest.approx((revenue(5) - 0.4) / 0.6)     # all re-leased


class TestExitCap:
    def test_future_values_use_the_exit_cap_rate(self):
        # $1M NOI, $12.5M value today (8% going-in); at a 10% exit cap the property is worth $10M
        # from month 1, so a $9.5M IO loan (76% LTV today) cannot refinance at 75% LTV + 15% paydown
        params = zero_vol(sale_cost_pct=0.10)   # $9M net sale proceeds cannot repay $9.5M either
        loan = io_loan(9_500_000.0, 36)
        going_in = simulate([flat_collateral()], [loan], params)[0][0]
        col = replace(flat_collateral(), exit_cap_rate=0.10)
        r = simulate([col], [loan], params)[0][0]
        assert going_in.pd_cumulative == 0
        assert r.value_percentiles["p50"][0] == 12_500_000
        assert r.value_percentiles["p50"][1] == pytest.approx(10_000_000)
        assert r.pd_maturity == 1          # 9.5M > 75% x 10M + 15% x 10M


class TestSaleAtMaturity:
    def test_borrower_with_equity_sells_instead_of_defaulting(self):
        # A 15% debt yield caps refinancing at $6.67M; with 15% paydown the borrower covers $8.54M,
        # short of the $9M balloon. The property ($12.5M, $12.25M after 2% sale costs) repays it.
        params = zero_vol(refi_min_debt_yield=0.15)
        r = simulate([flat_collateral()], [io_loan(9_000_000.0, 36)], params)[0][0]
        assert r.pd_cumulative == 0 and r.expected_loss == 0
        disc = 1 / (1 + 0.05 / 12)
        expected = sum(45_000 * disc ** t for t in range(1, 37)) + 9_000_000 * disc ** 36
        assert r.fair_value == pytest.approx(expected, rel=1e-9)

    def test_underwater_borrower_defaults(self):
        # $12.4M balloon > $12.25M sale proceeds
        params = zero_vol(refi_min_debt_yield=0.15)
        r = simulate([flat_collateral()], [io_loan(12_400_000.0, 36)], params)[0][0]
        assert r.pd_maturity == 1

    def test_sale_repays_the_whole_stack(self):
        params = zero_vol(refi_min_debt_yield=0.15)
        senior = io_loan(7_000_000.0, 36, loan_id="A", lien_position=1)
        junior = io_loan(3_000_000.0, 60, loan_id="B", lien_position=2)   # matures later
        res = {r.loan_id: r for r in simulate([flat_collateral()], [senior, junior], params)[0]}
        assert res["A"].pd_cumulative == 0 and res["B"].pd_cumulative == 0
        assert res["B"].fair_value < 3_000_000 * 1.2          # repaid at month 36, not month 60
