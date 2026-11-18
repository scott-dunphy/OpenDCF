"""Readiness, home-screen summary, stale results, scenario duplication, valuation-owned hold period,
and valuation-owned seniors housing operating model, marina purchase price."""
import json

from httpx import AsyncClient

from tests.api.test_valuations_api import _drop_setup_valuation, _setup_office_property

V = "/api/v1/valuations"
P = "/api/v1/properties"


async def _valuation(client: AsyncClient, prop_id: str, **extra) -> dict:
    r = await client.post(f"{P}/{prop_id}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065", **extra,
    })
    assert r.status_code == 201
    return r.json()


async def test_empty_property_is_not_ready_and_run_is_refused(client: AsyncClient):
    prop = (await client.post(P, json={
        "name": "Empty", "property_type": "office", "total_area": "10000", "area_unit": "sf",
    })).json()
    val = await _valuation(client, prop["id"])
    readiness = (await client.get(f"{V}/{val['id']}/readiness")).json()
    assert readiness["ready"] is False
    assert {i["key"]: i["status"] for i in readiness["items"]}["space"] == "missing"

    run = await client.post(f"{V}/{val['id']}/run")
    assert run.status_code == 400
    assert "Not ready to run" in run.json()["detail"]


async def test_set_up_property_is_ready(client: AsyncClient):
    ids = await _setup_office_property(client)
    readiness = (await client.get(f"{V}/{ids['setup_valuation_id']}/readiness")).json()
    assert readiness["ready"] is True
    statuses = {i["key"]: i["status"] for i in readiness["items"]}
    assert statuses["space"] == "done" and statuses["expenses"] == "done"


async def test_summary_counts_each_property_once_and_hides_irr_without_price(client: AsyncClient):
    ids = await _setup_office_property(client)
    a = await _valuation(client, ids["property_id"], name="A")
    b = await _valuation(client, ids["property_id"], name="B", purchase_price="3000000")
    await _drop_setup_valuation(client, ids)
    await client.post(f"{V}/{a['id']}/run")
    await client.post(f"{V}/{b['id']}/run")

    rows = [r for r in (await client.get(f"{P}/summary")).json() if r["id"] == ids["property_id"]]
    assert len(rows) == 1
    row = rows[0]
    assert row["valuation_count"] == 2 and row["suite_count"] == 3
    primary = row["primary_valuation"]
    assert primary["id"] == b["id"]  # most recently run
    assert primary["irr"] is not None and primary["is_stale"] is False

    await client.post(f"{V}/{a['id']}/run")
    primary = next(r for r in (await client.get(f"{P}/summary")).json() if r["id"] == ids["property_id"])["primary_valuation"]
    assert primary["id"] == a["id"] and primary["irr"] is None


async def test_lease_edit_makes_results_stale_and_rerun_clears_it(client: AsyncClient):
    ids = await _setup_office_property(client)
    val = await _valuation(client, ids["property_id"])
    await client.post(f"{V}/{val['id']}/run")

    def primary(rows):
        return next(r for r in rows if r["id"] == ids["property_id"])["primary_valuation"]

    assert primary((await client.get(f"{P}/summary")).json())["is_stale"] is False

    # Renaming the property is cosmetic
    await client.put(f"{P}/{ids['property_id']}", json={"name": "Renamed"})
    assert primary((await client.get(f"{P}/summary")).json())["is_stale"] is False

    leases = (await client.get(f"{V}/{val['id']}/leases")).json()
    assert len(leases) == 2
    r = await client.put(f"/api/v1/leases/{leases[0]['id']}", json={"base_rent_per_unit": "31.00"})
    assert r.status_code == 200
    assert primary((await client.get(f"{P}/summary")).json())["is_stale"] is True

    await client.post(f"{V}/{val['id']}/run")
    assert primary((await client.get(f"{P}/summary")).json())["is_stale"] is False


