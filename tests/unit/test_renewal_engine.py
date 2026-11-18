"""Unit tests for probability-weighted renewal engine."""
from collections import Counter
from datetime import date
from decimal import Decimal

import pytest

from src.engine.date_utils import build_analysis_period
from src.engine.renewal_engine import generate_speculative_leases
from src.engine.types import MarketAssumptions, SuiteInput


def make_suite(area: float = 5000.0, suite_id: str = "s1") -> SuiteInput:
    return SuiteInput(
        suite_id=suite_id,
        suite_name="Suite 100",
        area=Decimal(str(area)),
        space_type="office",
    )


def make_market(
    renewal_prob: float = 0.70,
    renewal_term: int = 60,
    new_term: int = 60,
    downtime: int = 6,
    market_rent: float = 35.0,
    rent_growth: float = 0.03,
    renewal_adj: float = 0.0,
    new_ti: float = 50.0,
    new_lc: float = 0.06,
    renewal_ti: float = 20.0,
    renewal_lc: float = 0.03,
    new_free_rent: int = 3,
    renewal_free_rent: int = 1,
    gen_vac: float = 0.05,
    credit_loss: float = 0.01,
) -> MarketAssumptions:
    return MarketAssumptions(
        space_type="office",
        market_rent_per_unit=Decimal(str(market_rent)),
        rent_growth_rate=Decimal(str(rent_growth)),
        new_lease_term_months=new_term,
        new_ti_per_sf=Decimal(str(new_ti)),
        new_lc_pct=Decimal(str(new_lc)),
        new_free_rent_months=new_free_rent,
        downtime_months=downtime,
        renewal_probability=Decimal(str(renewal_prob)),
        renewal_term_months=renewal_term,
        renewal_ti_per_sf=Decimal(str(renewal_ti)),
        renewal_lc_pct=Decimal(str(renewal_lc)),
        renewal_free_rent_months=renewal_free_rent,
        renewal_rent_adjustment_pct=Decimal(str(renewal_adj)),
        general_vacancy_pct=Decimal(str(gen_vac)),
        credit_loss_pct=Decimal(str(credit_loss)),
    )


class TestReturnType:
    def test_returns_tuple_of_slices_and_lease_inputs(self):
        """generate_speculative_leases returns (slices, lease_inputs)."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(renewal_prob=0.70, renewal_term=36, new_term=36, downtime=0)

        result = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        slices, lease_inputs = result
        assert isinstance(slices, list)
        assert isinstance(lease_inputs, list)

    def test_slices_and_lease_inputs_are_nonempty(self):
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(renewal_prob=0.70, renewal_term=36, new_term=36, downtime=0)

        slices, lease_inputs = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )
        assert len(slices) > 0
        assert len(lease_inputs) > 0

    def test_lease_input_ids_match_slice_lease_ids(self):
        """Every lease_id referenced in slices should exist in lease_inputs."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 60, 12)
        market = make_market(renewal_prob=0.65, renewal_term=36, new_term=36, downtime=3)

        slices, lease_inputs = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )
        lease_input_ids = {l.lease_id for l in lease_inputs}
        for s in slices:
            if not s.is_vacant:
                assert s.lease_id in lease_input_ids, (
                    f"Slice with lease_id={s.lease_id} has no matching LeaseInput"
                )


