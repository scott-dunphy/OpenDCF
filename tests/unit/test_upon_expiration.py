"""Upon-expiration options, MLA chaining, committed TI/LC."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from src.engine.property_cashflow import run_valuation
from src.engine.types import SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_growth_schedules import _flat_lease

D = Decimal
SUITE = SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office")


def _run(lease, market_map=None):
    return run_valuation(
        property_start_date=date(2025, 1, 1),
        analysis_period_months=60,
        fiscal_year_end_month=12,
        suites=[SUITE],
        leases=[lease],
        market_assumptions=market_map or {"office": _make_market()},
        expenses=[],
        params=_make_params(),
    )


def _expiring(**kw):
    # Expires end of Year 2
    return _flat_lease(end_date=date(2026, 12, 31), **kw)


class TestUponExpiration:
    def test_default_is_market_blend(self):
        assert _run(_expiring()).npv == _run(_expiring(upon_expiration="market")).npv

    def test_renew_has_no_downtime(self):
        y3 = _run(_expiring(upon_expiration="renew")).annual_cash_flows[2]
        assert y3.absorption_vacancy == 0
        # Market $35 grown 2 years at 3%, renewal spread 0
        assert abs(y3.gross_potential_rent - D("35") * D("1.03") ** 2 * 10000) < D("1")

    def test_vacate_has_full_downtime(self):
        y3 = _run(_expiring(upon_expiration="vacate")).annual_cash_flows[2]
        # 6 months downtime at 100% probability
        assert abs(y3.gross_potential_rent - D("35") * D("1.03") ** 2 * 10000 / 2) < D("1")

    def test_reabsorb_stays_vacant(self):
        r = _run(_expiring(upon_expiration="reabsorb"))
        assert all(cf.gross_potential_rent == 0 for cf in r.annual_cash_flows[2:])

    def test_option_uses_contract_terms_then_market(self):
        lease = _expiring(
            upon_expiration="option", option_rent_per_unit=D("25"), option_term_months=24,
            option_ti_per_sf=D("5"), option_lc_pct=D("0.02"),
        )
        cfs = _run(lease).annual_cash_flows
        assert abs(cfs[2].gross_potential_rent - D("250000")) < D("0.01")
        # Option rent escalates at market growth from its start
        assert abs(cfs[3].gross_potential_rent - D("257500")) < D("0.01")
        assert cfs[2].tenant_improvements == D("-50000")
        assert cfs[2].leasing_commissions < 0
        # After the 24-month option, market leasing with downtime (blend) resumes in Year 5
        assert cfs[4].gross_potential_rent != cfs[3].gross_potential_rent

    def test_option_without_rent_prices_at_market(self):
        lease = _expiring(upon_expiration="option", option_term_months=36)
        y3 = _run(lease).annual_cash_flows[2]
        assert abs(y3.gross_potential_rent - D("35") * D("1.03") ** 2 * 10000) < D("1")


class TestMlaChaining:
    def test_second_generation_uses_next_profile(self):
        first = replace(_make_market(), renewal_probability=D("1"), renewal_term_months=12, next_space_type="office_b")
        second = replace(_make_market(market_rent=D("50")), space_type="office_b", renewal_probability=D("1"))
        chained = _run(_expiring(), {"office": first, "office_b": second}).annual_cash_flows
        plain = _run(_expiring(), {"office": replace(first, next_space_type=None)}).annual_cash_flows
        # Year 3 = first renewal under "office"; Year 4 = second generation under "office_b"
        assert chained[2].gross_potential_rent == plain[2].gross_potential_rent
        assert chained[3].gross_potential_rent > plain[3].gross_potential_rent


class TestCommittedCosts:
    def test_paid_at_analysis_start_for_existing_lease(self):
        lease = _flat_lease(start_date=date(2024, 6, 1), committed_ti_amount=D("100000"), committed_lc_amount=D("20000"))
        y1 = _run(lease).annual_cash_flows[0]
        assert y1.tenant_improvements == D("-100000")
        assert y1.leasing_commissions == D("-20000")

    def test_paid_at_future_lease_start(self):
        lease = _flat_lease(start_date=date(2026, 3, 1), committed_ti_amount=D("80000"))
        cfs = _run(lease).annual_cash_flows
        assert cfs[1].tenant_improvements == D("-80000")
