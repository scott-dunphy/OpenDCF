"""Market leasing profiles belong to a valuation (each valuation has its own market view)."""
from httpx import AsyncClient

from tests.api.test_valuations_api import _setup_office_property

V = "/api/v1/valuations"
BODY = {"discount_rate": "0.08", "exit_cap_rate": "0.065"}


async def _profiles(client: AsyncClient, val_id: str) -> list[dict]:
    return (await client.get(f"{V}/{val_id}/market-profiles")).json()


async def test_new_valuation_copies_the_latest_and_edits_stay_separate(client: AsyncClient):
    ids = await _setup_office_property(client)
    pid = ids["property_id"]
    a = (await client.post(f"/api/v1/properties/{pid}/valuations", json={**BODY, "name": "A"})).json()
    [pa] = await _profiles(client, a["id"])
    assert pa["valuation_id"] == a["id"] and float(pa["market_rent_per_unit"]) == 35.0

    b = (await client.post(f"{V}/{a['id']}/duplicate")).json()
    [pb] = await _profiles(client, b["id"])
    assert pb["id"] != pa["id"] and float(pb["market_rent_per_unit"]) == 35.0

    # Editing B's market leaves A's alone, and only B needs a re-run
    ra = (await client.post(f"{V}/{a['id']}/run")).json()["key_metrics"]["npv"]
    await client.post(f"{V}/{b['id']}/run")
    assert (await client.put(f"{V}/{b['id']}/market-profiles/{pb['id']}",
                             json={"market_rent_per_unit": "50.00"})).status_code == 200
    assert float((await _profiles(client, a["id"]))[0]["market_rent_per_unit"]) == 35.0
    vals = {v["id"]: v for v in (await client.get(f"/api/v1/properties/{pid}/valuations")).json()}
    assert vals[b["id"]]["inputs_updated_at"] is not None and vals[a["id"]]["inputs_updated_at"] is None
    rb = (await client.post(f"{V}/{b['id']}/run")).json()["key_metrics"]["npv"]
    assert float(rb) > float(ra)
    assert (await client.post(f"{V}/{a['id']}/run")).json()["key_metrics"]["npv"] == ra

    # Deleting a valuation deletes its market leasing only
    assert (await client.delete(f"{V}/{b['id']}")).status_code == 204
    assert len(await _profiles(client, a["id"])) == 1


async def test_space_type_unique_per_valuation_and_frozen_profiles_locked(client: AsyncClient):
    ids = await _setup_office_property(client)
    val = (await client.post(f"/api/v1/properties/{ids['property_id']}/valuations",
                             json={**BODY, "name": "A"})).json()
    dup = await client.post(f"{V}/{val['id']}/market-profiles", json={"space_type": "office", "market_rent_per_unit": "1"})
    assert dup.status_code == 409
    assert (await client.post(f"{V}/{val['id']}/submit", json={"name": "A"})).status_code == 200
    [p] = await _profiles(client, val["id"])
    assert (await client.put(f"{V}/{val['id']}/market-profiles/{p['id']}", json={"downtime_months": 1})).status_code == 409
    assert (await client.delete(f"{V}/{val['id']}/market-profiles/{p['id']}")).status_code == 409
    added = await client.post(f"{V}/{val['id']}/market-profiles", json={"space_type": "retail", "market_rent_per_unit": "1"})
    assert added.status_code == 409


async def test_readiness_reads_the_valuation_market(client: AsyncClient):
    ids = await _setup_office_property(client)
    setup = ids["setup_valuation_id"]
    items = {i["key"]: i for i in (await client.get(f"{V}/{setup}/readiness")).json()["items"]}
    assert items["market"]["status"] == "done" and items["market"]["valuation_id"] == setup
    [p] = await _profiles(client, setup)
    await client.delete(f"{V}/{setup}/market-profiles/{p['id']}")
    items = {i["key"]: i for i in (await client.get(f"{V}/{setup}/readiness")).json()["items"]}
    assert items["market"]["status"] == "warning" and "office" in items["market"]["detail"]


