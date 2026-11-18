"""Terms of market (renewal / new / lease-up / option / full-occupancy fill) leases."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.engine.date_utils import build_analysis_period
from src.engine.property_cashflow import _fill_turnover_vacancy, _project_suite, run_valuation
from src.engine.renewal_engine import _market_rent_at, generate_option_lease, generate_speculative_leases
from src.engine.types import ExpenseRecoveryOverride, SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_growth_schedules import _expense, _flat_lease

D = Decimal
SUITE = SuiteInput(suite_id="S1", suite_name="100", area=D("10000"), space_type="office")


def _override(category: str, **kw) -> ExpenseRecoveryOverride:
    return replace(ExpenseRecoveryOverride(expense_category=category, recovery_type="nnn",
                                           base_year_stop_amount=None, cap_per_sf_annual=None,
                                           floor_per_sf_annual=None, admin_fee_pct=None), **kw)


def _market(**kw):
    return replace(_make_market(renewal_prob=D("1")), **kw)


def _expenses():
    return [_expense(expense_id="C", category="cam", base_amount=D(100000), growth_rate=D("0.03"),
                     is_recoverable=True),
            _expense(expense_id="T", category="real_estate_taxes", base_amount=D(50000), growth_rate=D("0.03"),
                     is_recoverable=True)]


def _run(leases, market, months=60, start=date(2025, 1, 1), suite=SUITE, **params):
    return run_valuation(property_start_date=start, analysis_period_months=months, fiscal_year_end_month=12,
                         suites=[suite], leases=leases, market_assumptions={"office": market},
                         expenses=_expenses(), params=replace(_make_params(), **params))


def _spec(source, market, months=60, vacancy=date(2027, 1, 1)):
    analysis = build_analysis_period(date(2025, 1, 1), months, 12)
    _, leases = generate_speculative_leases(
        SUITE, vacancy, analysis, market,
        original_recovery_type=source.recovery_type,
        original_pro_rata_share=source.pro_rata_share,
        original_recovery_overrides=source.recovery_overrides,
        original_expense_stop_per_sf=source.expense_stop_per_sf,
    )
    return leases


class TestPreAnalysisRollover:
    """A lease that expired before the analysis start rolls over from a date before Year 1."""

    def _market(self):
        return _market(market_rent_per_unit=D("30"), renewal_free_rent_months=0, recovery_type="base_year_stop")

    def test_rent_and_base_year_come_from_year_one(self):
        analysis = build_analysis_period(date(2025, 1, 1), 120, 12)
        assert _market_rent_at(self._market(), analysis, date(2024, 12, 1)) == D("30")
        renewal = generate_speculative_leases(SUITE, date(2024, 12, 1), analysis, self._market())[1][0]
        assert renewal.base_rent_per_unit == D("30")
        assert renewal.base_year == 2024

    def test_base_year_recovers_year_one_growth(self):
        lease = _flat_lease(start_date=date(2020, 1, 1), end_date=date(2024, 11, 30), recovery_type="nnn")
        r = _run([lease], self._market(), months=120)
        # 2024 base year deflated from Year 1 at 3%: recovers Year 1 over 2024 for CAM and taxes
        expected = D(150000) - D(150000) / D("1.03")
        assert r.annual_cash_flows[0].expense_recoveries == pytest.approx(expected, abs=D("0.01"))


    def test_leasing_costs_before_the_analysis_are_not_charged(self):
        # Renewal signed Dec 2024: its TI and LC were spent before the analysis starts
        lease = _flat_lease(start_date=date(2020, 1, 1), end_date=date(2024, 11, 30), recovery_type="nnn")
        market = replace(self._market(), renewal_ti_per_sf=D("10"), renewal_lc_pct=D("0.05"))
        r = _run([lease], market, months=120)
        assert r.annual_cash_flows[0].tenant_improvements == 0
        assert r.annual_cash_flows[0].leasing_commissions == 0
        # The next renewal, inside the analysis, still pays them
        assert any(cf.tenant_improvements != 0 for cf in r.annual_cash_flows[1:])


class TestSameAsExpiringLease:
    """A blank Recovery Structure carries the expiring lease's whole recovery assignment."""

    def test_category_overrides_carried(self):
        source = _flat_lease(end_date=date(2026, 12, 31), recovery_type="full_service_gross",
                             recovery_overrides=(_override("real_estate_taxes"),))
        renewal = _spec(source, _market())[0]
        assert renewal.recovery_type == "full_service_gross"
        assert renewal.recovery_overrides == source.recovery_overrides

    def test_gross_plus_taxes_keeps_recovering_taxes(self):
        source = _flat_lease(end_date=date(2026, 12, 31), recovery_type="full_service_gross",
                             recovery_overrides=(_override("real_estate_taxes"),))
        cfs = _run([source], _market()).annual_cash_flows
        taxes = [D(50000) * D("1.03") ** y for y in range(5)]
        assert [cf.expense_recoveries for cf in cfs] == [pytest.approx(t, abs=D("0.01")) for t in taxes]

    def test_stop_carried_and_base_year_amounts_reset(self):
        source = _flat_lease(end_date=date(2026, 12, 31), recovery_type="modified_gross",
                             expense_stop_per_sf=D("12"),
                             recovery_overrides=(_override("cam", recovery_type="base_year_stop",
                                                           base_year_stop_amount=D(90000)),))
        renewal = _spec(source, _market())[0]
        assert (renewal.recovery_type, renewal.expense_stop_per_sf) == ("modified_gross", D("12"))
        assert renewal.recovery_overrides[0].base_year_stop_amount is None
        assert renewal.base_year == 2027

    def test_chained_generations_keep_terms(self):
        # 24-month renewals: three generations in the analysis, all with the expiring lease's terms
        source = _flat_lease(end_date=date(2026, 12, 31), recovery_type="modified_gross",
                             expense_stop_per_sf=D("12"), pro_rata_share=D("0.4"),
                             recovery_overrides=(_override("real_estate_taxes", recovery_type="none"),))
        leases = _spec(source, _market(renewal_term_months=24), months=96)
        assert len(leases) == 3
        for lease in leases:
            assert (lease.recovery_type, lease.expense_stop_per_sf, lease.pro_rata_share) == (
                "modified_gross", D("12"), D("0.4"))
            assert lease.recovery_overrides == source.recovery_overrides

    def test_chained_into_blank_profile_keeps_structure_stop(self):
        # First profile: modified gross with a $12 stop; the next profile is blank
        first = _market(renewal_term_months=24, recovery_type="modified_gross", expense_stop_per_sf=D("12"),
                        next_space_type="office2")
        second = replace(_market(renewal_term_months=24), space_type="office2")
        analysis = build_analysis_period(date(2025, 1, 1), 96, 12)
        _, leases = generate_speculative_leases(SUITE, date(2027, 1, 1), analysis, first,
                                                market_map={"office": first, "office2": second})
        assert [(l.recovery_type, l.expense_stop_per_sf) for l in leases] == [("modified_gross", D("12"))] * 3


