"""Recovery pools API: validation, effect on results, staleness, snapshots and packages."""
from httpx import AsyncClient

from tests.api.test_valuations_api import _setup_office_property

V = "/api/v1/valuations"
P = "/api/v1/properties"


async def _valuation(client: AsyncClient, ids: dict) -> str:
    val = await client.post(f"{P}/{ids['property_id']}/valuations", json={
        "name": "Pools", "discount_rate": "0.08", "exit_cap_rate": "0.065"})
    assert val.status_code == 201, val.text
    return val.json()["id"]


async def _noi(client: AsyncClient, val: str) -> list[float]:
    run = await client.post(f"{V}/{val}/run")
    assert run.status_code == 200, run.text
    return [float(cf["net_operating_income"]) for cf in run.json()["annual_cash_flows"]]


async def test_crud_and_validation(client: AsyncClient):
    ids = await _setup_office_property(client)
    url = f"{V}/{ids['setup_valuation_id']}/recovery-pools"
    pool = await client.post(url, json={"name": "CAM", "expense_categories": ["cam", "cam"],
                                        "excluded_suite_ids": [ids["suite_ids"][0]]})
    assert pool.status_code == 201, pool.text
    body = pool.json()
    assert body["expense_categories"] == ["cam"] and body["deduct_excluded_recoveries"] is True

    # A category sits in one pool only
    clash = await client.post(url, json={"name": "Other", "expense_categories": ["cam", "insurance"]})
    assert clash.status_code == 422 and "CAM" in clash.json()["detail"]
    # Suites must be the valuation's
    other = await _setup_office_property(client)
    bad = await client.post(url, json={"name": "X", "excluded_suite_ids": [other["suite_ids"][0]]})
    assert bad.status_code == 422
    # Fixed area needs an area
    assert (await client.post(url, json={"name": "X", "denominator": "fixed_area"})).status_code == 422

    updated = await client.put(f"{url}/{body['id']}", json={
        "name": "CAM", "expense_categories": ["cam"], "denominator": "occupied_area",
        "minimum_occupancy_pct": "0.9"})
    assert updated.status_code == 200 and updated.json()["denominator"] == "occupied_area"
    assert len((await client.get(url)).json()) == 1
    assert (await client.delete(f"{url}/{body['id']}")).status_code == 204
    assert (await client.get(url)).json() == []


async def test_pool_changes_results_and_marks_them_stale(client: AsyncClient):
    ids = await _setup_office_property(client)
    val = await _valuation(client, ids)
    base = await _noi(client, val)
    pool = await client.post(f"{V}/{val}/recovery-pools", json={
        "name": "Taxes", "expense_categories": ["real_estate_taxes"], "denominator": "fixed_area",
        "fixed_area": "10000"})
    summary = (await client.get(f"{P}/summary")).json()
    assert next(r for r in summary if r["id"] == ids["property_id"])["primary_valuation"]["is_stale"] is True
    pooled = await _noi(client, val)
    assert pooled[0] > base[0]        # tenants share taxes over 10,000 SF rather than 15,000

    full = (await client.get(f"{V}/{val}/reports/full")).json()
    taxes = [r for r in full["recovery_audit"] if r["expense_category"] == "real_estate_taxes"]
    assert taxes and all(r["recovery_pool"] == pool.json()["name"] for r in taxes)
    assert {float(r["share_denominator_area"]) for r in taxes} == {10000.0}


async def test_frozen_valuation_verifies_after_a_pool_edit(client: AsyncClient):
    ids = await _setup_office_property(client)
    url = f"{V}/{ids['setup_valuation_id']}/recovery-pools"
    pool = (await client.post(url, json={"name": "Taxes", "expense_categories": ["real_estate_taxes"],
                                         "denominator": "fixed_area", "fixed_area": "10000"})).json()
    val = await _valuation(client, ids)
    await _noi(client, val)
    assert (await client.post(f"{V}/{val}/submit", json={"name": "A"})).status_code == 200
    # The frozen valuation's own pool is locked; the setup valuation's copy stays editable
    (own,) = (await client.get(f"{V}/{val}/recovery-pools")).json()
    assert (await client.put(f"{V}/{val}/recovery-pools/{own['id']}", json={
        "name": "Taxes", "expense_categories": ["real_estate_taxes"], "denominator": "property_area"})).status_code == 409
    assert (await client.put(f"{url}/{pool['id']}", json={
        "name": "Taxes", "expense_categories": ["real_estate_taxes"], "denominator": "property_area"})).status_code == 200
    check = (await client.post(f"{V}/{val}/verify")).json()
    assert check["matches"] is True and check["error"] is None, check


async def test_package_round_trip_remaps_excluded_suites(client: AsyncClient):
    ids = await _setup_office_property(client)
    await client.post(f"{V}/{ids['setup_valuation_id']}/recovery-pools", json={
        "name": "CAM", "expense_categories": ["cam"], "excluded_suite_ids": [ids["suite_ids"][0]]})
    val = await _valuation(client, ids)
    source = await _noi(client, val)

    package = (await client.get(f"{V}/{val}/package")).json()
    imported = (await client.post("/api/v1/valuation-packages/import", json=package)).json()
    (pool,) = (await client.get(f"{V}/{imported['valuation_id']}/recovery-pools")).json()
    new_suites = {s["id"] for s in (await client.get(f"{V}/{imported['valuation_id']}/suites")).json()}
    assert pool["excluded_suite_ids"] and set(pool["excluded_suite_ids"]) <= new_suites
    assert await _noi(client, imported["valuation_id"]) == source


async def test_deleting_an_excluded_suite_leaves_the_pool_usable(client: AsyncClient):
    ids = await _setup_office_property(client)
    vacant = ids["suite_ids"][2]
    url = f"{V}/{ids['setup_valuation_id']}/recovery-pools"
    pool = (await client.post(url, json={"name": "CAM", "expense_categories": ["cam"],
                                         "excluded_suite_ids": [vacant]})).json()
    assert (await client.delete(f"{V}/{ids['setup_valuation_id']}/suites/{vacant}")).status_code == 204
    val = await _valuation(client, ids)
    await _noi(client, val)
    # The form drops the missing suite; saving without it works
    assert (await client.put(f"{url}/{pool['id']}", json={"name": "CAM", "expense_categories": ["cam"],
                                                         "excluded_suite_ids": []})).status_code == 200
