"""Each valuation owns its whole model (docs/valuation-owned-inputs-plan.md)."""
from httpx import AsyncClient
from sqlalchemy import func, select

from src.models.property import Property, Suite
from src.models.valuation import Valuation
from tests.api.test_valuations_api import _setup_office_property

V = "/api/v1/valuations"


async def _own_valuation(client: AsyncClient, ids: dict, name: str = "Base") -> str:
    r = await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
        "name": name, "discount_rate": "0.08", "exit_cap_rate": "0.065"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _npv(client: AsyncClient, val_id: str) -> str:
    r = await client.post(f"{V}/{val_id}/run")
    assert r.status_code == 200, r.text
    return r.json()["key_metrics"]["npv"]


async def test_new_valuation_copies_the_newest_model_with_new_ids(client: AsyncClient):
    ids = await _setup_office_property(client)
    val = await _own_valuation(client, ids)
    suites = (await client.get(f"{V}/{val}/suites")).json()
    assert sorted(s["suite_name"] for s in suites) == ["Suite 100", "Suite 200", "Suite 300"]
    assert not {s["id"] for s in suites} & set(ids["suite_ids"])
    assert len((await client.get(f"{V}/{val}/leases")).json()) == 2
    assert len((await client.get(f"{V}/{val}/expenses")).json()) == 4
    assert len((await client.get(f"{V}/{val}/market-profiles")).json()) == 1
    tenants = (await client.get(f"{V}/{val}/tenants")).json()
    assert [t["name"] for t in tenants] == ["Acme Corp"] and tenants[0]["id"] != ids["tenant_id"]
    lease = next(l for l in (await client.get(f"{V}/{val}/leases")).json() if l["tenant_id"])
    assert lease["tenant_id"] == tenants[0]["id"]  # references point at the copy's own rows


async def test_duplicate_is_independent_of_its_source(client: AsyncClient):
    ids = await _setup_office_property(client)
    base = await _own_valuation(client, ids)
    before = await _npv(client, base)
    copy = await client.post(f"{V}/{base}/duplicate")
    assert copy.status_code == 201, copy.text
    copy_id = copy.json()["id"]

    lease = (await client.get(f"{V}/{copy_id}/leases")).json()[0]
    assert (await client.put(f"/api/v1/leases/{lease['id']}", json={"base_rent_per_unit": "60.00"})).status_code == 200
    assert (await client.post(f"{V}/{copy_id}/expenses", json={
        "category": "utilities", "base_year_amount": "40000"})).status_code == 201

    assert await _npv(client, base) == before
    assert await _npv(client, copy_id) != before
    assert len((await client.get(f"{V}/{base}/expenses")).json()) == 4


async def test_roll_forward_moves_the_start_and_lists_lease_changes(client: AsyncClient):
    ids = await _setup_office_property(client)
    base = await _own_valuation(client, ids)
    suite = next(s for s in (await client.get(f"{V}/{base}/suites")).json() if s["suite_name"] == "Suite 300")
    assert (await client.post(f"/api/v1/suites/{suite['id']}/leases", json={
        "lease_start_date": "2024-01-01", "lease_end_date": "2025-02-28", "base_rent_per_unit": "28",
        "recovery_type": "nnn"})).status_code == 201

    r = await client.post(f"{V}/{base}/roll-forward", json={"period": "quarter"})
    assert r.status_code == 201, r.text
    body = r.json()
    rolled = body["valuation"]
    assert rolled["analysis_start_date_override"] == "2025-04-01"
    assert rolled["prior_valuation_id"] == base and rolled["review_status"] == "draft"
    assert [(l["suite_name"], l["lease_end_date"]) for l in body["expired_leases"]] == [("Suite 300", "2025-02-28")]
    assert body["started_leases"] == []
    assert len((await client.get(f"{V}/{rolled['id']}/leases")).json()) == 3
    assert (await client.post(f"{V}/{rolled['id']}/run")).status_code == 200


async def test_deleting_a_valuation_deletes_only_its_model(client: AsyncClient, db_session):
    ids = await _setup_office_property(client)
    val = await _own_valuation(client, ids)
    assert (await client.delete(f"{V}/{val}")).status_code == 204
    left = (await db_session.execute(select(Suite.valuation_id, func.count()).group_by(Suite.valuation_id))).all()
    assert left == [(ids["setup_valuation_id"], 3)]


async def test_import_can_add_a_valuation_to_an_existing_property(client: AsyncClient, db_session):
    from src.services.appraisal_reconstruction import build_plan, materialize_plan

    ids = await _setup_office_property(client)
    source = await db_session.get(Valuation, ids["setup_valuation_id"])
    prop = await db_session.get(Property, ids["property_id"])
    plan, _ = await build_plan(db_session, source, [])
    plan["target_property_id"] = prop.id
    rebuilt_prop, rebuilt = await materialize_plan(db_session, plan, prop)
    await db_session.commit()

    assert rebuilt_prop.id == prop.id and rebuilt.property_id == prop.id
    assert (await db_session.execute(select(func.count()).select_from(Property))).scalar() == 1
    assert len((await client.get(f"{V}/{rebuilt.id}/suites")).json()) == 3
    assert await _npv(client, rebuilt.id) == await _npv(client, ids["setup_valuation_id"])


async def test_snapshot_from_before_valuation_owned_inputs_restores(client: AsyncClient, db_session):
    """A frozen snapshot written when inputs were property-owned (no valuation_id on its rows,
    operating models and dates on the property) still rebuilds and reproduces its value."""
    from src.services.valuation_service import ValuationService
    from src.services.valuation_snapshot import capture, restored

    ids = await _setup_office_property(client)
    val = await _own_valuation(client, ids)
    npv = await _npv(client, val)
    valuation = await db_session.get(Valuation, val)
    snapshot = await capture(db_session, valuation)
    for name, rows in snapshot["tables"].items():
        if name != "market_leasing_profiles":
            for row in rows:
                row.pop("valuation_id", None)
    for row in snapshot["tables"]["valuations"]:
        for key in ("self_storage_assumptions_json", "prior_valuation_id",
                    "analysis_start_date_override", "analysis_period_months_override"):
            row.pop(key, None)

    async with restored(snapshot) as session:
        result = await ValuationService(session).execute_valuation(val)
    assert str(result.key_metrics.npv) == npv


async def test_storage_conversion_refuses_while_a_sibling_uses_the_unit_rent_roll(client: AsyncClient):
    prop = (await client.post("/api/v1/properties", json={
        "name": "Storage", "property_type": "self_storage", "total_area": "2", "area_unit": "unit",
        "analysis_start_date": "2026-01-01"})).json()
    first = (await client.post(f"/api/v1/properties/{prop['id']}/valuations", json={
        "name": "A", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()["id"]
    assert (await client.post(f"{V}/{first}/suites", json={
        "suite_name": "10x10", "area": "2", "space_type": "10x10"})).status_code == 201
    second = (await client.post(f"/api/v1/properties/{prop['id']}/valuations", json={
        "name": "B", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()["id"]
    r = await client.post(f"{V}/{second}/self-storage/convert-rent-roll")
    assert r.status_code == 409 and "'A'" in r.text
