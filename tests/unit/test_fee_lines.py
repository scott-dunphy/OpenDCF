"""% of EGI fee lines reimbursed by tenants: each line on the lease's own terms for that line (recovery
type, share, pool, gross-up, cap, floor, admin fee), and the cap / floor / admin fee order on any line.

One 10,000 SF suite unless stated; rent $30/SF ($300,000), no general vacancy or credit loss.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.engine.property_cashflow import run_valuation
from src.engine.types import ExpenseRecoveryOverride, RecoveryPoolInput, RentStepInput, SuiteInput
from tests.integration.test_engine_parity import _make_market, _make_params
from tests.unit.test_growth_schedules import _expense, _flat_lease, _run

D = Decimal
MARKET = _make_market(market_rent=D("30"), gen_vacancy=D(0), credit_loss=D(0))
NNN = _flat_lease(recovery_type="nnn")
TAXES = _expense(is_recoverable=True)  # $100,000 growing 3%


def _fee(category="management_fee", pct="0.03", **kw):
    return _expense(expense_id=category, category=category, base_amount=D(0), growth_rate=D(0), is_recoverable=True,
                    is_pct_of_egi=True, pct_of_egi=D(pct), **kw)


def _o(category, recovery_type="nnn", cap=None, floor=None, admin=None, **kw):
    return ExpenseRecoveryOverride(category, recovery_type, None, cap, floor, admin, **kw)


def _recoveries(lease, expenses, n=3, **kw):
    return [cf.expense_recoveries for cf in _run(lease, expenses=expenses, market=MARKET, **kw).annual_cash_flows[:n]]


def _fee_paid(cf, *categories):
    return -sum((cf.expense_detail.get(c, D(0)) for c in categories), D(0))


class TestSingleNetFeeLineUnchanged:
    """Numbers from before the per-line fee rework: one NNN management fee line must not move."""

    def test_nnn_fee(self):
        cfs = _run(NNN, expenses=[TAXES, _fee()], market=MARKET).annual_cash_flows
        assert [round(cf.expense_recoveries, 4) for cf in cfs[:3]] == [
            D("112371.1340"), D("115463.9175"), D("118649.4845")]

    def test_fee_in_a_dollar_cap_group(self):
        ov = (_o("management_fee", cap=D("0.10"), cap_group="g"),)
        cfs = _run(replace(NNN, recovery_overrides=ov), expenses=[TAXES, _fee()], market=MARKET).annual_cash_flows
        assert [round(cf.expense_recoveries, 4) for cf in cfs[:3]] == [D("101000"), D("104000"), D("107090")]
        assert [round(cf.net_operating_income, 4) for cf in cfs[:3]] == [
            D("288970"), D("288880"), D("288787.3")]

    def test_fee_in_a_growth_cap_group(self):
        cam = _expense(expense_id="C", category="cam", base_amount=D(50000), growth_rate=D("0.05"), is_recoverable=True)
        ov = tuple(_o(c, cap_group="ctrl", cap_growth_pct=D("0.02")) for c in ("cam", "management_fee"))
        lease = replace(NNN, recovery_overrides=ov, start_date=date(2024, 1, 1))
        cfs = _run(lease, expenses=[cam, _fee()], market=MARKET).annual_cash_flows
        assert [round(cf.expense_recoveries, 4) for cf in cfs[:3]] == [
            D("59034.7263"), D("60215.2548"), D("61419.4079")]
        assert [round(cf.net_operating_income, 4) for cf in cfs[:3]] == [
            D("298263.6845"), D("296908.7972"), D("295451.8257")]

    @pytest.mark.parametrize("calendar", [False, True])
    def test_grossed_up_fee_with_lease_up(self, calendar):
        suites = [SuiteInput(suite_id=s, suite_name=s, area=D(5000), space_type="office") for s in ("A", "B")]
        leases = [_flat_lease(lease_id="A", suite_id="A", area=D(5000), recovery_type="nnn"),
                  _flat_lease(lease_id="B", suite_id="B", area=D(5000), recovery_type="nnn",
                              start_date=date(2025, 7, 1))]
        cleaning = _expense(expense_id="CL", category="cleaning", growth_rate=D(0), is_recoverable=True,
                            variable_pct=D("0.5"), is_gross_up_eligible=True, gross_up_vacancy_pct=D("0.95"))
        fee = _fee(is_gross_up_eligible=True, gross_up_vacancy_pct=D("0.95"))
        r = run_valuation(
            property_start_date=date(2025, 4, 1), analysis_period_months=36, fiscal_year_end_month=3,
            suites=suites, leases=leases, market_assumptions={"office": MARKET}, expenses=[cleaning, fee],
            params=replace(_make_params(total_area=D(10000)), apply_stabilized_gross_up=True,
                           calendar_year_recoveries=calendar))
        # Calendar mode bills calendar 2025 (Apr-Dec, 83% occupied) at its own occupancy, not the
        # fiscal year's 87.5%, so Year 1 is grossed up further
        assert [round(cf.expense_recoveries, 4) for cf in r.annual_cash_flows] == [
            D("95515.9547") if not calendar else D("96159.2898"), D("112371.1340"), D("112371.1340")]
        assert [round(cf.net_operating_income, 4) for cf in r.annual_cash_flows] == [
            D("253525.4761") if not calendar else D("254149.5111"), D("300000"), D("300000")]


class TestSeveralFeeLines:
    def test_base_year_lease_recovers_a_split_fee_once(self):
        # fees-2: 3% + 1% recovers what one 4% line does
        lease = _flat_lease(recovery_type="base_year_stop", base_year=2025)
        one = _recoveries(lease, [TAXES, _fee(pct="0.04")])
        split = _recoveries(lease, [TAXES, _fee(pct="0.03"), _fee("admin_fee", "0.01")])
        assert split == pytest.approx(one, rel=D("1e-9"))
        assert one[1] > D(3000)  # taxes increase plus the fee increase

    def test_override_none_on_one_line_drops_only_that_line(self):
        # fees-3: an NNN lease excluding the 1% line reimburses only the 3% line
        expenses = [TAXES, _fee(pct="0.03"), _fee("admin_fee", "0.01")]
        only_three = _recoveries(NNN, [TAXES, _fee(pct="0.03")])
        no_admin = _recoveries(replace(NNN, recovery_overrides=(_o("admin_fee", "none"),)), expenses)
        assert no_admin == pytest.approx(only_three, rel=D("1e-9"))
        only_one = _recoveries(NNN, [TAXES, _fee("admin_fee", "0.01")])
        no_mgmt = _recoveries(replace(NNN, recovery_overrides=(_o("management_fee", "none"),)), expenses)
        assert no_mgmt == pytest.approx(only_one, rel=D("1e-9"))

    def test_admin_fee_on_one_line_marks_up_that_line_only(self):
        expenses = [TAXES, _fee(pct="0.03"), _fee("admin_fee", "0.01")]
        cf = _run(replace(NNN, recovery_overrides=(_o("admin_fee", admin=D("0.5")),)), expenses=expenses,
                  market=MARKET).annual_cash_flows[0]
        assert cf.expense_recoveries == pytest.approx(
            D(100000) + _fee_paid(cf, "management_fee") + _fee_paid(cf, "admin_fee") * D("1.5"))


class TestFeeCapAndFloor:
    def test_floor_is_a_dollar_minimum(self):
        # fees-1: a $2/SF floor on a ~$12,000 fee makes the tenant pay $20,000 (it diverged before)
        lease = replace(NNN, recovery_overrides=(_o("management_fee", floor=D(2)),))
        cfs = _run(lease, expenses=[TAXES, _fee()], market=MARKET).annual_cash_flows
        assert cfs[0].expense_recoveries == pytest.approx(D(120000))
        assert _fee_paid(cfs[0], "management_fee") == pytest.approx(D("0.03") * D(420000))

    def test_ungrouped_cap_caps_the_fee(self):
        # fees-4: $0.10/SF with no cap group caps the fee at $1,000, as a one-line cap group does
        lease = replace(NNN, recovery_overrides=(_o("management_fee", cap=D("0.10")),))
        assert _recoveries(lease, [TAXES, _fee()]) == pytest.approx([D(101000), D(104000), D(107090)])

    def test_cap_wins_over_floor(self):
        # critic: the minimum applies first, then the maximum
        cam = _expense(category="cam", is_recoverable=True, growth_rate=D(0))  # $10/SF
        lease = replace(NNN, recovery_overrides=(_o("cam", cap=D(5), floor=D(8)),))
        assert _recoveries(lease, [cam], 1) == pytest.approx([D(50000)])
        fee_lease = replace(NNN, recovery_overrides=(_o("management_fee", cap=D("0.5"), floor=D(2)),))
        assert _recoveries(fee_lease, [TAXES, _fee()], 1)[0] == pytest.approx(D(105000))

    def test_admin_fee_then_ungrouped_cap(self):
        # fees-10: CAM $10/SF, admin 15%, cap $8/SF: the cap includes the admin fee, as a cap group's does
        cam = _expense(category="cam", is_recoverable=True, growth_rate=D(0))
        alone = replace(NNN, recovery_overrides=(_o("cam", cap=D(8), admin=D("0.15")),))
        grouped = replace(NNN, recovery_overrides=(_o("cam", cap=D(8), admin=D("0.15"), cap_group="g"),))
        assert _recoveries(alone, [cam], 1) == pytest.approx(_recoveries(grouped, [cam], 1))
        assert _recoveries(alone, [cam], 1) == pytest.approx([D(80000)])


def _half_leased(expenses, pools=()):
    """A leased (NNN) and B vacant for the whole run: 50% occupancy."""
    suites = [SuiteInput(suite_id=s, suite_name=s, area=D(5000), space_type="office") for s in ("A", "B")]
    leases = [_flat_lease(lease_id="A", suite_id="A", area=D(5000), recovery_type="nnn"),
              _flat_lease(lease_id="B", suite_id="B", area=D(5000), recovery_type="nnn", start_date=date(2030, 1, 1),
                          end_date=date(2035, 12, 31))]
    return run_valuation(
        property_start_date=date(2025, 1, 1), analysis_period_months=24, fiscal_year_end_month=12,
        suites=suites, leases=leases, market_assumptions={"office": MARKET}, expenses=expenses,
        params=replace(_make_params(total_area=D(10000)), apply_stabilized_gross_up=True),
        recovery_pools=tuple(pools)).annual_cash_flows[0]


class TestFeeGrossUp:
    @pytest.mark.parametrize("category", ["management_fee", "property_management"])
    def test_each_line_grosses_up_on_its_own_terms(self, category):
        # fees-9: the 50%-share tenant at 50% occupancy pays 95% of an eligible line and 50% of another
        eligible = _fee(category, is_gross_up_eligible=True, gross_up_vacancy_pct=D("0.95"))
        cf = _half_leased([eligible, _fee("admin_fee", "0.01")])
        assert cf.expense_recoveries == pytest.approx(
            _fee_paid(cf, category) * D("0.95") + _fee_paid(cf, "admin_fee") * D("0.5"))

    def test_no_gross_up_in_an_occupied_area_pool(self):
        # pools-3: the only tenant in place pays the whole fee, not 95% / 50% of it
        eligible = _fee(is_gross_up_eligible=True, gross_up_vacancy_pct=D("0.95"))
        pool = RecoveryPoolInput(pool_id="Q", name="occ", expense_categories=("management_fee",),
                                 denominator="occupied_area")
        cf = _half_leased([eligible], [pool])
        assert cf.expense_recoveries == pytest.approx(_fee_paid(cf, "management_fee"))


class TestFeeInPoolWithExcludedAnchor:
    SUITES = [SuiteInput(suite_id="A", suite_name="Anchor", area=D(50000), space_type="office"),
              SuiteInput(suite_id="I1", suite_name="101", area=D(10000), space_type="office"),
              SuiteInput(suite_id="I2", suite_name="102", area=D(10000), space_type="office")]

    def _run(self, deduct):
        leases = [_flat_lease(lease_id=f"L{s.suite_id}", suite_id=s.suite_id, area=s.area, recovery_type="nnn")
                  for s in self.SUITES]
        pool = RecoveryPoolInput(pool_id="P", name="fee", expense_categories=("management_fee",),
                                 excluded_suite_ids=("A",), deduct_excluded_recoveries=deduct)
        return run_valuation(
            property_start_date=date(2025, 1, 1), analysis_period_months=24, fiscal_year_end_month=12,
            suites=self.SUITES, leases=leases, market_assumptions={"office": MARKET}, expenses=[_fee(pct="0.04")],
            params=_make_params(total_area=D(70000)), recovery_pools=(pool,)).annual_cash_flows[0]

    def test_deducting_pool_recovers_the_fee_once(self):
        # pools-2: the anchor pays 50/70 of the fee and the shops share the rest
        cf = self._run(deduct=True)
        assert cf.expense_recoveries == pytest.approx(_fee_paid(cf, "management_fee"))

    def test_non_deducting_pool_shops_share_the_whole_fee(self):
        cf = self._run(deduct=False)
        assert cf.expense_recoveries == pytest.approx(_fee_paid(cf, "management_fee") * D(120) / D(70))


class TestFeeOverBaseYear:
    def _stepped(self, **kw):
        # rent steps $30 -> $40 in 2026, so the fee rises
        return _flat_lease(escalation_type="fixed_step", rent_steps=(RentStepInput(date(2026, 1, 1), D(40)),), **kw)

    def test_base_year_override_on_a_net_lease(self):
        # fees-7 / stops-base-year-5: NNN lease, management fee override base_year_stop
        net = self._stepped(recovery_type="nnn", base_year=2025,
                            recovery_overrides=(_o("management_fee", "base_year_stop"),))
        whole = self._stepped(recovery_type="base_year_stop", base_year=2025)
        fee_only = [_fee()]
        assert _recoveries(net, fee_only) == pytest.approx(_recoveries(whole, fee_only), rel=D("1e-9"))
        assert _recoveries(net, fee_only)[1] > D(2500)

    def test_explicit_stop_without_base_year_recovers_the_fee(self):
        # An explicit stop amount sets the stop, so a missing base-year date must not drop the fee line
        stop = D(100000)
        dated = self._stepped(recovery_type="base_year_stop", base_year=2025, base_year_stop_amount=stop)
        undated = self._stepped(recovery_type="base_year_stop", base_year_stop_amount=stop)
        expenses = [TAXES, _fee()]
        assert _recoveries(undated, expenses) == pytest.approx(_recoveries(dated, expenses), rel=D("1e-9"))
        fee_not_recovered = [TAXES, replace(_fee(), is_recoverable=False)]
        assert _recoveries(undated, expenses)[1] > _recoveries(undated, fee_not_recovered)[1]

    def test_base_year_before_the_analysis_estimates_the_base_fee(self):
        # fees-6: a 2024 base year: the 2024 fee is the 2025 fee moved with the other expenses (taxes, 3%)
        lease = _flat_lease(recovery_type="base_year_stop", base_year=2024)
        cfs = _run(lease, expenses=[TAXES, _fee()], market=MARKET).annual_cash_flows
        fee1 = _fee_paid(cfs[0], "management_fee")
        taxes_increase = D(100000) - D(100000) / D("1.03")
        assert cfs[0].expense_recoveries == pytest.approx(taxes_increase + fee1 - fee1 / D("1.03"), rel=D("1e-3"))


class TestFeeInModifiedGrossPool:
    # The fee comes from the cash flow re-run until it converges (as for base-year leases)
    def test_no_stop_pays_the_fee_like_nnn(self):
        # fees-12 / stops-base-year-6
        mg = _flat_lease(recovery_type="modified_gross")
        cfs = _run(mg, expenses=[TAXES, _fee()], market=MARKET).annual_cash_flows
        assert cfs[0].expense_recoveries == pytest.approx(D(100000) + _fee_paid(cfs[0], "management_fee"),
                                                          rel=D("1e-3"))

    def test_fee_counts_against_the_stop(self):
        mg = _flat_lease(recovery_type="modified_gross", expense_stop_per_sf=D(5))
        cfs = _run(mg, expenses=[TAXES, _fee()], market=MARKET).annual_cash_flows
        fee1 = _fee_paid(cfs[0], "management_fee")
        assert cfs[0].expense_recoveries == pytest.approx(D(100000) + fee1 - D(50000), rel=D("1e-3"))


class TestSplitFeeEqualsOneLine:
    """A 4% fee entered as 3% + 1% (two categories, or two lines of one category) recovers the same."""

    SPLITS = {
        "one line": [_fee(pct="0.04")],
        "two categories": [_fee(pct="0.03"), _fee("admin_fee", "0.01")],
        "two lines, one category": [_fee(pct="0.03"), replace(_fee(pct="0.01"), expense_id="M2")],
    }

    @pytest.mark.parametrize("lease", [
        _flat_lease(recovery_type="base_year_stop", base_year=2025),
        _flat_lease(recovery_type="modified_gross", expense_stop_per_sf=D(5)),
    ], ids=["base_year", "modified_gross"])
    def test_stop_leases(self, lease):
        results = [_recoveries(lease, [TAXES, *fees]) for fees in self.SPLITS.values()]
        for r in results[1:]:
            assert r == pytest.approx(results[0], rel=D("1e-9"))

    @pytest.mark.parametrize("terms", [dict(cap=D("10.5")), dict(cap_growth_pct=D("0.01"))], ids=["dollar", "growth"])
    def test_cap_group(self, terms):
        categories = ("admin_fee", "management_fee", "real_estate_taxes")
        lease = replace(NNN, start_date=date(2024, 1, 1),
                        recovery_overrides=tuple(_o(c, cap_group="g", **terms) for c in categories))
        results = [_recoveries(lease, [TAXES, *fees]) for fees in self.SPLITS.values()]
        for r in results[1:]:
            assert r == pytest.approx(results[0], rel=D("1e-9"))
        uncapped = _recoveries(replace(NNN, start_date=date(2024, 1, 1)), [TAXES, _fee(pct="0.04")])
        assert results[0][2] < uncapped[2]


class TestPooledFeeWithExcludedAnchor:
    """A fee in a property-area pool that excludes a 50,000 SF anchor (shops 2 x 10,000 SF)."""

    SUITES = TestFeeInPoolWithExcludedAnchor.SUITES
    ELIGIBLE = dict(is_gross_up_eligible=True, gross_up_vacancy_pct=D("0.95"))
    STEP = dict(escalation_type="fixed_step", rent_steps=(RentStepInput(date(2026, 1, 1), D(40)),))

    def _run(self, leases, expenses, deduct=True, market=MARKET, categories=("management_fee",), **params_kw):
        pool = RecoveryPoolInput(pool_id="P", name="pool", expense_categories=categories,
                                 excluded_suite_ids=("A",), deduct_excluded_recoveries=deduct)
        params = replace(_make_params(total_area=D(70000)), apply_stabilized_gross_up=True, **params_kw)
        return run_valuation(
            property_start_date=date(2025, 1, 1), analysis_period_months=36, fiscal_year_end_month=12,
            suites=self.SUITES, leases=leases, market_assumptions={"office": market}, expenses=expenses,
            params=params, recovery_pools=(pool,))

    @staticmethod
    def _lease(suite_id, area, recovery_type="nnn", **kw):
        return _flat_lease(lease_id=f"L{suite_id}", suite_id=suite_id, area=D(area), recovery_type=recovery_type, **kw)

    def test_dark_anchor_is_not_grossed_up_onto_the_shops(self):
        # pools-2 (r6): the anchor leaves after Year 1 and its space stays dark; the shops are full, so
        # the pool is 100% occupied and the shops pay the fee, not 0.95 / 29% of it
        dark = replace(MARKET, renewal_probability=D(0), downtime_months=24, new_free_rent_months=0)
        leases = [self._lease("A", 50000, end_date=date(2025, 12, 31)), self._lease("I1", 10000),
                  self._lease("I2", 10000)]
        cf = self._run(leases, [_fee(pct="0.04", **self.ELIGIBLE)], market=dark).annual_cash_flows[1]
        assert cf.expense_recoveries == pytest.approx(_fee_paid(cf, "management_fee"), rel=D("1e-9"))

    @pytest.mark.parametrize("deduct", [True, False])
    @pytest.mark.parametrize("frequency", ["annual", "monthly"])
    def test_fee_grosses_up_like_cam_in_the_same_pool(self, deduct, frequency):
        # Shop I2 vacant: the pool's included suites are 50% occupied and gross up to 95%; the fee is
        # recovered in the same proportion as a CAM line in the same pool
        leases = [self._lease("A", 50000), self._lease("I1", 10000),
                  self._lease("I2", 10000, start_date=date(2030, 1, 1), end_date=date(2035, 12, 31))]
        cam =_expense(expense_id="C", category="cam", base_amount=D(70000), growth_rate=D(0), is_recoverable=True,
                       **self.ELIGIBLE)
        fee = _fee(pct="0.04", **self.ELIGIBLE)
        with_cam = self._run(leases, [cam], deduct, categories=("cam",),
                             vacancy_calculation_frequency=frequency).annual_cash_flows[0]
        with_fee = self._run(leases, [fee], deduct, vacancy_calculation_frequency=frequency).annual_cash_flows[0]
        cam_ratio = with_cam.expense_recoveries / _fee_paid(with_cam, "cam")
        assert cam_ratio < 1 if deduct else cam_ratio > 1
        assert with_fee.expense_recoveries / _fee_paid(with_fee, "management_fee") == pytest.approx(
            cam_ratio, rel=D("1e-9"))

    STOPS = {
        "modified_gross": dict(recovery_type="modified_gross"),
        "base_year": dict(recovery_type="base_year_stop", base_year=2025, **STEP),
    }

    @pytest.mark.parametrize("anchor_terms", list(STOPS.values()), ids=list(STOPS))
    def test_stop_anchor_is_deducted_from_net_shops(self, anchor_terms):
        # The anchor's dollar fee rows come off the pool before the net shops share it
        terms = dict(anchor_terms)
        leases = [self._lease("A", 50000, terms.pop("recovery_type"), **terms), self._lease("I1", 10000),
                  self._lease("I2", 10000)]
        for cf in self._run(leases, [_fee(pct="0.04")]).annual_cash_flows:
            assert cf.expense_recoveries == pytest.approx(_fee_paid(cf, "management_fee"), abs=D("0.05"))

    @pytest.mark.parametrize("calendar", [False, True])
    def test_net_anchor_is_deducted_from_modified_gross_shops(self, calendar):
        # The anchor's net share (solved with EGI) comes off the pool before the shops' dollar rows
        leases = [self._lease("A", 50000), self._lease("I1", 10000, "modified_gross"),
                  self._lease("I2", 10000, "modified_gross")]
        for cf in self._run(leases, [_fee(pct="0.04")], calendar_year_recoveries=calendar).annual_cash_flows:
            assert cf.expense_recoveries == pytest.approx(_fee_paid(cf, "management_fee"), abs=D("0.05"))

    @pytest.mark.parametrize("anchor, shops", [("nnn", "modified_gross"), ("modified_gross", "nnn"),
                                               ("modified_gross", "modified_gross")])
    def test_split_fee_line_is_deducted_once(self, anchor, shops):
        # A 4% fee entered as 3% + 1% lines of one category: each line comes off by its part of what the
        # anchor pays toward the category, not the whole of it
        leases = [self._lease("A", 50000, anchor), self._lease("I1", 10000, shops), self._lease("I2", 10000, shops)]
        fees = [_fee(pct="0.03"), replace(_fee(pct="0.01"), expense_id="M2")]
        for cf in self._run(leases, fees).annual_cash_flows:
            assert cf.expense_recoveries == pytest.approx(_fee_paid(cf, "management_fee"), abs=D("0.05"))

    def test_net_anchor_is_deducted_from_base_year_shops(self):
        # Shops on a 2025 base year pay the pool's increase: (2026 fee less the anchor's part) less
        # (2025 fee less the anchor's part)
        leases = [self._lease("A", 50000, **self.STEP),
                  self._lease("I1", 10000, "base_year_stop", base_year=2025, **self.STEP),
                  self._lease("I2", 10000, "base_year_stop", base_year=2025, **self.STEP)]
        cfs = self._run(leases, [_fee(pct="0.04")]).annual_cash_flows
        fees = [_fee_paid(cf, "management_fee") for cf in cfs[:2]]
        anchor = [f * D(50) / D(70) for f in fees]
        assert cfs[1].expense_recoveries == pytest.approx(
            anchor[1] + (fees[1] - anchor[1]) - (fees[0] - anchor[0]), abs=D("0.05"))


class TestFeeRowsConverge:
    """Base-year and modified gross fee rows use the converged fee, not the previous pass's."""

    def test_modified_gross_no_stop_pays_the_final_fee(self):
        mg = _flat_lease(recovery_type="modified_gross")
        cf = _run(mg, expenses=[TAXES, _fee()], market=MARKET).annual_cash_flows[0]
        assert cf.expense_recoveries == pytest.approx(D(100000) + _fee_paid(cf, "management_fee"), abs=D("0.02"))

    def test_base_year_pays_the_final_fee_increase(self):
        lease = TestFeeOverBaseYear()._stepped(recovery_type="base_year_stop", base_year=2025)
        cfs = _run(lease, expenses=[_fee()], market=MARKET).annual_cash_flows
        assert cfs[1].expense_recoveries == pytest.approx(
            _fee_paid(cfs[1], "management_fee") - _fee_paid(cfs[0], "management_fee"), abs=D("0.02"))
