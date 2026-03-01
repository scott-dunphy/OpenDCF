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
