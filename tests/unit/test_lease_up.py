"""Lease-up / absorption for vacant suites."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from src.engine.property_cashflow import run_valuation
from src.engine.types import SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_growth_schedules import _flat_lease

D = Decimal
VACANT = SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office")


def _run(suite, leases=()):
    return run_valuation(
        property_start_date=date(2025, 1, 1),
        analysis_period_months=60,
        fiscal_year_end_month=12,
        suites=[suite],
        leases=list(leases),
        market_assumptions={"office": _make_market()},
        expenses=[],
        params=_make_params(),
    )


class TestLeaseUp:
    def test_unset_keeps_existing_behavior(self):
        assert not VACANT.has_lease_up
        assert _run(VACANT).npv == _run(replace(VACANT, absorption_start_date=None)).npv

    def test_lease_up_months_then_new_tenant(self):
        r = _run(replace(VACANT, lease_up_months=9))
        y1 = r.annual_cash_flows[0]
        # Vacant 9 months, then a new tenant at $35 for 3 months with 3 months free rent
        assert abs(y1.gross_potential_rent - D("35") * 10000 * 3 / 12) < D("1")
        assert y1.free_rent < 0
        assert y1.tenant_improvements == D("-500000")  # $50/SF new-tenant TI
        assert y1.absorption_vacancy < 0

    def test_absorption_start_date_delays_leasing(self):
        r = _run(replace(VACANT, absorption_start_date=date(2026, 1, 1), lease_up_months=0))
        cfs = r.annual_cash_flows
        assert cfs[0].gross_potential_rent == 0
        assert cfs[0].tenant_improvements == 0
        # Leases on 2026-01-01 at Year 2 market rent ($35 x 1.03)
        assert abs(cfs[1].gross_potential_rent - D("35") * D("1.03") * 10000) < D("1")

    def test_defaults_to_mla_downtime(self):
        r = _run(replace(VACANT, absorption_start_date=date(2025, 1, 1)))
        # MLA downtime is 6 months
        assert abs(r.annual_cash_flows[0].gross_potential_rent - D("35") * 10000 / 2) < D("1")

    def test_reabsorbed_lease_uses_lease_up(self):
        lease = _flat_lease(end_date=date(2025, 12, 31), upon_expiration="reabsorb")
        plain = _run(VACANT, [lease]).annual_cash_flows[1]
        leased_up = _run(replace(VACANT, lease_up_months=12), [lease]).annual_cash_flows
        assert plain.gross_potential_rent == 0
        assert leased_up[1].gross_potential_rent == 0
        assert leased_up[2].gross_potential_rent > 0
