"""Assumptions library: census market lookup, scope precedence and quality positioning."""
from decimal import Decimal

import pytest

from src.engine.assumption_overrides import ScopedValues, position_in_range, resolve
from src.services import cbsa

D = Decimal


class TestCbsa:
    def test_zip_lookup(self):
        assert cbsa.from_zip("75201") == "19100"
        assert cbsa.from_zip("66210-1234") == "28140"
        assert cbsa.from_zip("not a zip") is None
        assert cbsa.title("19100") == "Dallas-Fort Worth-Arlington, TX"

    def test_market_names(self):
        assert cbsa.match_market("Dallas-Fort Worth") == "19100"
        assert cbsa.match_market("Austin") == "12420"          # the metro, not Austin, MN
        assert cbsa.match_market("Austin", "MN") == "12380"
        assert cbsa.match_market("Portland") is None           # OR and ME: ambiguous
        assert cbsa.match_market("Portland", "Oregon") == "38900"
        assert cbsa.match_market("19100") == "19100"

    def test_for_property_falls_back_to_city_with_state(self):
        assert cbsa.for_property(None, None, "Austin", "TX") == "12420"
        assert cbsa.for_property(None, None, "Austin", None) is None
        assert cbsa.for_property("10001", "Dallas", None, None) == "35620"  # ZIP wins

    def test_search_and_states(self):
        assert [c.code for c in cbsa.search("kansas city mo")] == ["28140"]
        assert cbsa.state_code("texas") == "TX" and cbsa.state_code("tx") == "TX" and cbsa.state_code("Narnia") is None


class TestQualityPositioning:
    @pytest.mark.parametrize("q, cap, growth", [
        (5, D("0.05"), D("0.04")),     # best: low cap rate, high growth
        (4, D("0.055"), D("0.035")),
        (3, D("0.06"), D("0.03")),
        (2, D("0.0675"), D("0.025")),
        (1, D("0.075"), D("0.02")),
    ])
    def test_direction_and_interpolation(self, q, cap, growth):
        assert position_in_range("exit_cap_rate", D("0.05"), D("0.06"), D("0.075"), D(q)) == cap
        assert position_in_range("market_rent_growth", D("0.02"), D("0.03"), D("0.04"), D(q)) == growth

    def test_fields_without_direction_take_base(self):
        assert position_in_range("cpi_rate", D("0.01"), D("0.025"), D("0.04"), D(5)) == D("0.025")


LIBRARY = [
    ScopedValues({"exit_cap_rate": D("0.08")}, source="global"),
    ScopedValues({"exit_cap_rate": D("0.07")}, property_type="industrial", source="industrial"),
    ScopedValues({"exit_cap_rate": D("0.065")}, property_type="industrial", state="TX", source="tx"),
    ScopedValues({"exit_cap_rate": D("0.06"), "discount_rate": D("0.075")}, property_type="industrial",
                 cbsa_code="19100", source="dfw", ranges={"exit_cap_rate": (D("0.05"), D("0.075"))}),
    ScopedValues({"exit_cap_rate": D("0.0525")}, property_type="industrial", cbsa_code="19100",
                 quality_score=5, source="dfw-5"),
]


def _resolve(**kw):
    return resolve(LIBRARY, None, "industrial", None, **kw)


class TestLibraryPrecedence:
    def test_chain(self):
        assert _resolve().values["exit_cap_rate"] == D("0.07")
        assert _resolve(state="TX").values["exit_cap_rate"] == D("0.065")
        assert _resolve(cbsa_code="19100", state="TX").values["exit_cap_rate"] == D("0.06")
        r = _resolve(cbsa_code="19100", state="TX", quality_score=D(5))
        assert r.values["exit_cap_rate"] == D("0.0525") and r.sources["exit_cap_rate"] == "dfw-5"
        assert resolve(LIBRARY, None, "office", None, cbsa_code="19100").values["exit_cap_rate"] == D("0.08")

    def test_range_positions_by_quality_and_is_reported(self):
        r = _resolve(cbsa_code="19100", quality_score=D(4))
        assert r.values["exit_cap_rate"] == D("0.055")
        assert r.ranges["exit_cap_rate"] == (D("0.05"), D("0.06"), D("0.075"))
        assert r.sources["exit_cap_rate"] == "dfw (quality 4)"
        assert r.values["discount_rate"] == D("0.075") and "discount_rate" not in r.ranges

    def test_quality_rounds_to_a_quality_profile(self):
        assert _resolve(cbsa_code="19100", quality_score=D("4.6")).values["exit_cap_rate"] == D("0.0525")

    def test_half_scores_round_up_to_a_quality_profile(self):
        assert _resolve(cbsa_code="19100", quality_score=D("4.5")).values["exit_cap_rate"] == D("0.0525")
        assert _resolve(cbsa_code="19100", quality_score=D("4.4")).values["exit_cap_rate"] == D("0.053")  # positioned, no profile for 4


def test_integer_fields_position_to_whole_months():
    layer = ScopedValues({"downtime_months": D(6)}, ranges={"downtime_months": (D(3), D(9))}, source="x")
    assert resolve([layer], None, "office", None, quality_score=D(4)).values["downtime_months"] == D(5)  # 4.5 -> 5
    assert resolve([layer], None, "office", None, quality_score=D(2)).values["downtime_months"] == D(8)  # 7.5 -> 8


def test_reserves_by_basis_follow_the_property_area_unit():
    house = ScopedValues({"capital_reserves_per_sf": D("0.30"), "capital_reserves_per_unit_count": D("300")}, source="house")
    office = ScopedValues({"capital_reserves_per_unit": D("0.40")}, property_type="office", source="office")
    assert resolve([house], None, "industrial", None, area_unit="sf").values["capital_reserves_per_unit"] == D("0.30")
    assert resolve([house], None, "multifamily", None, area_unit="unit").values["capital_reserves_per_unit"] == D("300")
    assert resolve([house, office], None, "office", None, area_unit="sf").values["capital_reserves_per_unit"] == D("0.40")
    assert "capital_reserves_per_unit" not in resolve([house], None, "office", None).values  # basis unknown


def test_user_directions_flip_positioning():
    layer = ScopedValues({"new_ti_per_sf": D(40)}, ranges={"new_ti_per_sf": (D(20), D(60))}, source="x")
    assert resolve([layer], None, "office", None, quality_score=D(5)).values["new_ti_per_sf"] == D(20)
    flipped = resolve([layer], None, "office", None, quality_score=D(5), directions={"new_ti_per_sf": "higher"})
    assert flipped.values["new_ti_per_sf"] == D(60)
    none = resolve([layer], None, "office", None, quality_score=D(5), directions={"new_ti_per_sf": "none"})
    assert none.values["new_ti_per_sf"] == D(40)