async def test_engine_update_makes_results_stale_and_rerun_clears_it(client: AsyncClient, monkeypatch):
    import src.engine

    ids = await _setup_office_property(client)
    val = await _valuation(client, ids["property_id"])
    await client.post(f"{V}/{val['id']}/run")

    def primary(rows):
        return next(r for r in rows if r["id"] == ids["property_id"])["primary_valuation"]

    async def state():
        p = primary((await client.get(f"{P}/summary")).json())
        v = (await client.get(f"{V}/{val['id']}")).json()
        return p["is_stale"], p["stale_reason"], v["engine_outdated"], v["result_engine_version"]

    assert await state() == (False, None, False, src.engine.ENGINE_VERSION)

    monkeypatch.setattr(src.engine, "ENGINE_VERSION", src.engine.ENGINE_VERSION + 1)
    assert await state() == (True, "engine", True, src.engine.ENGINE_VERSION - 1)
    listed = (await client.get(f"{P}/{ids['property_id']}/valuations")).json()
    assert next(v for v in listed if v["id"] == val["id"])["engine_outdated"] is True

    await client.post(f"{V}/{val['id']}/run")
    assert await state() == (False, None, False, src.engine.ENGINE_VERSION)


async def test_frozen_valuation_is_not_flagged_for_rerun_after_engine_update(client: AsyncClient, monkeypatch):
    import src.engine

    ids = await _setup_office_property(client)
    val = await _valuation(client, ids["property_id"])
    await client.post(f"{V}/{val['id']}/run")
    r = await client.post(f"{V}/{val['id']}/submit", json={"name": "Analyst A"})
    assert r.status_code == 200
    monkeypatch.setattr(src.engine, "ENGINE_VERSION", src.engine.ENGINE_VERSION + 1)

    p = next(r for r in (await client.get(f"{P}/summary")).json() if r["id"] == ids["property_id"])
    assert p["primary_valuation"]["is_stale"] is False
    # Informational only: the UI points at Verify frozen result
    assert (await client.get(f"{V}/{val['id']}")).json()["engine_outdated"] is True

async def test_duplicate_copies_assumptions_not_results(client: AsyncClient):
    ids = await _setup_office_property(client)
    val = await _valuation(client, ids["property_id"], exit_cap_rate="0.07", purchase_price="2500000")
    await client.post(f"{V}/{val['id']}/run")
    r = await client.post(f"{V}/{val['id']}/duplicate")
    assert r.status_code == 201
    copy = r.json()
    assert copy["id"] != val["id"] and copy["name"] == "Base (copy)"
    assert float(copy["exit_cap_rate"]) == 0.07 and float(copy["purchase_price"]) == 2500000
    assert copy["status"] == "draft" and copy["result_npv"] is None


async def test_valuation_hold_period_overrides_property(client: AsyncClient):
    ids = await _setup_office_property(client)  # property: 10 years
    ten = await _valuation(client, ids["property_id"], name="10 yr")
    five = await _valuation(client, ids["property_id"], name="5 yr", analysis_period_months_override=60)
    r10 = (await client.post(f"{V}/{ten['id']}/run")).json()
    r5 = (await client.post(f"{V}/{five['id']}/run")).json()
    assert len(r10["annual_cash_flows"]) == 10
    assert len(r5["annual_cash_flows"]) == 5


async def test_seniors_operating_model_lives_on_valuation(client: AsyncClient):
    prop = (await client.post(P, json={
        "name": "Sunrise", "property_type": "seniors_housing", "total_area": "40", "area_unit": "unit",
        "analysis_start_date": "2026-01-01",
    })).json()
    model = {
        "unit_types": [{
            "name": "AL 1BR", "acuity": "assisted_living", "unit_type": "one_br", "count": 40, "avg_sf": "650",
            "monthly_base_fee": "5000", "stabilized_occupancy": "0.90",
        }],
        "expenses": [{"name": "Payroll", "category": "labor", "annual_fixed": "600000"}],
    }
    a = await _valuation(client, prop["id"], name="8%")
    assert (await client.get(f"{V}/{a['id']}/readiness")).json()["ready"] is False

    r = await client.put(f"{V}/{a['id']}", json={"seniors_housing_assumptions_json": json.dumps(model)})
    assert r.status_code == 200
    assert (await client.get(f"{V}/{a['id']}/readiness")).json()["ready"] is True

    # A new valuation starts from a copy of the latest one's model
    b = await _valuation(client, prop["id"], name="10%", discount_rate="0.10")
    assert json.loads(b["seniors_housing_assumptions_json"]) == model
    ra = await client.post(f"{V}/{a['id']}/run")
    rb = await client.post(f"{V}/{b['id']}/run")
    assert ra.status_code == 200 and rb.status_code == 200
    assert float(ra.json()["key_metrics"]["npv"]) > float(rb.json()["key_metrics"]["npv"])