class TestStructureBaseYearAmount:
    def test_fixed_amount_resets_on_market_lease(self):
        market = _market(recovery_type="base_year_stop", recovery_overrides=(
            _override("cam", recovery_type="base_year_stop", base_year_stop_amount=D(100000)),))
        renewal = _spec(_flat_lease(end_date=date(2026, 12, 31), recovery_type="nnn"), market)[0]
        assert renewal.recovery_overrides[0].base_year_stop_amount is None
        assert renewal.base_year == 2027

    def test_cam_recovers_nothing_in_its_base_year(self):
        market = _market(recovery_type="base_year_stop", recovery_overrides=(
            _override("cam", recovery_type="base_year_stop", base_year_stop_amount=D(100000)),))
        cfs = _run([_flat_lease(end_date=date(2026, 12, 31), recovery_type="full_service_gross")],
                   market).annual_cash_flows
        assert cfs[2].expense_recoveries == 0


class TestTypedShareOnMarketLeases:
    def test_blank_structure_keeps_share(self):
        source = _flat_lease(end_date=date(2026, 12, 31), recovery_type="nnn", pro_rata_share=D("0.5"))
        assert _spec(source, _market())[0].pro_rata_share == D("0.5")

    def test_structure_uses_area_share(self):
        source = _flat_lease(end_date=date(2026, 12, 31), recovery_type="nnn", pro_rata_share=D("0.5"))
        assert _spec(source, _market(recovery_type="nnn"))[0].pro_rata_share is None


class TestLeaseUpBeforeFirstLease:
    def test_gap_does_not_copy_future_lease(self):
        suite = replace(SUITE, lease_up_months=3)
        analysis = build_analysis_period(date(2025, 1, 1), 60, 12)
        future = _flat_lease(start_date=date(2027, 1, 1), end_date=date(2029, 12, 31),
                             recovery_type="full_service_gross", pro_rata_share=D("0.5"))
        market = _make_market(renewal_prob=D("0"))
        _, spec = _project_suite(suite, [future], analysis, market, D("0.025"), (), {"office": market})
        assert spec
        assert (spec[0].recovery_type, spec[0].pro_rata_share) == ("nnn", None)


class TestOptionMarketRent:
    def test_market_priced_option_uses_market_frequency(self):
        source = _flat_lease(end_date=date(2026, 12, 31), base_rent_per_unit=D("2.5"),
                             rent_payment_frequency="monthly", upon_expiration="option", option_term_months=36)
        analysis = build_analysis_period(date(2025, 1, 1), 60, 12)
        _, leases, _ = generate_option_lease(SUITE, source, date(2027, 1, 1), analysis, _make_market())
        assert leases[0].rent_payment_frequency == "annual"


