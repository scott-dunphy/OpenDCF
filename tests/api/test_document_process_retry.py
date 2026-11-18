"""A document that failed to process and then succeeds on retry no longer shows the old error."""
from httpx import AsyncClient

import src.api.documents as documents_api
from src.config import settings
from src.models.document import SourceDocument
from tests.api.test_valuations_api import _setup_office_property


async def test_successful_retry_clears_the_error(client: AsyncClient, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "documents"))
    ids = await _setup_office_property(client)
    val_id = (await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
        "name": "Deal", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()["id"]
    doc = (await client.post(f"/api/v1/valuations/{val_id}/documents",
                             files={"files": ("om.txt", b"Offering memorandum", "text/plain")})).json()[0]

    def fail(*_args):
        raise ConnectionError("Connection error.")

    monkeypatch.setattr(documents_api, "extract_with_anthropic", fail)
    failed = await client.post(f"/api/v1/valuations/{val_id}/documents/{doc['id']}/process")
    assert failed.status_code == 422
    stored = await db_session.get(SourceDocument, doc["id"])
    await db_session.refresh(stored)
    assert stored.error_message == "Connection error."

    monkeypatch.setattr(documents_api, "extract_with_anthropic", lambda *_a: {
        "document_type": "offering_memorandum", "relevant": True, "confidence": 0.9, "reason": "OM", "facts": [],
    })
    ok = await client.post(f"/api/v1/valuations/{val_id}/documents/{doc['id']}/process")
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "processed" and ok.json()["error_message"] is None