def test_snapshots_from_before_valuation_owned_market_still_restore():
    from src.services.valuation_snapshot import _upgraded

    old = {"valuation_id": "v1", "tables": {
        "market_leasing_profiles": [{"id": "m1", "property_id": "p1", "space_type": "retail"}],
        "suites": [{"id": "s1", "space_type": "office", "market_leasing_profile_id": "m1"},
                   {"id": "s2", "space_type": "office", "market_leasing_profile_id": None}],
    }}
    tables = _upgraded(old)
    assert tables["market_leasing_profiles"][0]["valuation_id"] == "v1"
    assert [s["market_space_type"] for s in tables["suites"]] == ["retail", None]


async def test_readiness_checks_each_valuation_and_names_the_relet_type(client: AsyncClient):
    ids = await _setup_office_property(client)
    pid, setup = ids["property_id"], ids["setup_valuation_id"]
    other = (await client.post(f"/api/v1/properties/{pid}/valuations", json={**BODY, "name": "B"})).json()
    [p] = await _profiles(client, other["id"])
    await client.delete(f"{V}/{other['id']}/market-profiles/{p['id']}")

    def market(body):
        return {i["key"]: i for i in body["items"]}["market"]

    # B has no office profile; the setup valuation still does
    b = market((await client.get(f"{V}/{other['id']}/readiness")).json())
    assert b["valuation_id"] == other["id"] and b["status"] == "warning"
    picked = market((await client.get(f"{V}/{setup}/workspace")).json()["readiness"])
    assert picked["valuation_id"] == setup and picked["status"] == "done"

    # A suite re-leased as another type is reported under that type
    await client.put(f"{V}/{setup}/suites/{ids['suite_ids'][0]}", json={"market_space_type": "retail_bank"})
    picked = market((await client.get(f"{V}/{setup}/readiness")).json())
    assert "Retail" in picked["detail"] or "retail_bank" in picked["detail"]
    assert "office" not in picked["detail"].lower()


async def test_profile_edit_blocks_sensitivity_until_rerun(client: AsyncClient):
    ids = await _setup_office_property(client)
    val = (await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={**BODY, "name": "A"})).json()
    await client.post(f"{V}/{val['id']}/run")
    assert (await client.get(f"{V}/{val['id']}/reports/sensitivity")).status_code == 200
    [p] = await _profiles(client, val["id"])
    await client.put(f"{V}/{val['id']}/market-profiles/{p['id']}", json={"market_rent_per_unit": "50"})
    blocked = await client.get(f"{V}/{val['id']}/reports/sensitivity")
    assert blocked.status_code == 400 and "Inputs changed" in blocked.text
    await client.post(f"{V}/{val['id']}/run")
    assert (await client.get(f"{V}/{val['id']}/reports/sensitivity")).status_code == 200


async def test_package_marked_frozen_imports_as_a_draft(client: AsyncClient):
    ids = await _setup_office_property(client)
    package = (await client.get(f"{V}/{ids['setup_valuation_id']}/package")).json()
    package["valuation"]["review_status"] = "approved"  # as packages exported before the export guard
    imported = await client.post("/api/v1/valuation-packages/import", json=package)
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["valuation_id"]
    assert (await client.get(f"{V}/{new_id}")).json()["review_status"] == "draft"
    assert len(await _profiles(client, new_id)) == 1


async def test_workbook_import_always_creates_a_valuation_holding_the_model(client: AsyncClient):
    from tests.api.test_imports_api import _preview_template

    job = await _preview_template(client)
    commit = await client.post(f"/api/v1/imports/{job['id']}/commit", json={"create_valuations": False})
    assert commit.status_code in (200, 201), commit.text
    pid = commit.json()["created_property_ids"][0]
    (val,) = (await client.get(f"/api/v1/properties/{pid}/valuations")).json()
    assert (await client.get(f"{V}/{val['id']}/suites")).json()
