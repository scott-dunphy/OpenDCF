"""Renewal rent at the greater or lesser of market and the expiring lease's last rent."""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from src.engine.date_utils import build_analysis_period
from src.engine.property_cashflow import _project_suite
from src.engine.renewal_engine import generate_speculative_leases
from tests.unit.test_lease_projector import make_lease
from tests.unit.test_renewal_engine import make_market, make_suite

ANALYSIS = build_analysis_period(date(2025, 1, 1), 120, 12)
START = date(2026, 1, 1)


def _market(rule, **kw):
    m = make_market(renewal_prob=1.0, downtime=0, rent_growth=0.0, new_free_rent=0, renewal_free_rent=0)
    return replace(m, renewal_rent_rule=rule, **kw)


def _first_month_rent(market, prior):
    slices, _ = generate_speculative_leases(make_suite(), START, ANALYSIS, market, prior_rent=prior)
    return sum(s.base_rent * s.scenario_weight for s in slices if s.period_start == START) / 5000 * 12


@pytest.mark.parametrize("rule,prior,expected", [
    ("market", D(40), D(35)),
    ("greater_of_prior", D(40), D(40)),
    ("greater_of_prior", D(30), D(35)),
    ("lesser_of_prior", D(30), D(30)),
    ("lesser_of_prior", D(40), D(35)),
    ("greater_of_prior", None, D(35)),   # no prior lease
])
def test_renewal_branch(rule, prior, expected):
    assert _first_month_rent(_market(rule), prior) == pytest.approx(expected)


def test_rule_compares_after_the_renewal_adjustment():
    # Market $35 less 10% = $31.50; greater of that and $33 = $33
    assert _first_month_rent(_market("greater_of_prior", renewal_rent_adjustment_pct=D("-0.10")), D(33)) == pytest.approx(D(33))


@pytest.mark.parametrize("method", ["probability_tree", "blended"])
def test_new_tenants_pay_market(method):
    m = _market("greater_of_prior", renewal_probability=D(0), rollover_method=method)
    assert _first_month_rent(m, D(40)) == pytest.approx(D(35))


def test_tree_and_blended_agree():
    # 60% renewal at $40 (prior), 40% new tenant at $35: expected rent $38 either way
    for method in ("probability_tree", "blended"):
        m = _market("greater_of_prior", renewal_probability=D("0.6"), rollover_method=method)
        assert _first_month_rent(m, D(40)) == pytest.approx(D(38)), method


def test_prior_rent_is_the_last_contract_rent_in_market_units():
    # $3.50/SF/month from 2023 rising 3% a year, ending 2027-12-31: last rent 3.50 x 1.03^4 a month = $47.27/SF/yr
    lease = make_lease(start=date(2023, 1, 1), end=date(2027, 12, 31), rent=D("3.50"), area=D(5000),
                       escalation_type="pct_annual", escalation_pct=D("0.03"), frequency="monthly")
    lease = replace(lease, suite_id="s1")
    slices, leases = _project_suite(make_suite(), [lease], ANALYSIS, _market("greater_of_prior"), D("0.025"))
    renewal = next(l for l in leases if l.start_date == date(2028, 1, 1))
    assert renewal.base_rent_per_unit == pytest.approx(D("3.50") * D("1.03") ** 4 * 12)
    # Lesser of: market $35
    slices, leases = _project_suite(make_suite(), [lease], ANALYSIS, _market("lesser_of_prior"), D("0.025"))
    assert next(l for l in leases if l.start_date == date(2028, 1, 1)).base_rent_per_unit == D(35)


def test_later_renewals_compare_with_the_speculative_lease():
    # Renewal at $40 (prior), 3% bumps over 5 years: the next renewal compares with $40 x 1.03^4
    lease = replace(make_lease(start=date(2021, 1, 1), end=date(2025, 12, 31), rent=D(40), area=D(5000)), suite_id="s1")
    m = _market("greater_of_prior", lease_escalation_pct=D("0.03"))
    _, leases = _project_suite(make_suite(), [lease], ANALYSIS, m, D("0.025"))
    starts = {l.start_date: l.base_rent_per_unit for l in leases}
    assert starts[date(2026, 1, 1)] == D(40)
    assert starts[date(2031, 1, 1)] == pytest.approx(D(40) * D("1.03") ** 4)
