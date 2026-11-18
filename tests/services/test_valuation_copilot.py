from decimal import Decimal

import pytest

from src.models.market import MarketLeasingProfile
from src.models.property import Suite
from src.services.valuation_copilot import (
    apply_changes,
    assert_proposal_is_current,
    validate_changes,
)


def test_copilot_validates_and_applies_allowlisted_change():
    profile = MarketLeasingProfile(
        id="profile-1",
        property_id="property-1",
        space_type="anchor",
        market_rent_per_unit=Decimal("10"),
        rent_growth_rate_pct=Decimal("0.03"),
    )
    entities = {("market_leasing_profile", profile.id): profile}
    changes = [
        {
            "entity_type": "market_leasing_profile",
            "entity_id": profile.id,
            "field": "market_rent_per_unit",
            "new_value": 12,
            "reason": "User request",
        }
    ]
    validated = validate_changes(changes, entities)
    apply_changes(validated, entities)
    assert profile.market_rent_per_unit == Decimal("12")


def test_copilot_single_value_replaces_its_year_by_year_schedule():
    profile = MarketLeasingProfile(
        id="profile-1", property_id="property-1", space_type="anchor", market_rent_per_unit=Decimal("10"),
        general_vacancy_pct=Decimal("0.05"), general_vacancy_schedule=[Decimal("0.05"), Decimal("0.10")],
        credit_loss_schedule=[Decimal("0.01"), Decimal("0.02")],
    )
    entities = {("market_leasing_profile", profile.id): profile}
    validated = validate_changes([{
        "entity_type": "market_leasing_profile", "entity_id": profile.id, "field": "general_vacancy_pct",
        "new_value": 0.08, "reason": "User request",
    }], entities)
    apply_changes(validated, entities)
    assert profile.general_vacancy_pct == Decimal("0.08") and profile.general_vacancy_schedule == []
    assert profile.credit_loss_schedule == [Decimal("0.01"), Decimal("0.02")]


def test_copilot_rejects_non_allowlisted_change():
    profile = MarketLeasingProfile(id="profile-1", property_id="property-1", space_type="anchor")
    with pytest.raises(ValueError, match="may not change"):
        validate_changes(
            [
                {
                    "entity_type": "market_leasing_profile",
                    "entity_id": profile.id,
                    "field": "property_id",
                    "new_value": "other",
                    "reason": "unsafe",
                }
            ],
            {("market_leasing_profile", profile.id): profile},
        )


def test_copilot_parses_false_string_as_false():
    suite = Suite(id="suite-1", property_id="property-1", suite_name="A", area=Decimal("1"), space_type="office")
    changes = [{
        "entity_type": "suite", "entity_id": suite.id, "field": "is_available",
        "new_value": "false", "reason": "User request",
    }]
    assert validate_changes(changes, {("suite", suite.id): suite})[0]["new_value"] is False


def test_copilot_rejects_stale_confirmation():
    profile = MarketLeasingProfile(
        id="profile-1", property_id="property-1", space_type="anchor",
        market_rent_per_unit=Decimal("10"), rent_growth_rate_pct=Decimal("0.03"),
    )
    entities = {("market_leasing_profile", profile.id): profile}
    proposal = validate_changes([{
        "entity_type": "market_leasing_profile", "entity_id": profile.id,
        "field": "market_rent_per_unit", "new_value": "12", "reason": "User request",
    }], entities)
    profile.market_rent_per_unit = Decimal("11")
    with pytest.raises(ValueError, match="changed after this proposal"):
        assert_proposal_is_current(proposal, entities)