class TestProbabilityWeights:
    def test_weights_sum_to_one_per_month(self):
        """For every month in the analysis, all scenario weights sum to ~1.0."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 120, 12)
        market = make_market(renewal_prob=0.70, renewal_term=60, new_term=60, downtime=6)

        slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )

        weights_by_month: dict[int, Decimal] = {}
        for s in slices:
            weights_by_month[s.month_index] = (
                weights_by_month.get(s.month_index, Decimal(0)) + s.scenario_weight
            )

        for month_idx, total_weight in weights_by_month.items():
            assert abs(total_weight - Decimal(1)) < Decimal("0.02"), (
                f"Month {month_idx}: weights sum to {total_weight}"
            )

    def test_renewal_weight_equals_renewal_probability(self):
        """Gen-0 renewal slices have scenario_weight == renewal_probability."""
        suite = make_suite()
        # Short analysis so we stay in gen 0
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(renewal_prob=0.70, renewal_term=36, new_term=36, downtime=0)

        slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )

        renewal_slices = [s for s in slices if s.scenario_label == "renewal"]
        assert len(renewal_slices) > 0
        for s in renewal_slices:
            assert abs(s.scenario_weight - Decimal("0.70")) < Decimal("0.01")

    def test_new_tenant_weight_equals_complement(self):
        """Gen-0 new tenant slices have weight == 1 - renewal_probability."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(renewal_prob=0.70, renewal_term=36, new_term=36, downtime=0)

        slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )

        new_slices = [s for s in slices if s.scenario_label == "new_tenant"]
        assert len(new_slices) > 0
        for s in new_slices:
            assert abs(s.scenario_weight - Decimal("0.30")) < Decimal("0.01")

    def test_100pct_renewal_no_new_tenant_slices(self):
        """With P=1.0, only renewal slices generated."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(renewal_prob=1.0, renewal_term=36, new_term=36, downtime=0)

        slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )

        new_slices = [s for s in slices if s.scenario_label == "new_tenant"]
        assert len(new_slices) == 0

    def test_0pct_renewal_no_renewal_slices(self):
        """With P=0.0, only new tenant slices (+ downtime vacancies)."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(renewal_prob=0.0, renewal_term=36, new_term=36, downtime=0)

        slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )

        renewal_slices = [s for s in slices if s.scenario_label == "renewal"]
        assert len(renewal_slices) == 0

    def test_lease_level_renewal_probability_override_applies(self):
        """Lease-level override should control first-generation renewal weighting."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(renewal_prob=0.70, renewal_term=36, new_term=36, downtime=0)

        slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
            renewal_probability_override=Decimal("0.0"),
        )

        assert all(s.scenario_label != "renewal" for s in slices)

    def test_lease_level_renewal_rent_spread_override_applies(self):
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(
            renewal_prob=1.0,
            market_rent=35.0,
            renewal_adj=0.0,
            renewal_term=36,
            new_term=36,
            downtime=0,
        )

        base_slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )
        override_slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
            renewal_rent_spread_override=Decimal("0.10"),
        )

        base_renew = [s for s in base_slices if s.scenario_label == "renewal"]
        override_renew = [s for s in override_slices if s.scenario_label == "renewal"]
        assert base_renew and override_renew
        assert override_renew[0].base_rent > base_renew[0].base_rent


class TestDowntime:
    def test_downtime_creates_vacancy_gap(self):
        """With 6-month downtime, new tenant slices start after 6 months."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(renewal_prob=0.0, renewal_term=36, new_term=36, downtime=6)

        slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )

        vacant_slices = [s for s in slices if s.is_vacant]
        assert len(vacant_slices) >= 5  # 5-6 months of downtime

        new_slices = [s for s in slices if s.scenario_label == "new_tenant"]
        if new_slices:
            assert min(s.month_index for s in new_slices) >= 5

    def test_zero_downtime_immediate_occupancy(self):
        """With 0 downtime and P=0, new tenant starts in month 0."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(renewal_prob=0.0, renewal_term=36, new_term=36, downtime=0)

        slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )

        new_slices = [s for s in slices if s.scenario_label == "new_tenant"]
        assert len(new_slices) > 0
        assert new_slices[0].month_index == 0

    def test_downtime_vacant_slices_have_zero_rent(self):
        """Vacancy slices during downtime have zero effective rent."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(renewal_prob=0.0, renewal_term=36, new_term=36, downtime=3)

        slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )

        for s in slices:
            if s.is_vacant:
                assert s.effective_rent == Decimal(0)
                assert s.base_rent == Decimal(0)


    def test_new_tenant_after_analysis_end_is_not_created(self):
        """Downtime running past the analysis end leaves the suite vacant: no stub lease, no TI/LC."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 120, 12)
        market = make_market(renewal_prob=0.0, downtime=9)

        slices, leases = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2034, 6, 1),
            analysis=analysis,
            market=market,
        )

        assert leases == []
        assert all(s.is_vacant for s in slices)
        assert sum(s.ti_cost + s.lc_cost for s in slices) == Decimal(0)
        assert max(s.period_end for s in slices) == analysis.end_date

class TestSpeculativeIdentity:
    def test_speculative_lease_ids_are_unique_across_branches(self):
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 120, 12)
        market = make_market(renewal_prob=0.50, renewal_term=24, new_term=24, downtime=2)

        _, lease_inputs = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )

        counts = Counter(li.lease_id for li in lease_inputs)
        duplicates = [lease_id for lease_id, count in counts.items() if count > 1]
        assert not duplicates, f"Duplicate speculative lease IDs found: {duplicates}"


class TestRecursion:
    def test_full_coverage_over_10_year_analysis(self):
        """Multi-generation leases should cover most of the 10-year period."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 120, 12)
        market = make_market(
            renewal_prob=0.70, renewal_term=36, new_term=36, downtime=3
        )

        slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )

        assert len(slices) > 60  # many months covered
        last_slice = max(slices, key=lambda s: s.period_end)
        assert last_slice.period_end >= date(2033, 1, 1)

    def test_max_generation_cap_prevents_infinite_recursion(self):
        """Very short lease terms force many generations — max gen cap prevents recursion."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 120, 12)
        # 3-month leases would generate many generations
        market = make_market(renewal_prob=0.70, renewal_term=3, new_term=3, downtime=0)

        # Should not raise or hang
        slices, lease_inputs = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )
        assert isinstance(slices, list)

    def test_vacant_analysis_start_returns_empty(self):
        """Vacancy start at or after analysis end → empty result."""
        suite = make_suite()
        analysis = build_analysis_period(date(2025, 1, 1), 12, 12)
        market = make_market()

        slices, lease_inputs = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2026, 1, 1),  # == analysis end
            analysis=analysis,
            market=market,
        )
        assert slices == []
        assert lease_inputs == []


class TestTILCCosts:
    def test_ti_lc_on_first_slice(self):
        """TI and LC costs are negative and appear on the first slice of each lease."""
        suite = make_suite(area=5000)
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        market = make_market(
            renewal_prob=0.0,  # only new tenant
            new_term=24, downtime=0,
            new_ti=50.0, new_lc=0.05,
        )

        slices, _ = generate_speculative_leases(
            suite=suite,
            vacancy_start_date=date(2025, 1, 1),
            analysis=analysis,
            market=market,
        )

        new_slices = [s for s in slices if s.scenario_label == "new_tenant"]
        assert len(new_slices) > 0
        first = new_slices[0]
        # TI = -(50/SF * 5000 SF) = -$250K
        assert first.ti_cost < Decimal(0)
        assert abs(first.ti_cost + Decimal("250000")) < Decimal("1")
        # LC should also be negative
        assert first.lc_cost < Decimal(0)


class TestSuiteRollover:
    """Suite-level projection around in-place leases (property_cashflow._project_suite)."""

    def _lease(self, lease_id, start, end):
        from src.engine.types import LeaseInput
        return LeaseInput(
            lease_id, "s1", lease_id, Decimal(5000), start, end, Decimal(20), "annual", "flat",
            None, None, None, (), (), "nnn", None, None, None, (), None, None,
        )

    def _project(self, leases):
        from src.engine.property_cashflow import _project_suite
        market = make_market()
        analysis = build_analysis_period(date(2025, 1, 1), 120, 12)
        return _project_suite(make_suite(), leases, analysis, market, Decimal("0.025"), (), {"office": market})

    def test_overlapping_in_place_leases_not_double_counted(self):
        slices, _ = self._project([
            self._lease("A", date(2024, 1, 1), date(2027, 12, 31)),
            self._lease("B", date(2027, 1, 1), date(2031, 12, 31)),
        ])
        jan_2027 = [s for s in slices if s.month_index == 24]
        assert [s.lease_id for s in jan_2027] == ["A"]
        assert any(s.lease_id == "B" and s.month_index == 36 for s in slices)

    def test_gap_and_final_rollover_ids_are_distinct(self):
        _, spec = self._project([
            self._lease("A", date(2024, 1, 1), date(2025, 12, 31)),
            self._lease("B", date(2029, 1, 1), date(2030, 12, 31)),
        ])
        counts = Counter(l.lease_id for l in spec)
        assert len(spec) >= 4
        assert all(c == 1 for c in counts.values()), counts


class TestZeroFixedEscalation:
    def test_zero_per_unit_escalation_keeps_speculative_rent_flat(self):
        from src.engine.renewal_engine import _build_speculative_lease

        lease = _build_speculative_lease(
            suite=make_suite(),
            lease_id="spec",
            tenant_label="Market",
            start_date=date(2026, 1, 1),
            end_date=date(2030, 12, 31),
            rent=Decimal("30"),
            growth_rate=Decimal("0.03"),
            ti_per_sf=Decimal(0),
            lc_pct=Decimal(0),
            free_rent_months=0,
            term_months=60,
            escalation_per_unit=Decimal("0"),
        )
        assert lease.escalation_type == "fixed_step"
        assert lease.rent_steps == ()


class TestLeasingCommissionByLeaseYear:
    """% of each lease year's rent, e.g. 6% of years 1-5 and 3% of years 6-10."""
    RATES = (Decimal("0.06"),) * 5 + (Decimal("0.03"),)

    def _lc(self, market, start=date(2025, 1, 1)) -> Decimal:
        analysis = build_analysis_period(date(2025, 1, 1), 24, 12)
        slices, _ = generate_speculative_leases(make_suite(), start, analysis, market)
        return -sum(s.lc_cost * s.scenario_weight for s in slices)

    def _market(self, **kw):
        from dataclasses import replace
        m = make_market(renewal_prob=0.0, downtime=0, new_term=120, rent_growth=0.0, new_free_rent=0)
        return replace(m, **kw)

    def test_new_lease_rates_by_lease_year(self):
        rent = Decimal(35) * 5000   # a year
        assert self._lc(self._market()) == pytest.approx(rent * 10 * Decimal("0.06"), abs=Decimal("0.01"))
        assert self._lc(self._market(new_lc_pct_by_lease_year=self.RATES)) == pytest.approx(
            rent * (5 * Decimal("0.06") + 5 * Decimal("0.03")), abs=Decimal("0.01"))

    def test_partial_last_year_and_free_rent(self):
        # 66-month lease, 3 months free: year 1 is 9 paid months at 6%, year 6 is 6 months at 3%
        m = self._market(new_lease_term_months=66, new_free_rent_months=3, new_lc_pct_by_lease_year=self.RATES)
        monthly = Decimal(35) * 5000 / 12
        assert self._lc(m) == pytest.approx(monthly * (57 * Decimal("0.06") + 6 * Decimal("0.03")), abs=Decimal("0.01"))

    def test_blended_weights_each_lease_year(self):
        # 70% renewal at a single 3%, 30% new tenant at 6% then 3%: years 1-5 at 3.9%, after at 3%
        m = self._market(renewal_probability=Decimal("0.7"), renewal_term_months=120, rollover_method="blended",
                         new_free_rent_months=0, renewal_free_rent_months=0, new_lc_pct_by_lease_year=self.RATES)
        rent = Decimal(35) * 5000
        assert self._lc(m) == pytest.approx(rent * (5 * Decimal("0.039") + 5 * Decimal("0.03")), abs=Decimal("0.01"))

    def test_renewal_rates_by_lease_year(self):
        m = self._market(renewal_probability=Decimal(1), renewal_term_months=120, renewal_free_rent_months=0,
                         renewal_lc_pct_by_lease_year=(Decimal("0.03"),) * 5 + (Decimal("0.015"),))
        rent = Decimal(35) * 5000
        assert self._lc(m) == pytest.approx(rent * (5 * Decimal("0.03") + 5 * Decimal("0.015")), abs=Decimal("0.01"))
