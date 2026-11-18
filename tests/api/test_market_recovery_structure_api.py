"""Recovery structure on market leasing profiles: market leases use its terms; blank keeps the
expiring lease's recovery type (NNN for space never leased)."""
from datetime import date

from httpx import AsyncClient

from src.engine.date_utils import build_analysis_period
from src.engine.renewal_engine import _base_year
from src.engine.types import ExpenseRecoveryOverride
from tests.api.test_valuations_api import _setup_office_property


async def _valuation_and_profile(client: AsyncClient, ids: dict) -> tuple[str, str]:
    val = (await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
        "name": "Recoveries", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()["id"]
    (profile,) = (await client.get(f"/api/v1/valuations/{val}/market-profiles")).json()
    return val, profile["id"]


async def _total_recoveries(client: AsyncClient, val: str) -> float:
    run = await client.post(f"/api/v1/valuations/{val}/run")
    assert run.status_code == 200, run.text
    return sum(float(cf["expense_recoveries"]) for cf in run.json()["annual_cash_flows"])


async def test_gross_structure_stops_market_lease_recoveries(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, profile = await _valuation_and_profile(client, ids)
    url = f"/api/v1/valuations/{val}/market-profiles/{profile}"
    blank = await _total_recoveries(client, val)

    nnn = (await client.post(f"/api/v1/valuations/{val}/recovery-structures",
                             json={"name": "NNN"})).json()["id"]
    gross = (await client.post(f"/api/v1/valuations/{val}/recovery-structures",
                               json={"name": "Gross", "default_recovery_type": "full_service_gross"})).json()["id"]

    # An NNN structure matches the blank default (in-place leases are NNN, vacant space is NNN)
    assert (await client.put(url, json={"recovery_structure_id": nnn})).status_code == 200
    assert await _total_recoveries(client, val) == blank

    # Gross: the vacant suite leasing up and every rollover stop recovering
    res = await client.put(url, json={"recovery_structure_id": gross})
    assert res.json()["recovery_structure_id"] == gross
    assert await _total_recoveries(client, val) < blank

    # Clearing it restores the default
    res = await client.put(url, json={"recovery_structure_id": ""})
    assert res.json()["recovery_structure_id"] is None
    assert await _total_recoveries(client, val) == blank


async def test_structure_must_belong_to_the_valuation(client: AsyncClient):
    ids = await _setup_office_property(client)
    # Another valuation of the same property has its own structures
    foreign = (await client.post(f"/api/v1/valuations/{ids['setup_valuation_id']}/recovery-structures",
                                 json={"name": "Elsewhere"})).json()["id"]
    val, profile = await _valuation_and_profile(client, ids)
    res = await client.put(f"/api/v1/valuations/{val}/market-profiles/{profile}",
                           json={"recovery_structure_id": foreign})
    assert res.status_code == 422


async def test_deleting_the_structure_clears_the_profile(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, profile = await _valuation_and_profile(client, ids)
    rs = (await client.post(f"/api/v1/valuations/{val}/recovery-structures",
                            json={"name": "Gross", "default_recovery_type": "full_service_gross"})).json()["id"]
    url = f"/api/v1/valuations/{val}/market-profiles/{profile}"
    await client.put(url, json={"recovery_structure_id": rs})
    assert (await client.delete(f"/api/v1/valuations/{val}/recovery-structures/{rs}")).status_code == 204
    assert (await client.get(url)).json()["recovery_structure_id"] is None
    assert (await client.post(f"/api/v1/valuations/{val}/run")).status_code == 200


async def test_package_round_trip_points_at_the_new_valuation_structure(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, profile = await _valuation_and_profile(client, ids)
    rs = (await client.post(f"/api/v1/valuations/{val}/recovery-structures",
                            json={"name": "Gross", "default_recovery_type": "full_service_gross"})).json()["id"]
    await client.put(f"/api/v1/valuations/{val}/market-profiles/{profile}", json={"recovery_structure_id": rs})
    source = await _total_recoveries(client, val)

    package = (await client.get(f"/api/v1/valuations/{val}/package")).json()
    imported = (await client.post("/api/v1/valuation-packages/import", json=package)).json()
    new_structures = (await client.get(
        f"/api/v1/valuations/{imported['valuation_id']}/recovery-structures")).json()
    (new_profile,) = (await client.get(f"/api/v1/valuations/{imported['valuation_id']}/market-profiles")).json()
    assert new_profile["recovery_structure_id"] in {s["id"] for s in new_structures}
    assert new_profile["recovery_structure_id"] != rs
    assert await _total_recoveries(client, imported["valuation_id"]) == source


def test_base_year_set_when_a_structure_item_is_base_year():
    analysis = build_analysis_period(date(2025, 1, 1), 120, 12)
    taxes = ExpenseRecoveryOverride(
        expense_category="real_estate_taxes", recovery_type="base_year_stop", base_year_stop_amount=None,
        cap_per_sf_annual=None, floor_per_sf_annual=None, admin_fee_pct=None,
    )
    assert _base_year(analysis, date(2028, 3, 1), "nnn") is None
    assert _base_year(analysis, date(2028, 3, 1), "nnn", (taxes,)) == 2028
