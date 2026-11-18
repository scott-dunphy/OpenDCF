import io
import json
import zipfile

from httpx import AsyncClient

from src.config import settings
from src.models.document import ExtractedFact, SourceDocument
from tests.api.test_valuations_api import _setup_office_property


async def test_valuation_package_round_trip_recreates_model(client: AsyncClient):
    ids = await _setup_office_property(client)
    valuation = (
        await client.post(
            f"/api/v1/properties/{ids['property_id']}/valuations",
            json={"name": "Portable", "discount_rate": "0.08", "exit_cap_rate": "0.065"},
        )
    ).json()
    package_response = await client.get(f"/api/v1/valuations/{valuation['id']}/package")
    assert package_response.status_code == 200
    package = package_response.json()
    model = package["valuation"]["model"]
    assert model["suites"] and model["leases"] and model["tenants"]
    assert "rent_steps" in model and "free_rent_periods" in model

    imported = await client.post("/api/v1/valuation-packages/import", json=package)
    assert imported.status_code == 201, imported.text
    result = imported.json()
    assert result["property_id"] != ids["property_id"]
    rebuilt = await client.get(f"/api/v1/properties/{result['property_id']}/valuations")
    assert rebuilt.status_code == 200
    assert rebuilt.json()[0]["id"] == result["valuation_id"]


RENT_ROLL = b"Suite 100, Acme, 5,000 SF, $32.50"
FACT_STATUSES = {
    "property.total_area": "accepted",
    "leases[].tenant_name": "rejected",
    "leases[].base_rent": "proposed",
}


async def _valuation_with_evidence(client: AsyncClient, db_session) -> dict:
    """A run valuation with one uploaded document, its extraction and three reviewed facts."""
    ids = await _setup_office_property(client)
    valuation = (
        await client.post(
            f"/api/v1/properties/{ids['property_id']}/valuations",
            json={"name": "Deal", "discount_rate": "0.08", "exit_cap_rate": "0.065"},
        )
    ).json()
    document = (
        await client.post(
            f"/api/v1/valuations/{valuation['id']}/documents",
            files={"files": ("rent roll.txt", RENT_ROLL, "text/plain")},
        )
    ).json()[0]
    stored = await db_session.get(SourceDocument, document["id"])
    stored.status, stored.document_type = "processed", "rent_roll"
    stored.extraction_json = json.dumps({"document_type": "rent_roll", "facts": []})
    for path, status in FACT_STATUSES.items():
        db_session.add(ExtractedFact(
            valuation_id=valuation["id"], document_id=document["id"], field_path=path,
            value_json=json.dumps("x"), status=status, page_number=2, record_key="Acme 100",
        ))
    await db_session.commit()
    await client.patch(
        f"/api/v1/valuations/{valuation['id']}/documents/{document['id']}", json={"relevant": False}
    )
    return valuation | {"npv": await _run_npv(client, valuation["id"]), "document_id": document["id"]}


async def _run_npv(client: AsyncClient, valuation_id: str) -> str:
    run = await client.post(f"/api/v1/valuations/{valuation_id}/run")
    assert run.status_code == 200, run.text
    npv = (await client.get(f"/api/v1/valuations/{valuation_id}")).json()["result_npv"]
    assert npv is not None
    return npv


async def _evidence(client: AsyncClient, valuation_id: str) -> tuple[list[dict], dict[str, str]]:
    documents = (await client.get(f"/api/v1/valuations/{valuation_id}/documents")).json()
    facts = (await client.get(f"/api/v1/valuations/{valuation_id}/document-review")).json()["facts"]
    return documents, {f["field_path"]: f["status"] for f in facts}


async def _import_file(client: AsyncClient, name: str, content: bytes) -> dict:
    imported = await client.post("/api/v1/valuation-packages/import", files={"file": (name, content)})
    assert imported.status_code == 201, imported.text
    return imported.json()


async def test_deal_package_zip_round_trip_carries_documents_and_facts(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "documents"))
    source = await _valuation_with_evidence(client, db_session)
    package = await client.get(f"/api/v1/valuations/{source['id']}/package?format=zip")
    assert package.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    sha = manifest["evidence"]["documents"][0]["sha256"]
    assert {"manifest.json", f"documents/{sha}/rent roll.txt", f"extractions/{sha}.json"} <= names
    assert manifest["schema_version"] == "1.1.0"

    # Received by someone whose database and store have never seen the file
    await db_session.delete(await db_session.get(SourceDocument, source["document_id"]))
    await db_session.commit()
    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "elsewhere"))
    result = await _import_file(client, "deal.odcf.zip", package.content)

    assert await _run_npv(client, result["valuation_id"]) == source["npv"]
    documents, statuses = await _evidence(client, result["valuation_id"])
    assert [(d["original_filename"], d["document_type"], d["relevant"]) for d in documents] == [
        ("rent roll.txt", "rent_roll", False)
    ]
    content = await client.get(
        f"/api/v1/valuations/{result['valuation_id']}/documents/{documents[0]['id']}/content"
    )
    assert content.content == RENT_ROLL
    assert statuses == FACT_STATUSES
    stored = await db_session.get(SourceDocument, documents[0]["id"])
    assert json.loads(stored.extraction_json)["document_type"] == "rent_roll"