class TestFractionalFreeRent:
    def test_renewal_abates_the_fraction(self):
        market = _market(market_rent_per_unit=D("30"), rent_growth_rate=D("0"), renewal_free_rent_schedule=(D("2.5"),),
                         renewal_ti_per_sf=D("0"), renewal_lc_pct=D("0.04"))
        cfs = _run([_flat_lease(end_date=date(2026, 12, 31), base_rent_per_unit=D("30"))], market).annual_cash_flows
        monthly = D("30") * D(10000) / 12
        assert cfs[2].free_rent == pytest.approx(-monthly * D("2.5"))
        # LC on the same 57.5 months of rent
        assert cfs[2].leasing_commissions == pytest.approx(-monthly * D("57.5") * D("0.04"))


class TestFullOccupancyFill:
    def _fill(self, source, market, months=72):
        analysis = build_analysis_period(date(2025, 1, 1), months, 12)
        slices, _ = _project_suite(SUITE, [source], analysis, market, D("0.025"), (), {"office": market})
        return _fill_turnover_vacancy({"S1": slices}, [SUITE], {"office": market}, analysis, {"S1": [source]})

    def test_modified_gross_stop_kept(self):
        market = replace(_make_market(renewal_prob=D("0")), recovery_type="modified_gross",
                         expense_stop_per_sf=D("12"))
        fill = self._fill(_flat_lease(end_date=date(2026, 12, 31), recovery_type="nnn"), market)
        assert [(f.recovery_type, f.expense_stop_per_sf) for f in fill] == [("modified_gross", D("12"))]

    def test_modified_gross_without_stop_resets_to_base_year(self):
        market = replace(_make_market(renewal_prob=D("0")), recovery_type="modified_gross")
        fill = self._fill(_flat_lease(end_date=date(2026, 12, 31), recovery_type="nnn"), market)
        assert [(f.recovery_type, f.base_year, f.start_date) for f in fill] == [
            ("base_year_stop", 2027, date(2027, 1, 1))]

    def test_blank_structure_follows_expiring_lease(self):
        source = _flat_lease(end_date=date(2026, 12, 31), recovery_type="full_service_gross", pro_rata_share=D("0.5"),
                             recovery_overrides=(_override("real_estate_taxes"),))
        fill = self._fill(source, _make_market(renewal_prob=D("0")))
        assert [(f.recovery_type, f.pro_rata_share, f.recovery_overrides) for f in fill] == [
            ("full_service_gross", D("0.5"), source.recovery_overrides)]

    def test_each_vacancy_bases_in_its_own_year(self):
        # Two rollovers: downtime in 2027 and again in 2032 (after a 60-month new lease)
        market = replace(_make_market(renewal_prob=D("0")), recovery_type="base_year_stop")
        fill = self._fill(_flat_lease(end_date=date(2026, 12, 31), recovery_type="nnn"), market, months=144)
        assert [(f.start_date, f.base_year) for f in fill] == [(date(2027, 1, 1), 2027), (date(2032, 7, 1), 2032)]

    def test_filled_months_recover_like_the_new_tenant(self):
        # Year 6 downtime filled at full occupancy recovers over the $12 stop, as the new tenant does
        market = replace(_make_market(renewal_prob=D("0")), recovery_type="modified_gross",
                         expense_stop_per_sf=D("12"))
        lease = _flat_lease(end_date=date(2029, 12, 31), recovery_type="nnn")
        r = run_valuation(property_start_date=date(2025, 1, 1), analysis_period_months=72, fiscal_year_end_month=12,
                          suites=[SUITE], leases=[lease], market_assumptions={"office": market},
                          expenses=_expenses(), params=_make_params(), _use_extended_forward_noi=False,
                          _full_occupancy=True)
        expense = D(150000) * D("1.03") ** 5
        assert r.annual_cash_flows[5].expense_recoveries == pytest.approx(expense - D(120000), abs=D("0.01"))


class TestAfterOption:
    def test_market_leases_follow_the_option_terms(self):
        # 24-month option ends inside the analysis; the blank profile's market lease continues its terms
        overrides = (_override("cam", recovery_type="base_year_stop", base_year_stop_amount=D(90000)),
                     _override("real_estate_taxes", recovery_type="none"))
        source = _flat_lease(end_date=date(2026, 12, 31), recovery_type="nnn", recovery_overrides=overrides,
                             upon_expiration="option", option_rent_per_unit=D("30"), option_term_months=24)
        analysis = build_analysis_period(date(2025, 1, 1), 84, 12)
        market = _market()
        _, spec = _project_suite(SUITE, [source], analysis, market, D("0.025"), (), {"office": market})
        option, renewal = spec[0], spec[1]
        assert option.lease_id.startswith("option_") and renewal.start_date == date(2029, 1, 1)
        assert renewal.recovery_overrides == option.recovery_overrides
        assert renewal.recovery_overrides[0].base_year_stop_amount is None
        assert renewal.base_year == 2029
