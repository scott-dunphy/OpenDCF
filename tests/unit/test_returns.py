"""Unit tests for purchase-price returns, direct cap and sensitivity grids."""
from dataclasses import replace
from decimal import Decimal

from src.engine.dcf import build_debt_schedule_detail, discount_cash_flows, irr_from_series
from src.engine.returns import compute_investment_returns, direct_cap_value, sensitivity_grid
from tests.unit.test_dcf import make_annual_cfs, make_params


def _with_debt(cfs, debt_service):
    for cf, ds in zip(cfs, debt_service):
        cf.debt_service = -ds
        cf.levered_cash_flow = cf.cash_flow_before_debt - ds
    return cfs


class TestIrrFromSeries:
    def test_simple_bond(self):
        irr = irr_from_series([Decimal(-1000), Decimal(100), Decimal(1100)])
        assert abs(irr - Decimal("0.10")) < Decimal("0.000001")

    def test_no_sign_change(self):
        assert irr_from_series([Decimal(100), Decimal(100)]) is None


class TestInvestmentReturns:
    def test_no_price_returns_none(self):
        cfs = make_annual_cfs([100_000] * 5)
        assert compute_investment_returns(cfs, Decimal(0), Decimal(0), make_params(), [Decimal(0)] * 5) is None

    def test_unlevered_irr_equals_cap_rate_for_flat_perpetuity(self):
        """Flat $100K NOI bought at 8% cap and sold at 8% cap (no costs) → IRR = 8%."""
        cfs = make_annual_cfs([100_000] * 10)
        params = replace(make_params(), purchase_price=Decimal("1250000"))
        r = compute_investment_returns(cfs, Decimal("1250000"), Decimal("1250000"), params, [Decimal(0)] * 10)
        assert abs(r.unlevered_irr - Decimal("0.08")) < Decimal("0.000001")
        assert r.unlevered_irr_status == "unique"
        assert r.unlevered_xirr_status == "unique"
        assert r.unlevered_xirr is not None
        assert r.unlevered_mirr is not None
        assert r.going_in_cap_rate == Decimal("0.08")
        assert r.levered_irr is None
        assert r.npv_at_price == Decimal(0)
        # Multiple = (10 × 100K + 1.25M) / 1.25M
        assert abs(r.unlevered_equity_multiple - Decimal("1.8")) < Decimal("0.0001")

    def test_acquisition_costs_lower_irr(self):
        cfs = make_annual_cfs([100_000] * 10)
        params = replace(make_params(), purchase_price=Decimal("1250000"), acquisition_costs_pct=Decimal("0.02"))
        r = compute_investment_returns(cfs, Decimal("1250000"), Decimal("1250000"), params, [Decimal(0)] * 10)
        assert r.total_investment == Decimal("1275000")
        assert r.unlevered_irr < Decimal("0.08")

    def test_levered_returns_with_io_loan(self):
        """IO loan at 5% on 60% LTV: levered IRR > unlevered IRR (positive leverage)."""
        cfs = make_annual_cfs([100_000] * 10)
        params = replace(
            make_params(),
            purchase_price=Decimal("1250000"),
            loan_amount=Decimal("750000"),
            interest_rate=Decimal("0.05"),
            amortization_months=360,
            loan_term_months=240,
            io_period_months=240,
            loan_fees_pct=Decimal("0.01"),
        )
        service, balances, balloons = build_debt_schedule_detail(params, 10)
        assert balances[-1] == Decimal("750000")
        _with_debt(cfs, service)
        r = compute_investment_returns(cfs, Decimal("1250000"), Decimal("1250000"), params, balances)
        assert r.equity_invested == Decimal("1250000") - Decimal("750000") + Decimal("7500")
        assert r.loan_payoff_at_sale == Decimal("750000")
        assert r.levered_irr > r.unlevered_irr
        assert abs(r.year1_dscr - Decimal("100000") / Decimal("37500")) < Decimal("0.0001")
        assert r.min_dscr == r.year1_dscr
        assert r.loan_to_value == Decimal("0.6")
        assert abs(r.year1_debt_yield - Decimal("100000") / Decimal("750000")) < Decimal("0.000001")
        # Cash-on-cash = (100K - 37.5K) / 507.5K
        assert abs(r.year1_cash_on_cash - Decimal("62500") / Decimal("507500")) < Decimal("0.000001")
        assert len(r.levered_cash_flows) == 11

    def test_balance_after_maturity_is_zero(self):
        params = replace(
            make_params(),
            loan_amount=Decimal("1000000"),
            interest_rate=Decimal("0.06"),
            amortization_months=360,
            loan_term_months=60,
        )
        service, balances, balloons = build_debt_schedule_detail(params, 10)
        assert balances[4] == Decimal(0)
        assert balances[3] > Decimal(0)
        assert service[5] == Decimal(0)
        assert balloons[4] > Decimal(0)
        assert balloons[3] == Decimal(0)
        assert balloons[5] == Decimal(0)

    def test_balloon_at_maturity_excluded_from_dscr(self):
        """A 10-yr IO loan on a 10-yr hold repays its balloon in year 10; DSCR stays at NOI / interest."""
        cfs = make_annual_cfs([100_000] * 10)
        params = replace(
            make_params(),
            purchase_price=Decimal("1250000"),
            loan_amount=Decimal("750000"),
            interest_rate=Decimal("0.05"),
            amortization_months=360,
            loan_term_months=120,
            io_period_months=120,
        )
        service, balances, balloons = build_debt_schedule_detail(params, 10)
        assert balloons[9] == Decimal("750000")
        assert balances[9] == Decimal(0)
        _with_debt(cfs, service)
        r = compute_investment_returns(cfs, Decimal("1250000"), Decimal("1250000"), params, balances, balloons)
        expected = Decimal("100000") / Decimal("37500")
        assert abs(r.min_dscr - expected) < Decimal("0.0001")
        assert abs(r.avg_cash_on_cash - r.year1_cash_on_cash) < Decimal("0.000001")