async def test_deal_package_reuses_a_document_already_stored(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "documents"))
    source = await _valuation_with_evidence(client, db_session)
    package = await client.get(f"/api/v1/valuations/{source['id']}/package?format=zip")
    result = await _import_file(client, "deal.odcf.zip", package.content)
    documents, statuses = await _evidence(client, result["valuation_id"])
    assert [d["id"] for d in documents] == [source["document_id"]]
    assert statuses == FACT_STATUSES
    # The source keeps its own facts
    assert (await _evidence(client, source["id"]))[1] == FACT_STATUSES


async def test_json_package_imports_facts_against_a_metadata_only_document(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "documents"))
    source = await _valuation_with_evidence(client, db_session)
    package = (await client.get(f"/api/v1/valuations/{source['id']}/package")).json()
    await db_session.delete(await db_session.get(SourceDocument, source["document_id"]))
    await db_session.commit()
    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "elsewhere"))

    imported = await client.post("/api/v1/valuation-packages/import", json=package)
    assert imported.status_code == 201, imported.text
    valuation_id = imported.json()["valuation_id"]
    documents, statuses = await _evidence(client, valuation_id)
    assert [d["original_filename"] for d in documents] == ["rent roll.txt"]
    assert statuses == FACT_STATUSES
    url = f"/api/v1/valuations/{valuation_id}/documents/{documents[0]['id']}/content"
    assert (await client.get(url)).status_code == 404
    # Uploading the file later fills in the content
    await client.post(
        f"/api/v1/valuations/{valuation_id}/documents",
        files={"files": ("rent roll.txt", RENT_ROLL, "text/plain")},
    )
    assert (await client.get(url)).content == RENT_ROLL


async def test_frozen_valuation_exports_its_frozen_model(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "documents"))
    source = await _valuation_with_evidence(client, db_session)
    submitted = await client.post(f"/api/v1/valuations/{source['id']}/submit", json={"name": "A"})
    assert submitted.status_code == 200, submitted.text
    frozen_npv = submitted.json()["result_npv"]
    # The property row is not frozen; the package carries it as it was frozen
    prop_id = submitted.json()["property_id"]
    renamed = await client.put(f"/api/v1/properties/{prop_id}", json={"name": "Renamed later"})
    assert renamed.status_code == 200, renamed.text

    package = await client.get(f"/api/v1/valuations/{source['id']}/package?format=zip")
    assert package.status_code == 200, package.text
    result = await _import_file(client, "deal.odcf.zip", package.content)
    prop = (await client.get(f"/api/v1/properties/{result['property_id']}")).json()
    assert prop["name"] != "Renamed later"
    imported = (await client.get(f"/api/v1/valuations/{result['valuation_id']}")).json()
    assert imported["review_status"] == "draft"
    assert await _run_npv(client, result["valuation_id"]) == frozen_npv
    assert (await _evidence(client, result["valuation_id"]))[1] == FACT_STATUSES


async def test_import_rejects_a_zip_whose_file_does_not_match_its_checksum(client: AsyncClient):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "OpenDCF Valuation Package"}))
        archive.writestr(f"documents/{'0' * 64}/x.txt", b"tampered")
    response = await client.post(
        "/api/v1/valuation-packages/import", files={"file": ("deal.odcf.zip", buffer.getvalue())}
    )
    assert response.status_code == 422
    assert "checksum" in response.text


async def test_deal_package_keeps_the_extraction_of_a_document_missing_from_the_store(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "documents"))
    source = await _valuation_with_evidence(client, db_session)
    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "emptied"))
    package = await client.get(f"/api/v1/valuations/{source['id']}/package?format=zip")
    assert package.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        names = set(archive.namelist())
        sha = json.loads(archive.read("manifest.json"))["evidence"]["documents"][0]["sha256"]
    assert f"extractions/{sha}.json" in names
    assert not any(n.startswith("documents/") for n in names)
