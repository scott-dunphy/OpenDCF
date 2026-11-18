"""Leasing commissions on the full lease term, LC $/SF, leasing cost and reserves growth,
reimbursed management fees, and vacancy/credit loss on gross revenue."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_growth_schedules import _expense, _flat_lease

D = Decimal


def _run(lease=None, market=None, expenses=(), months=60, **params):
    suite = SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office")
    return run_valuation(
        property_start_date=date(2025, 1, 1), analysis_period_months=months, fiscal_year_end_month=12,
        suites=[suite], leases=[lease or _flat_lease(end_date=date(2026, 12, 31), recovery_type="nnn")],
        market_assumptions={"office": market or _make_market()}, expenses=list(expenses),
        params=replace(_make_params(), **params),
    )


def _rollover_market(**kw):
    # Renewal only, no growth, so each rollover's lease rent is easy to state
    base = dict(rent_growth_rate=D(0), renewal_free_rent_months=0, renewal_ti_per_sf=D(0), renewal_lc_pct=D("0.04"))
    return replace(_make_market(market_rent=D("30"), renewal_prob=D("1"), gen_vacancy=D(0), credit_loss=D(0)),
                   **{**base, **kw})


class TestLeasingCommissions:
    def test_lc_is_on_the_full_lease_term_past_the_analysis_end(self):
        # Renewal starts Jan 2027 for 60 months; the 60-month analysis ends Dec 2029 (36 months in)
        full_term_rent = D(30) * 10000 * 5
        for months in (60, 72):
            r = _run(market=_rollover_market(), months=months)
            assert -r.annual_cash_flows[2].leasing_commissions == pytest.approx(full_term_rent * D("0.04"))

    def test_lc_per_sf_and_leasing_cost_growth(self):
        m = _rollover_market(renewal_lc_pct=D(0), renewal_lc_per_sf=D("2.5"), renewal_ti_per_sf=D(5),
                             leasing_cost_growth_rate=D("0.03"))
        y3 = _run(market=m).annual_cash_flows[2]          # rollover in Year 3: two years of growth
        assert -y3.leasing_commissions == pytest.approx(D("2.5") * 10000 * D("1.03") ** 2)
        assert -y3.tenant_improvements == pytest.approx(D(5) * 10000 * D("1.03") ** 2)


class TestReservesGrowth:
    def test_reserves_grow_from_year_one(self):
        r = _run(capital_reserves_per_unit=D("0.20"), capital_reserves_growth_rate=D("0.03"))
        assert [-cf.capital_reserves for cf in r.annual_cash_flows[:3]] == pytest.approx(
            [D(2000), D(2060), D("2121.80")])


class TestManagementFeeReimbursed:
    def _mgmt(self, recoverable):
        return _expense(expense_id="M", category="management_fee", base_amount=D(0), growth_rate=D(0),
                        is_recoverable=recoverable, is_pct_of_egi=True, pct_of_egi=D("0.02"))

    def test_net_tenant_reimburses_the_fee_on_its_own_egi(self):
        lease = _flat_lease(recovery_type="nnn")
        taxes = _expense(is_recoverable=True)
        plain = _run(lease, expenses=[taxes, self._mgmt(False)]).annual_cash_flows[0]
        cf = _run(lease, expenses=[taxes, self._mgmt(True)]).annual_cash_flows[0]
        fee = cf.expense_detail["management_fee"]
        # The fee is 2% of an EGI that includes the fee reimbursed; the full-building tenant pays it all
        assert -fee == pytest.approx(cf.effective_gross_income * D("0.02"))
        assert cf.expense_recoveries == pytest.approx(D(100000) - fee)
        # The landlord no longer bears the fee it paid before
        assert cf.net_operating_income - plain.net_operating_income == pytest.approx(
            -plain.expense_detail["management_fee"])

    def test_gross_tenant_does_not(self):
        cf = _run(_flat_lease(), expenses=[self._mgmt(True)]).annual_cash_flows[0]
        assert cf.expense_recoveries == 0


class TestVacancyOnGrossRevenue:
    def test_loss_applies_to_rent_and_recoveries(self):
        lease = _flat_lease(recovery_type="nnn")
        exp = [_expense(is_recoverable=True)]       # $100,000 taxes, recovered in full
        rent_only = _run(lease, expenses=exp).annual_cash_flows[0]
        gross = _run(lease, expenses=exp, vacancy_on_gross_revenue=True).annual_cash_flows[0]
        assert rent_only.credit_loss == D(-3000) and rent_only.general_vacancy_loss == D(-15000)
        assert gross.credit_loss == pytest.approx(D(-4000)) and gross.general_vacancy_loss == pytest.approx(D(-20000))


class TestBlendedRollover:
    def test_one_lease_with_weighted_terms(self):
        # Expiry Dec 2026: 65% renewal; new tenant 6 months down, $50 TI, 3 months free; renewal $20 TI, 1 month
        m = replace(_make_market(market_rent=D("30"), gen_vacancy=D(0), credit_loss=D(0)), rent_growth_rate=D(0),
                    rollover_method="blended")
        y3 = _run(market=m).annual_cash_flows[2]
        # Down round(0.35 x 6) = 2 months: rent from Mar 2027, 10 months of $25,000, less free rent of
        # 0.65 x 1 + 0.35 x 3 = 1.7 months (published DCF software keeps the fraction)
        assert y3.gross_potential_rent + y3.free_rent == pytest.approx(D(25000) * D("8.3"))
        assert -y3.tenant_improvements == pytest.approx((D("0.65") * 20 + D("0.35") * 50) * 10000)
        # LC on the full 60-month lease less free rent at the weighted 4.05%
        assert -y3.leasing_commissions == pytest.approx(
            D(25000) * D("58.3") * (D("0.65") * D("0.03") + D("0.35") * D("0.06")))


class TestMarketLeaseEscalation:
    def test_escalation_rate_and_lc_basis(self):
        # Renewal Jan 2027 at $30: rises 2.5% a year (market growth is 3%)
        m = _rollover_market(rent_growth_rate=D("0.03"), lease_escalation_pct=D("0.025"))
        cfs = _run(market=m, months=72).annual_cash_flows
        rent = D(30) * D("1.03") ** 2 * 10000         # market rent in Year 3
        assert cfs[3].gross_potential_rent == pytest.approx(rent * D("1.025"))
        with_steps = rent * sum(D("1.025") ** k for k in range(5)) * D("0.04")
        assert -cfs[2].leasing_commissions == pytest.approx(with_steps)
        # published DCF software CPI rent: escalations left out of the commission
        base_only = _run(market=replace(m, lc_includes_escalations=False), months=72).annual_cash_flows[2]
        assert -base_only.leasing_commissions == pytest.approx(rent * 5 * D("0.04"))