class TestDirectCap:
    def test_direct_cap(self):
        assert direct_cap_value(Decimal("100000"), Decimal("0.05")) == Decimal("2000000")

    def test_missing_rate(self):
        assert direct_cap_value(Decimal("100000"), None) is None


class TestSensitivityGrid:
    def test_mid_year_cash_flows_do_not_pull_sale_proceeds_forward(self):
        kwargs = dict(
            cash_flows_before_debt=[Decimal("100")],
            terminal_noi_basis=Decimal("100"),
            exit_costs_pct=Decimal(0),
            transfer_tax_preset="none",
            transfer_tax_custom_rate=None,
            capital_deduction=Decimal(0),
            discount_rates=[Decimal("0.10")],
            exit_cap_rates=[Decimal("0.10")],
            use_mid_year=True,
        )
        end = sensitivity_grid(**kwargs)
        legacy = sensitivity_grid(**kwargs, terminal_timing="mid_year")
        assert end.values[0][0] < legacy.values[0][0]

    def test_center_cell_matches_dcf(self):
        cfs = make_annual_cfs([100_000 * (1.03 ** i) for i in range(10)])
        noi_basis = Decimal(str(100_000 * (1.03 ** 10)))
        params = make_params(discount_rate=0.08, exit_cap_rate=0.065, exit_costs_pct=0.02)
        gross = noi_basis / params.exit_cap_rate
        tv = gross - gross * params.exit_costs_pct
        _, _, npv = discount_cash_flows(cfs, tv, params.discount_rate)

        grid = sensitivity_grid(
            cash_flows_before_debt=[cf.cash_flow_before_debt for cf in cfs],
            terminal_noi_basis=noi_basis,
            exit_costs_pct=params.exit_costs_pct,
            transfer_tax_preset="none",
            transfer_tax_custom_rate=None,
            capital_deduction=Decimal(0),
            discount_rates=[Decimal("0.075"), Decimal("0.08"), Decimal("0.085")],
            exit_cap_rates=[Decimal("0.06"), Decimal("0.065"), Decimal("0.07")],
        )
        assert abs(grid.values[1][1] - npv) < Decimal("0.01")
        # Value falls as discount rate rises and as exit cap rises
        assert grid.values[0][1] > grid.values[1][1] > grid.values[2][1]
        assert grid.values[1][0] > grid.values[1][1] > grid.values[1][2]
        assert grid.irr_by_exit_cap == [None, None, None]

    def test_irr_by_exit_cap_with_price(self):
        cfs = [Decimal(100_000)] * 10
        grid = sensitivity_grid(
            cash_flows_before_debt=cfs,
            terminal_noi_basis=Decimal(100_000),
            exit_costs_pct=Decimal(0),
            transfer_tax_preset="none",
            transfer_tax_custom_rate=None,
            capital_deduction=Decimal(0),
            discount_rates=[Decimal("0.08")],
            exit_cap_rates=[Decimal("0.07"), Decimal("0.08"), Decimal("0.09")],
            total_investment=Decimal(1_250_000),
        )
        assert abs(grid.irr_by_exit_cap[1] - Decimal("0.08")) < Decimal("0.000001")
        assert grid.irr_by_exit_cap[0] > grid.irr_by_exit_cap[1] > grid.irr_by_exit_cap[2]
