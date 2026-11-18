import json

from httpx import AsyncClient

from src.config import settings
from src.models.document import ExtractedFact
from src.models.property import Property
from src.models.valuation import Valuation
from tests.api.test_valuations_api import _setup_office_property


async def test_dashboard_can_create_hidden_appraisal_import_workspace(
    client: AsyncClient, db_session
):
    response = await client.post("/api/v1/appraisal-import-workspaces", json={})

    assert response.status_code == 201
    payload = response.json()
    prop = await db_session.get(Property, payload["property_id"])
    valuation = await db_session.get(Valuation, payload["valuation_id"])
    assert prop is not None
    assert prop.external_id.startswith("__appraisal_intake__:")
    assert valuation is not None
    assert valuation.property_id == prop.id
    assert valuation.name == "AI Appraisal Import"


async def test_document_intelligence_status_reports_missing_anthropic_key(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    response = await client.get("/api/v1/document-intelligence/status")

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert "ANTHROPIC_API_KEY" in response.json()["message"]


async def test_document_content_preview_and_fact_value_review(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "documents"))
    ids = await _setup_office_property(client)
    valuation = (
        await client.post(
            f"/api/v1/properties/{ids['property_id']}/valuations",
            json={"name": "Intake", "discount_rate": "0.08", "exit_cap_rate": "0.065"},
        )
    ).json()
    uploaded = await client.post(
        f"/api/v1/valuations/{valuation['id']}/documents",
        files={"files": ("lease.txt", b"Lease evidence", "text/plain")},
    )
    assert uploaded.status_code == 201
    document = uploaded.json()[0]

    preview = await client.get(
        f"/api/v1/valuations/{valuation['id']}/documents/{document['id']}/content"
    )
    assert preview.status_code == 200
    assert preview.content == b"Lease evidence"
    assert preview.headers["content-type"].startswith("text/plain")

    fact = ExtractedFact(
        valuation_id=valuation["id"],
        document_id=document["id"],
        field_path="lease.base_rent_per_unit",
        value_json=json.dumps("10"),
        status="proposed",
    )
    db_session.add(fact)
    await db_session.commit()
    reviewed = await client.patch(
        f"/api/v1/valuations/{valuation['id']}/facts/{fact.id}",
        json={"status": "accepted", "value": "12"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "accepted"
    assert reviewed.json()["value"] == "12"


async def test_bulk_fact_review_and_review_queue_deduplicate(
    client: AsyncClient, db_session
):
    ids = await _setup_office_property(client)
    valuation = (
        await client.post(
            f"/api/v1/properties/{ids['property_id']}/valuations",
            json={"name": "Review", "discount_rate": "0.08", "exit_cap_rate": "0.065"},
        )
    ).json()
    document_id = "doc-review-test"
    from src.models.document import SourceDocument, ValuationDocument

    document = SourceDocument(
        id=document_id,
        sha256="a" * 64,
        original_filename="appraisal.pdf",
        media_type="application/pdf",
        byte_size=10,
        storage_key="aa/test",
        status="processed",
        document_type="appraisal",
    )
    db_session.add(document)
    await db_session.flush()
    db_session.add(ValuationDocument(valuation_id=valuation["id"], document_id=document_id))
    for _ in range(2):
        db_session.add(
            ExtractedFact(
                valuation_id=valuation["id"],
                document_id=document_id,
                field_path="property.total_area",
                value_json=json.dumps(50000),
                page_number=7,
                confidence=0.99,
            )
        )
    await db_session.commit()

    review = await client.get(f"/api/v1/valuations/{valuation['id']}/document-review")
    assert len(review.json()["facts"]) == 1
    bulk = await client.post(
        f"/api/v1/valuations/{valuation['id']}/facts/bulk-review",
        json={"status": "accepted"},
    )
    assert bulk.status_code == 200
    assert bulk.json()["updated"] == 2


async def test_model_is_built_from_rent_roll_and_operating_statement_without_appraisal(
    client: AsyncClient, db_session, monkeypatch
):
    from src.api import reconstructions
    from src.models.document import SourceDocument, ValuationDocument

    workspace = (await client.post("/api/v1/appraisal-import-workspaces", json={})).json()
    valuation_id = workspace["valuation_id"]
    for doc_id, doc_type, field_path, value in (
        ("doc-rent-roll", "rent_roll", "leases[].tenant_name", "Acme"),
        ("doc-t12", "operating_statement", "expenses.real_estate_taxes", 120000),
        ("doc-junk", "other", "other.note", "ignored"),
    ):
        db_session.add(
            SourceDocument(
                id=doc_id,
                sha256=doc_id.ljust(64, "0"),
                original_filename=f"{doc_id}.pdf",
                media_type="application/pdf",
                byte_size=10,
                storage_key=f"aa/{doc_id}",
                status="processed",
                document_type=doc_type,
                relevant=doc_type != "other",
            )
        )
        await db_session.flush()
        db_session.add(ValuationDocument(valuation_id=valuation_id, document_id=doc_id))
        db_session.add(
            ExtractedFact(
                valuation_id=valuation_id,
                document_id=doc_id,
                field_path=field_path,
                value_json=json.dumps(value),
                status="accepted",
            )
        )
    await db_session.commit()

    seen = {}

    def fake_structure(plan, facts, document_types):
        seen["sources"] = {document_types[f.document_id] for f in facts}
        plan["expenses"] = [
            {"category": "real_estate_taxes", "base_year_amount": 120000, "growth_rate_pct": 0.03}
        ]
        plan["suites"] = [{"source_id": "s1", "suite_name": "100", "area": 1, "space_type": "office"}]
        plan["tenants"] = [{"source_id": "t1", "name": "Acme"}]
        plan["leases"] = [
            {
                "source_id": "l1",
                "source_suite_id": "s1",
                "source_tenant_id": "t1",
                "lease_start_date": "2025-01-01",
                "lease_end_date": "2030-12-31",
                "base_rent_per_unit": 30,
            }
        ]
        return plan

    monkeypatch.setattr(reconstructions, "structure_plan_with_anthropic", fake_structure)
    response = await client.post(
        f"/api/v1/valuations/{valuation_id}/appraisal-reconstructions", json={}
    )

    assert response.status_code == 201, response.text
    assert seen["sources"] == {"rent_roll", "operating_statement"}

    created = await client.post(
        f"/api/v1/appraisal-reconstructions/{response.json()['id']}/materialize"
    )
    assert created.status_code == 200, created.text
    new_valuation_id = created.json()["rebuilt_valuation_id"]
    documents = (await client.get(f"/api/v1/valuations/{new_valuation_id}/documents")).json()
    assert {d["id"] for d in documents} == {"doc-rent-roll", "doc-t12", "doc-junk"}


async def test_building_the_model_requires_a_processed_document(client: AsyncClient):
    workspace = (await client.post("/api/v1/appraisal-import-workspaces", json={})).json()
    response = await client.post(
        f"/api/v1/valuations/{workspace['valuation_id']}/appraisal-reconstructions", json={}
    )
    assert response.status_code == 409


async def _workspace_with_document(client, db_session, doc_id="doc-ws"):
    from src.models.document import SourceDocument, ValuationDocument

    workspace = (await client.post("/api/v1/appraisal-import-workspaces", json={})).json()
    db_session.add(
        SourceDocument(
            id=doc_id,
            sha256=doc_id.ljust(64, "1"),
            original_filename=f"{doc_id}.pdf",
            media_type="application/pdf",
            byte_size=10,
            storage_key=f"bb/{doc_id}",
            status="processed",
            document_type="other",
            relevant=False,
        )
    )
    await db_session.flush()
    db_session.add(ValuationDocument(valuation_id=workspace["valuation_id"], document_id=doc_id))
    db_session.add(
        ExtractedFact(
            valuation_id=workspace["valuation_id"],
            document_id=doc_id,
            field_path="expenses.insurance",
            value_json="18000",
        )
    )
    await db_session.commit()
    return workspace


async def test_document_can_be_reclassified_and_removed(client: AsyncClient, db_session):
    workspace = await _workspace_with_document(client, db_session)
    base = f"/api/v1/valuations/{workspace['valuation_id']}/documents/doc-ws"

    reclassified = await client.patch(base, json={"document_type": "operating_statement", "relevant": True})
    assert reclassified.status_code == 200
    assert reclassified.json()["document_type"] == "operating_statement"
    assert reclassified.json()["relevant"] is True
    assert (await client.patch(base, json={"document_type": "nonsense"})).status_code == 422

    assert (await client.delete(base)).status_code == 204
    review = (await client.get(f"/api/v1/valuations/{workspace['valuation_id']}/document-review")).json()
    assert review["facts"] == []
    assert (await client.get(f"/api/v1/valuations/{workspace['valuation_id']}/documents")).json() == []


async def test_unfinished_imports_are_listed_and_can_be_discarded(client: AsyncClient, db_session):
    empty = (await client.post("/api/v1/appraisal-import-workspaces", json={})).json()
    workspace = await _workspace_with_document(client, db_session, "doc-unfinished")

    listed = (await client.get("/api/v1/appraisal-import-workspaces")).json()
    assert [w["valuation_id"] for w in listed] == [workspace["valuation_id"]]
    assert listed[0]["documents"] == ["doc-unfinished.pdf"]
    assert listed[0]["model_ready"] is False

    assert (await client.delete(f"/api/v1/appraisal-import-workspaces/{workspace['valuation_id']}")).status_code == 204
    assert await db_session.get(Property, workspace["property_id"]) is None
    assert (await client.delete(f"/api/v1/appraisal-import-workspaces/{empty['valuation_id']}")).status_code == 204


async def test_regular_valuation_cannot_be_discarded_as_workspace(client: AsyncClient):
    ids = await _setup_office_property(client)
    valuation = (
        await client.post(
            f"/api/v1/properties/{ids['property_id']}/valuations",
            json={"name": "Keep", "discount_rate": "0.08", "exit_cap_rate": "0.065"},
        )
    ).json()
    response = await client.delete(f"/api/v1/appraisal-import-workspaces/{valuation['id']}")
    assert response.status_code == 409


async def test_low_coverage_builds_and_rent_roll_date_sets_analysis_start(
    client: AsyncClient, db_session, monkeypatch
):
    from datetime import date

    from src.api import reconstructions
    from src.models.document import SourceDocument, ValuationDocument

    workspace = (await client.post("/api/v1/appraisal-import-workspaces", json={})).json()
    valuation_id = workspace["valuation_id"]
    db_session.add(
        SourceDocument(
            id="doc-dated-rr",
            sha256="c" * 64,
            original_filename="rent_roll.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            byte_size=10,
            storage_key="cc/rr",
            status="processed",
            document_type="rent_roll",
            relevant=True,
            as_of_date=date(2026, 9, 30),
        )
    )
    await db_session.flush()
    db_session.add(ValuationDocument(valuation_id=valuation_id, document_id="doc-dated-rr"))
    db_session.add(
        ExtractedFact(
            valuation_id=valuation_id,
            document_id="doc-dated-rr",
            field_path="leases[].tenant_name",
            value_json='"Acme"',
            status="accepted",
        )
    )
    await db_session.commit()

    def fake_structure(plan, facts, document_types):
        plan["property"]["total_area"] = 10000
        plan["suites"] = [{"source_id": "s1", "suite_name": "100", "area": 1000, "space_type": "office"}]
        return plan

    monkeypatch.setattr(reconstructions, "structure_plan_with_anthropic", fake_structure)
    response = await client.post(
        f"/api/v1/valuations/{valuation_id}/appraisal-reconstructions", json={}
    )

    assert response.status_code == 201, response.text
    assert response.json()["plan"]["property"]["analysis_start_date"] == "2026-10-01"


async def test_skipping_a_file_affects_only_this_valuation(client: AsyncClient, db_session):
    from src.models.document import ValuationDocument

    first = await _workspace_with_document(client, db_session, "doc-shared")
    second = (await client.post("/api/v1/appraisal-import-workspaces", json={})).json()
    db_session.add(ValuationDocument(valuation_id=second["valuation_id"], document_id="doc-shared"))
    await db_session.commit()

    used = await client.patch(
        f"/api/v1/valuations/{first['valuation_id']}/documents/doc-shared", json={"relevant": True}
    )
    assert used.json()["relevant"] is True
    docs = lambda vid: client.get(f"/api/v1/valuations/{vid}/documents")
    assert (await docs(first["valuation_id"])).json()[0]["relevant"] is True
    # The other valuation still follows the file's own classification
    assert (await docs(second["valuation_id"])).json()[0]["relevant"] is False

    await client.patch(f"/api/v1/valuations/{first['valuation_id']}/documents/doc-shared", json={"relevant": False})
    await client.patch(f"/api/v1/valuations/{second['valuation_id']}/documents/doc-shared", json={"relevant": True})
    assert (await docs(first["valuation_id"])).json()[0]["relevant"] is False
    assert (await docs(second["valuation_id"])).json()[0]["relevant"] is True


async def test_unfinished_import_list_uses_fixed_query_count(client: AsyncClient, db_session, test_engine):
    from sqlalchemy import event

    from src.models.document import AppraisalReconstruction, SourceDocument, ValuationDocument

    def reconstruction(workspace, doc_id, status):
        return AppraisalReconstruction(
            source_valuation_id=workspace["valuation_id"], source_document_id=doc_id,
            status=status, plan_json="{}",
        )

    count = 0

    def on_execute(*_):
        nonlocal count
        count += 1

    async def listed():
        nonlocal count
        count = 0
        event.listen(test_engine.sync_engine, "before_cursor_execute", on_execute)
        try:
            response = await client.get("/api/v1/appraisal-import-workspaces")
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", on_execute)
        assert response.status_code == 200
        return response.json(), count

    first = await _workspace_with_document(client, db_session, "doc-a")
    rows, one_workspace_queries = await listed()
    assert [w["valuation_id"] for w in rows] == [first["valuation_id"]]

    staged = await _workspace_with_document(client, db_session, "doc-b")
    db_session.add(SourceDocument(
        id="doc-b2", sha256="doc-b2".ljust(64, "1"), original_filename="doc-b2.pdf",
        media_type="application/pdf", byte_size=10, storage_key="bb/doc-b2", status="processed",
    ))
    await db_session.flush()
    db_session.add(ValuationDocument(valuation_id=staged["valuation_id"], document_id="doc-b2"))
    db_session.add(reconstruction(staged, "doc-b", "staged"))
    done = await _workspace_with_document(client, db_session, "doc-c")
    db_session.add(reconstruction(done, "doc-c", "staged"))
    db_session.add(reconstruction(done, "doc-c", "materialized"))
    await client.post("/api/v1/appraisal-import-workspaces", json={})  # no documents
    await db_session.commit()

    rows, many_workspace_queries = await listed()
    assert many_workspace_queries == one_workspace_queries
    by_id = {w["valuation_id"]: w for w in rows}
    assert set(by_id) == {staged["valuation_id"], first["valuation_id"]}  # created_at ties at 1s
    assert by_id[staged["valuation_id"]]["documents"] == ["doc-b.pdf", "doc-b2.pdf"]
    assert by_id[staged["valuation_id"]]["model_ready"] is True
    assert by_id[first["valuation_id"]] == {
        "property_id": first["property_id"], "valuation_id": first["valuation_id"],
        "created_at": first["created_at"], "documents": ["doc-a.pdf"], "model_ready": False,
    }


async def test_reuploading_an_extracted_file_gives_the_new_valuation_its_facts(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """The intake UI skips files already marked processed, so the upload itself must
    carry a finished extraction into each newly linked valuation."""
    from src.models.document import SourceDocument
    from sqlalchemy import select

    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "documents"))
    first = (await client.post("/api/v1/appraisal-import-workspaces", json={})).json()
    content = b"%PDF Starbucks OM"
    uploaded = await client.post(
        f"/api/v1/valuations/{first['valuation_id']}/documents",
        files={"files": ("om.pdf", content, "application/pdf")},
    )
    doc_id = uploaded.json()[0]["id"]

    document = await db_session.get(SourceDocument, doc_id)
    document.status = "processed"
    document.extraction_json = json.dumps({"facts": [
        {"field_path": "property.name", "value": "Starbucks Summerlin", "confidence": 0.9,
         "page_number": 1, "source_quote": "Starbucks", "record_key": None},
        {"field_path": "expenses.insurance", "value": "18000", "confidence": 0.8},
    ]})
    await db_session.commit()

    second = (await client.post("/api/v1/appraisal-import-workspaces", json={})).json()
    again = await client.post(
        f"/api/v1/valuations/{second['valuation_id']}/documents",
        files={"files": ("om.pdf", content, "application/pdf")},
    )
    assert again.status_code == 201
    assert again.json()[0]["reused"] is True
    assert again.json()[0]["status"] == "processed"

    db_session.expire_all()
    facts = (await db_session.execute(
        select(ExtractedFact).where(ExtractedFact.valuation_id == second["valuation_id"])
    )).scalars().all()
    assert sorted(f.field_path for f in facts) == ["expenses.insurance", "property.name"]

    # Uploading the same file to the same valuation again must not duplicate facts.
    await client.post(
        f"/api/v1/valuations/{second['valuation_id']}/documents",
        files={"files": ("om.pdf", content, "application/pdf")},
    )
    db_session.expire_all()
    count = len((await db_session.execute(
        select(ExtractedFact).where(ExtractedFact.valuation_id == second["valuation_id"])
    )).scalars().all())
    assert count == 2
