"""Merging duplicate properties: valuations and property-level rows move to one property."""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.models.document import SourceDocument, ValuationDocument
from src.services import property_merge
from tests.api.test_comparables_api import _sale
from tests.api.test_loans_api import LOAN
from tests.api.test_valuation_review_api import _reports
from tests.api.test_valuations_api import _setup_office_property

V = "/api/v1/valuations"
P = "/api/v1/properties"


async def _valuation(client: AsyncClient, pid: str, name: str, **extra) -> dict:
    r = await client.post(f"{P}/{pid}/valuations", json={
        "name": name, "discount_rate": "0.08", "exit_cap_rate": "0.065", **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def _npv(client: AsyncClient, val_id: str) -> str:
    r = await client.post(f"{V}/{val_id}/run")
    assert r.status_code == 200, r.text
    return (await client.get(f"{V}/{val_id}")).json()["result_npv"]


async def _setup(client: AsyncClient, db_session) -> dict:
    target = (await _setup_office_property(client))["property_id"]
    source = (await _setup_office_property(client))["property_id"]
    draft = await _valuation(client, source, "Draft")
    approved = await _valuation(client, source, "Q3 2026", analysis_start_date_override="2026-10-01")
    assert (await client.post(f"{V}/{approved['id']}/submit", json={"name": "A"})).status_code == 200
    assert (await client.post(f"{V}/{approved['id']}/approve", json={"name": "R"})).status_code == 200
    shared, own = await _sale(client, 1), await _sale(client, 2)
    for pid, sale in ((target, shared), (source, shared), (source, own)):
        r = await client.put(f"{P}/{pid}/comparable-sales/{sale['id']}", json={"weight": "1"})
        assert r.status_code in (200, 201), r.text
    loan = (await client.post("/api/v1/loans", json={**LOAN, "property_id": source})).json()
    pf = (await client.post("/api/v1/portfolios", json={"name": "Fund", "property_ids": [source]})).json()
    doc = SourceDocument(sha256="a" * 64, original_filename="rr.pdf", media_type="application/pdf",
                         byte_size=1, storage_key="k1")
    db_session.add(doc)
    await db_session.flush()
    db_session.add(ValuationDocument(valuation_id=draft["id"], document_id=doc.id))
    await db_session.commit()
    return {"target": target, "source": source, "draft": draft, "approved": approved, "shared": shared,
            "own": own, "loan": loan, "pf": pf}


async def test_merge_moves_everything_and_frozen_valuations_still_verify(client: AsyncClient, db_session):
    s = await _setup(client, db_session)
    draft_before = await _npv(client, s["draft"]["id"])
    stamped = (await client.get(f"{V}/{s['draft']['id']}")).json()["inputs_updated_at"]
    frozen_reports = await _reports(client, s["approved"]["id"])

    dupes = (await client.get(f"{P}/duplicates")).json()
    assert [{p["id"] for p in g["properties"]} for g in dupes] == [{s["target"], s["source"]}]

    r = await client.post(f"{P}/{s['target']}/merge", json={"source_ids": [s["source"]]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {v["id"] for v in body["valuations"]} >= {s["draft"]["id"], s["approved"]["id"]}
    assert body["merged"][0]["differences"] == {}
    assert body["dropped"] == {"comparable_selections": 1}
    assert body["moved"]["valuations"] == 3 and body["moved"]["mortgage_loans"] == 1

    assert (await client.get(f"{P}/{s['source']}")).status_code == 404
    names = {v["name"] for v in (await client.get(f"{P}/{s['target']}/valuations")).json()}
    assert {"Draft", "Q3 2026"} <= names
    # The frozen valuation is untouched and reproduces its approved value
    check = (await client.post(f"{V}/{s['approved']['id']}/verify")).json()
    assert check["matches"] is True and check["error"] is None, check
    assert await _reports(client, s["approved"]["id"]) == frozen_reports
    frozen = (await client.get(f"{V}/{s['approved']['id']}/frozen-inputs")).json()
    assert frozen["property"]["id"] == s["target"]
    # Drafts value the same and are not marked stale
    assert (await client.get(f"{V}/{s['draft']['id']}")).json()["inputs_updated_at"] == stamped
    assert await _npv(client, s["draft"]["id"]) == draft_before
    # Suites follow their valuation
    suites = (await client.get(f"{V}/{s['draft']['id']}/suites")).json()
    assert {x["property_id"] for x in suites} == {s["target"]}
    # Property-level rows
    assert (await client.get(f"/api/v1/loans/{s['loan']['id']}")).json()["property_id"] == s["target"]
    pf = (await client.get(f"/api/v1/portfolios/{s['pf']['id']}")).json()
    assert [p["id"] for p in pf["properties"]] == [s["target"]]
    picked = (await client.get(f"{P}/{s['target']}/comparable-sales")).json()
    assert {x["sale"]["id"] if "sale" in x else x["sale_id"] for x in picked} == {s["shared"]["id"], s["own"]["id"]}
    vd = (await db_session.execute(select(ValuationDocument))).scalar_one()
    assert vd.valuation_id == s["draft"]["id"]
    # As-of portfolio runs still value the moved approved valuation from its snapshot
    run = await client.post(f"/api/v1/portfolios/{s['pf']['id']}/runs", json={"as_of": "2026-12-31"})
    assert run.status_code == 201, run.text
    row = next(p for p in run.json()["scenarios"][0]["properties"] if p["property_id"] == s["target"])
    assert row["valuation_id"] == s["approved"]["id"]
    assert Decimal(row["value"]) == Decimal(check["stored_npv"])
    assert (await client.get(f"{P}/duplicates")).json() == []


async def test_merge_refuses_other_types_and_bad_ids(client: AsyncClient):
    office = (await _setup_office_property(client))["property_id"]
    retail = (await client.post(P, json={
        "name": "Strip", "property_type": "retail", "total_area": "15000", "area_unit": "sf",
        "analysis_start_date": "2025-01-01"})).json()["id"]
    r = await client.post(f"{P}/{office}/merge", json={"source_ids": [retail]})
    assert r.status_code == 422 and "same type" in r.json()["detail"]
    assert (await client.post(f"{P}/{office}/merge", json={"source_ids": [office]})).status_code == 422
    assert (await client.post(f"{P}/{office}/merge", json={"source_ids": []})).status_code == 422
    assert (await client.post(f"{P}/{office}/merge", json={"source_ids": ["nope"]})).status_code == 404
    assert (await client.get(f"{P}/{retail}")).status_code == 200


async def test_merge_refuses_an_appraisal_import_workspace(client: AsyncClient):
    office = (await _setup_office_property(client))["property_id"]
    workspace = (await client.post(P, json={
        "name": "Office", "property_type": "office", "total_area": "15000", "area_unit": "sf",
        "analysis_start_date": "2025-01-01", "external_id": "__appraisal_intake__:job"})).json()["id"]
    for target, source in ((office, workspace), (workspace, office)):
        r = await client.post(f"{P}/{target}/merge", json={"source_ids": [source]})
        assert r.status_code == 422 and "appraisal import" in r.json()["detail"]
    assert (await client.get(f"{P}/{workspace}")).status_code == 200


async def test_merge_reports_engine_field_differences(client: AsyncClient):
    a = (await _setup_office_property(client))["property_id"]
    b = (await _setup_office_property(client))["property_id"]
    await client.put(f"{P}/{b}", json={"total_area": "16000"})
    r = await client.post(f"{P}/{a}/merge", json={"source_ids": [b]})
    assert r.status_code == 200
    assert r.json()["merged"][0]["differences"] == {"total_area": ["16000.0000", "15000.0000"]}


async def test_merge_is_all_or_nothing(client: AsyncClient, db_session, monkeypatch):
    s = await _setup(client, db_session)
    real = property_merge._property_refs
    calls = {"n": 0}

    def refs_then_fail():
        calls["n"] += 1
        if calls["n"] == 2:  # after every row has moved, before the sources are deleted
            raise RuntimeError("boom")
        return real()

    monkeypatch.setattr(property_merge, "_property_refs", refs_then_fail)
    with pytest.raises(RuntimeError):
        await client.post(f"{P}/{s['target']}/merge", json={"source_ids": [s["source"]]})
    assert (await client.get(f"{P}/{s['source']}")).status_code == 200
    names = {v["name"] for v in (await client.get(f"{P}/{s['source']}/valuations")).json()}
    assert {"Draft", "Q3 2026"} <= names
    assert (await client.get(f"/api/v1/loans/{s['loan']['id']}")).json()["property_id"] == s["source"]
    suites = (await client.get(f"{V}/{s['draft']['id']}/suites")).json()
    assert {x["property_id"] for x in suites} == {s["source"]}


async def test_two_sources_sharing_a_comp_and_portfolio(client: AsyncClient):
    target, a, b = [(await _setup_office_property(client))["property_id"] for _ in range(3)]
    sale = await _sale(client, 1)
    for pid in (a, b):
        r = await client.put(f"{P}/{pid}/comparable-sales/{sale['id']}", json={"weight": "1"})
        assert r.status_code in (200, 201), r.text
    pf = (await client.post("/api/v1/portfolios", json={"name": "Fund", "property_ids": [a, b]})).json()
    r = await client.post(f"{P}/{target}/merge", json={"source_ids": [a, b]})
    assert r.status_code == 200, r.text
    assert r.json()["dropped"] == {"comparable_selections": 1, "portfolio_properties": 1}
    assert len((await client.get(f"{P}/{target}/comparable-sales")).json()) == 1
    assert [p["id"] for p in (await client.get(f"/api/v1/portfolios/{pf['id']}")).json()["properties"]] == [target]