async def test_marina_valuation_purchase_price_drives_irr(client: AsyncClient):
    prop = (await client.post(P, json={
        "name": "Harbor", "property_type": "marina", "total_area": "300", "area_unit": "unit",
        "analysis_start_date": "2026-01-01",
    })).json()
    cheap = await _valuation(client, prop["id"], name="Cheap", purchase_price="10000000")
    dear = await _valuation(client, prop["id"], name="Dear", purchase_price="20000000")
    r_cheap = (await client.post(f"{V}/{cheap['id']}/run")).json()
    r_dear = (await client.post(f"{V}/{dear['id']}/run")).json()
    assert float(r_cheap["key_metrics"]["irr"]) > float(r_dear["key_metrics"]["irr"])


async def test_another_valuations_model_does_not_make_a_run_ready(client: AsyncClient, db_session):
    from src.models.valuation import Valuation

    prop = (await client.post(P, json={
        "name": "Legacy", "property_type": "seniors_housing", "total_area": "40", "area_unit": "unit",
    })).json()
    old = await _valuation(client, prop["id"], name="Old")
    new = await _valuation(client, prop["id"], name="New")
    other = await db_session.get(Valuation, old["id"])
    other.seniors_housing_assumptions_json = json.dumps({"unit_types": []})
    await db_session.commit()

    # Each valuation is checked on its own model
    assert (await client.get(f"{V}/{old['id']}/readiness")).json()["ready"] is True
    assert (await client.get(f"{V}/{new['id']}/readiness")).json()["ready"] is False
    run = await client.post(f"{V}/{new['id']}/run")
    assert run.status_code == 400
    assert "Not ready to run" in run.json()["detail"]


async def test_refused_run_leaves_completed_valuation_and_results_untouched(
    client: AsyncClient, db_session, monkeypatch
):
    from src.api import valuations as valuations_api
    from src.models.valuation import Valuation
    from src.services.readiness import Readiness, ReadinessItem

    ids = await _setup_office_property(client)
    val = await _valuation(client, ids["property_id"], purchase_price="3000000")
    assert (await client.post(f"{V}/{val['id']}/run")).status_code == 200
    before = (await client.get(f"{V}/{val['id']}")).json()
    assert before["status"] == "completed" and before["result_npv"] is not None

    async def not_ready(db, prop, valuation=None):
        return Readiness(ready=False, items=[ReadinessItem(
            key="space", label="Rent roll", status="missing", detail="Add suites", section="rent-roll",
        )])

    monkeypatch.setattr(valuations_api, "assess_readiness", not_ready)
    run = await client.post(f"{V}/{val['id']}/run")
    assert run.status_code == 400
    assert run.json()["detail"] == "Not ready to run: Add suites"

    after = (await client.get(f"{V}/{val['id']}")).json()
    assert after == before
    row = next(r for r in (await client.get(f"{P}/summary")).json() if r["id"] == ids["property_id"])
    assert row["primary_valuation"]["id"] == val["id"]


async def test_refused_run_on_never_run_valuation_records_the_reason(client: AsyncClient):
    prop = (await client.post(P, json={
        "name": "Empty", "property_type": "office", "total_area": "10000", "area_unit": "sf",
    })).json()
    val = await _valuation(client, prop["id"])
    assert (await client.post(f"{V}/{val['id']}/run")).status_code == 400
    stored = (await client.get(f"{V}/{val['id']}")).json()
    assert stored["status"] == "failed"
    assert stored["error_message"].startswith("Not ready to run")
