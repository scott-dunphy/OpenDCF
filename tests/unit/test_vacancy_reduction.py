"""General vacancy reduced by modeled downtime, and credit-tenant exclusion."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from src.engine.property_cashflow import run_valuation
from src.engine.types import SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_growth_schedules import _flat_lease

D = Decimal


def _run(leases, suites, params=None, market=None):
    return run_valuation(
        property_start_date=date(2025, 1, 1),
        analysis_period_months=60,
        fiscal_year_end_month=12,
        suites=suites,
        leases=leases,
        market_assumptions={"office": market or _make_market(renewal_prob=D("0"))},
        expenses=[],
        params=params or _make_params(total_area=D("20000")),
    )


SUITES = [
    SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office"),
    SuiteInput(suite_id="S2", suite_name="200", area=D("10000"), space_type="office"),
]


def _leases(exclude_first=False):
    return [
        _flat_lease(lease_id="L1", suite_id="S1", exclude_from_general_vacancy=exclude_first),
        # Expires end of Year 2; 6 months downtime with 0% renewal -> vacancy in Year 3
        _flat_lease(lease_id="L2", suite_id="S2", end_date=date(2026, 12, 31)),
    ]


class TestCreditTenantExclusion:
    def test_excluded_lease_carries_no_general_vacancy_or_credit_loss(self):
        base = _run(_leases(), SUITES).annual_cash_flows[0]
        excl = _run(_leases(exclude_first=True), SUITES).annual_cash_flows[0]
        # Both leases pay $300K in Year 1; excluding L1 halves the vacancy base
        assert base.general_vacancy_loss == D("-30000.00")
        assert excl.general_vacancy_loss == D("-15000.00")
        assert excl.credit_loss == base.credit_loss / 2


class TestReduceByDowntime:
    def test_off_by_default(self):
        a = _run(_leases(), SUITES)
        b = _run(_leases(), SUITES, params=replace(_make_params(total_area=D("20000")),
                                                   reduce_general_vacancy_by_downtime=False))
        assert a.npv == b.npv

    def test_full_year_unchanged_when_no_downtime(self):
        params = replace(_make_params(total_area=D("20000")), reduce_general_vacancy_by_downtime=True)
        y1 = _run(_leases(), SUITES, params=params).annual_cash_flows[0]
        # No modeled vacancy: rate x GPR
        assert y1.general_vacancy_loss == D("-30000.00")

    def test_downtime_counts_toward_general_vacancy(self):
        params = replace(_make_params(total_area=D("20000")), reduce_general_vacancy_by_downtime=True)
        off = _run(_leases(), SUITES).annual_cash_flows[2]
        on = _run(_leases(), SUITES, params=params).annual_cash_flows[2]
        modeled = -on.absorption_vacancy
        assert modeled > 0
        target = (on.gross_potential_rent + modeled) * D("0.05")
        expected = -max(D(0), target - modeled)
        assert on.general_vacancy_loss == expected
        assert on.general_vacancy_loss > off.general_vacancy_loss  # smaller loss
        assert on.net_operating_income > off.net_operating_income
