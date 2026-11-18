import hashlib
import io
import json
import asyncio
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from src.config import settings
from src.db.session import get_session
from src.models.document import (
    AppraisalReconstruction,
    ExtractedFact,
    SourceDocument,
    ValuationDocument,
)
from src.models.lease import Lease
from src.models.property import Property, Suite
from src.models.valuation import Valuation
from src.services.document_intelligence import (
    DOCUMENT_TYPES,
    completeness_issues,
    extract_with_anthropic,
    portable_manifest,
    read_content,
    staleness_issues,
    store_content,
)
from src.services.appraisal_reconstruction import _coerce, materialize_plan
from src.services.valuation_clone import source_tables

router = APIRouter(prefix="/api/v1", tags=["document intelligence"])

from src.api.properties import INTAKE_PREFIX as APPRAISAL_INTAKE_PREFIX  # noqa: E402


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    return value


def _row(obj: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    return {
        column.name: _json_value(getattr(obj, column.name))
        for column in obj.__table__.columns
        if column.name not in exclude
    }


async def _valuation(db: AsyncSession, valuation_id: str) -> Valuation:
    item = await db.get(Valuation, valuation_id)
    if item is None:
        raise HTTPException(404, "Valuation not found")
    return item


async def _relevance(db: AsyncSession, valuation_id: str) -> dict[str, bool | None]:
    """Whether this valuation uses each linked document: its own choice, else the classification."""
    rows = await db.execute(
        select(SourceDocument.id, ValuationDocument.relevant_override, SourceDocument.relevant)
        .join(ValuationDocument)
        .where(ValuationDocument.valuation_id == valuation_id)
    )
    return {doc_id: override if override is not None else relevant for doc_id, override, relevant in rows}


async def _documents(db: AsyncSession, valuation_id: str) -> list[SourceDocument]:
    result = await db.execute(
        select(SourceDocument)
        .join(ValuationDocument)
        .where(ValuationDocument.valuation_id == valuation_id)
        .order_by(SourceDocument.created_at)
    )
    return list(result.scalars().all())


@router.get("/document-intelligence/status")
async def document_intelligence_status() -> dict:
    return {
        "configured": bool(settings.anthropic_api_key),
        "provider": "Anthropic",
        "model": settings.anthropic_document_model,
        "message": (
            None
            if settings.anthropic_api_key
            else "Anthropic is not configured. Add ANTHROPIC_API_KEY to .env and restart OpenDCF."
        ),
    }


@router.post("/appraisal-import-workspaces", status_code=status.HTTP_201_CREATED)
async def create_appraisal_import_workspace(
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Create the hidden source model used by the dashboard's upload-first import flow."""
    started_at = datetime.now()
    prop = Property(
        name=f"Appraisal import {started_at:%Y-%m-%d %H:%M}",
        property_type="office",
        total_area=Decimal("1"),
        area_unit="sf",
        analysis_start_date=date.today().replace(day=1),
        analysis_period_months=120,
        fiscal_year_end_month=12,
        ownership_pct=Decimal("1"),
        external_id=f"{APPRAISAL_INTAKE_PREFIX}{started_at:%Y%m%d%H%M%S%f}",
        comment="Temporary source workspace created by AI Appraisal Import.",
    )
    db.add(prop)
    await db.flush()
    valuation = Valuation(
        property_id=prop.id,
        name="AI Appraisal Import",
        description="Upload documents, review extracted facts, and rebuild the valuation.",
        discount_rate=Decimal("0.08"),
        exit_cap_rate=Decimal("0.065"),
        analysis_start_date_override=prop.analysis_start_date,
        analysis_period_months_override=prop.analysis_period_months,
    )
    db.add(valuation)
    await db.commit()
    await db.refresh(valuation)
    return {
        "property_id": prop.id,
        "valuation_id": valuation.id,
        "created_at": valuation.created_at,
    }


@router.get("/appraisal-import-workspaces")
async def list_appraisal_import_workspaces(db: AsyncSession = Depends(get_session)) -> list[dict]:
    """Unfinished imports: workspaces with documents and no created valuation yet."""
    rows = (
        await db.execute(
            select(Valuation.id, Valuation.property_id, Valuation.created_at)
            .join(Property, Valuation.property_id == Property.id)
            .where(Property.external_id.startswith(APPRAISAL_INTAKE_PREFIX))
            .order_by(Valuation.created_at.desc())
        )
    ).all()
    ids = [row.id for row in rows]
    statuses: dict[str, set[str]] = {}
    names: dict[str, list[str]] = {}
    if ids:
        for valuation_id, status_ in await db.execute(
            select(AppraisalReconstruction.source_valuation_id, AppraisalReconstruction.status)
            .where(AppraisalReconstruction.source_valuation_id.in_(ids))
        ):
            statuses.setdefault(valuation_id, set()).add(status_)
        for valuation_id, name in await db.execute(
            select(ValuationDocument.valuation_id, SourceDocument.original_filename)
            .join(SourceDocument)
            .where(ValuationDocument.valuation_id.in_(ids))
            .order_by(SourceDocument.created_at)
        ):
            names.setdefault(valuation_id, []).append(name)
    output = []
    for valuation_id, property_id, created_at in rows:
        workspace_statuses = statuses.get(valuation_id, set())
        documents = names.get(valuation_id, [])
        if "materialized" in workspace_statuses or not documents:
            continue
        output.append({
            "property_id": property_id,
            "valuation_id": valuation_id,
            "created_at": created_at,
            "documents": documents,
            "model_ready": "staged" in workspace_statuses,
        })
    return output


@router.delete(
    "/appraisal-import-workspaces/{valuation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def discard_appraisal_import_workspace(
    valuation_id: str, db: AsyncSession = Depends(get_session)
) -> None:
    """Delete an import workspace's hidden property. Created valuations are unaffected."""
    valuation = await _valuation(db, valuation_id)
    prop = await db.get(Property, valuation.property_id)
    if prop is None or not (prop.external_id or "").startswith(APPRAISAL_INTAKE_PREFIX):
        raise HTTPException(409, "Only import workspaces can be discarded")
    await db.delete(prop)
    await db.commit()


def _read_package_zip(raw: bytes) -> tuple[dict, dict[str, bytes], dict[str, str]]:
    """A deal package's manifest, its document files by sha256 and their extractions by sha256.

    Members are only read, never extracted to disk; each file must hash to the name it is filed
    under (documents/<sha256>/<filename>).
    """
    limit = settings.document_max_upload_bytes
    files: dict[str, bytes] = {}
    extractions: dict[str, str] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = {info.filename: info for info in archive.infolist() if not info.is_dir()}
            if "manifest.json" not in infos:
                raise HTTPException(422, "Deal package has no manifest.json")
            for name, info in infos.items():
                if info.file_size > limit:
                    raise HTTPException(413, f"{name}: exceeds the {limit}-byte upload limit")
            payload = json.loads(archive.read("manifest.json"))
            for name in infos:
                parts = name.split("/")
                if len(parts) == 3 and parts[0] == "documents":
                    content = archive.read(name)
                    if hashlib.sha256(content).hexdigest() != parts[1]:
                        raise HTTPException(422, f"{name}: file does not match its checksum")
                    files[parts[1]] = content
                elif len(parts) == 2 and parts[0] == "extractions" and parts[1].endswith(".json"):
                    extractions[parts[1].removesuffix(".json")] = archive.read(name).decode("utf-8")
    except (zipfile.BadZipFile, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(422, f"Invalid deal package: {exc}") from exc
    return payload, files, extractions


# Document columns that describe the file itself, carried over when the importing database lacks it
_DOCUMENT_COLUMNS = {
    "original_filename", "media_type", "byte_size", "status", "document_type", "relevant",
    "confidence", "reason", "family_key", "amendment_number", "document_date", "as_of_date",
    "extraction_model", "error_message",
}


async def _import_evidence(
    db: AsyncSession,
    valuation_id: str,
    evidence: dict,
    files: dict[str, bytes],
    extractions: dict[str, str],
) -> None:
    """Link the package's documents to the new valuation and give it their facts, review status kept.

    Files are content-addressed: one already in this database is reused as it is. One the package
    has no file for (a .odcf.json package) gets a metadata-only row, so its facts keep their source;
    uploading the file later fills it in.
    """
    document_ids: dict[str, str] = {}
    linked: dict[str, str] = {}  # sha256 -> document id linked to the new valuation
    for row in evidence.get("documents") or []:
        sha = row.get("sha256")
        if not sha or not row.get("id"):
            continue
        if sha in linked:  # the same file listed twice: link it once
            document_ids[row["id"]] = linked[sha]
            continue
        if sha in files:
            store_content(files[sha])
        document = await db.scalar(select(SourceDocument).where(SourceDocument.sha256 == sha))
        if document is None:
            document = SourceDocument(
                **_coerce(SourceDocument, {k: v for k, v in row.items() if k in _DOCUMENT_COLUMNS}),
                sha256=sha,
                storage_key=str(Path(sha[:2]) / sha),
                extraction_json=extractions.get(sha),
            )
            db.add(document)
            await db.flush()
        db.add(ValuationDocument(
            valuation_id=valuation_id, document_id=document.id,
            relevant_override=row.get("relevant_override"),
        ))
        document_ids[row["id"]] = linked[sha] = document.id
    for fact in evidence.get("facts") or []:
        document_id = document_ids.get(fact.get("document_id"))
        if document_id is None or not fact.get("field_path"):
            continue
        db.add(ExtractedFact(
            valuation_id=valuation_id,
            document_id=document_id,
            field_path=fact["field_path"],
            value_json=json.dumps(fact.get("value"), default=str),
            confidence=fact.get("confidence"),
            page_number=fact.get("page_number"),
            source_quote=fact.get("source_quote"),
            record_key=fact.get("record_key"),
            status=fact.get("status") if fact.get("status") in {"accepted", "rejected", "proposed"} else "proposed",
        ))


@router.post("/valuation-packages/import", status_code=status.HTTP_201_CREATED)
async def import_package(request: Request, db: AsyncSession = Depends(get_session)) -> dict:
    """Recreate a valuation model from a versioned OpenDCF portable package.

    Accepts the package as a JSON body, or as a multipart `file`: a .odcf.json manifest or a
    .odcf.zip deal package (manifest plus the source documents and their extractions).
    """
    files: dict[str, bytes] = {}
    extractions: dict[str, str] = {}
    try:
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            upload = (await request.form()).get("file")
            if upload is None or isinstance(upload, str):
                raise HTTPException(422, "Upload the package as the 'file' field")
            raw = await upload.read()
            if zipfile.is_zipfile(io.BytesIO(raw)):
                payload, files, extractions = _read_package_zip(raw)
            else:
                payload = json.loads(raw)
        else:
            payload = await request.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(422, f"Not an OpenDCF Valuation Package: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != "OpenDCF Valuation Package":
        raise HTTPException(422, "Not an OpenDCF Valuation Package")
    version = str(payload.get("schema_version", ""))
    if not version.startswith("1."):
        raise HTTPException(422, f"Unsupported valuation package schema version: {version}")
    property_data = payload.get("property")
    valuation_data = payload.get("valuation")
    if not isinstance(property_data, dict) or not isinstance(valuation_data, dict):
        raise HTTPException(422, "Package must contain property and valuation objects")
    model = valuation_data.get("model") or {}
    def sourced(rows: list[dict], *references: str) -> list[dict]:
        output = []
        for row in rows:
            item = dict(row)
            item["source_id"] = row.get("id", "")
            for reference in references:
                item[f"source_{reference}"] = row.get(reference)
            output.append(item)
        return output

    plan = {
        "property": property_data,
        "valuation": {key: value for key, value in valuation_data.items() if key != "model"},
        "suites": sourced(model.get("suites", [])),
        "tenants": sourced(model.get("tenants", [])),
        "market_leasing_profiles": [
            dict(row)
            | {"source_id": row.get("id", ""), "source_next_profile_id": row.get("next_profile_id"),
               "source_recovery_structure_id": row.get("recovery_structure_id")}
            for row in model.get("market_leasing_profiles", [])
        ],
        "expenses": model.get("expenses", []),
        "other_income": model.get("other_income", []),
        "capital_projects": model.get("capital_projects", []),
        "recovery_structures": sourced(model.get("recovery_structures", [])),
        "recovery_pools": model.get("recovery_pools", []),
        "recovery_structure_items": sourced(
            model.get("recovery_structure_items", []), "recovery_structure_id"
        ),
        "leases": sourced(
            model.get("leases", []), "suite_id", "tenant_id", "recovery_structure_id"
        ),
        "rent_steps": sourced(model.get("rent_steps", []), "lease_id"),
        "free_rent_periods": sourced(model.get("free_rent_periods", []), "lease_id"),
        "lease_expense_recoveries": sourced(
            model.get("lease_expense_recoveries", []), "lease_id"
        ),
        "appraisal_facts": [],
    }
    try:
        prop, valuation = await materialize_plan(db, plan)
        await _import_evidence(db, valuation.id, payload.get("evidence") or {}, files, extractions)
        await db.commit()
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        await db.rollback()
        raise HTTPException(422, f"Invalid valuation package: {exc}") from exc
    return {
        "property_id": prop.id,
        "valuation_id": valuation.id,
        "schema_version": version,
    }


async def _copy_finished_extraction(
    db: AsyncSession, valuation_id: str, document: SourceDocument
) -> dict | None:
    """Give a valuation the facts from a file's completed extraction, once.

    Returns the extraction, or None when the file has no complete extraction yet.
    An extraction without a facts list was cut off (older output limit) and must be re-read.
    """
    if not document.extraction_json:
        return None
    extraction = json.loads(document.extraction_json)
    if "facts" not in extraction:
        return None
    existing = await db.execute(
        select(ExtractedFact.id)
        .where(
            ExtractedFact.valuation_id == valuation_id,
            ExtractedFact.document_id == document.id,
        )
        .limit(1)
    )
    if existing.scalar_one_or_none() is None:
        for fact in extraction.get("facts", []):
            db.add(
                ExtractedFact(
                    valuation_id=valuation_id,
                    document_id=document.id,
                    field_path=fact["field_path"],
                    value_json=json.dumps(fact.get("value")),
                    confidence=fact.get("confidence"),
                    page_number=fact.get("page_number"),
                    source_quote=fact.get("source_quote"),
                    record_key=fact.get("record_key"),
                )
            )
    return extraction


@router.post("/valuations/{valuation_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_documents(
    valuation_id: str,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    await _valuation(db, valuation_id)
    output = []
    for upload in files:
        chunks = []
        size = 0
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > settings.document_max_upload_bytes:
                raise HTTPException(
                    413,
                    f"{upload.filename}: exceeds the {settings.document_max_upload_bytes}-byte upload limit",
                )
            chunks.append(chunk)
        content = b"".join(chunks)
        if not content:
            raise HTTPException(400, f"{upload.filename}: empty upload")
        digest, storage_key = store_content(content)
        result = await db.execute(select(SourceDocument).where(SourceDocument.sha256 == digest))
        document = result.scalar_one_or_none()
        reused = document is not None
        if document is None:
            document = SourceDocument(
                sha256=digest,
                original_filename=upload.filename or digest,
                media_type=upload.content_type or "application/octet-stream",
                byte_size=len(content),
                storage_key=storage_key,
            )
            db.add(document)
            await db.flush()
        linked = await db.execute(
            select(ValuationDocument).where(
                ValuationDocument.valuation_id == valuation_id,
                ValuationDocument.document_id == document.id,
            )
        )
        if linked.scalar_one_or_none() is None:
            db.add(ValuationDocument(valuation_id=valuation_id, document_id=document.id))
        if reused:
            # The intake UI only sends unprocessed files to /process, and processed status
            # belongs to the file, so a re-uploaded file must bring its facts along here.
            await _copy_finished_extraction(db, valuation_id, document)
        output.append({**_row(document), "reused": reused})
    await db.commit()
    return output


async def _linked_document(db: AsyncSession, valuation_id: str, document_id: str) -> SourceDocument:
    return (await _document_link(db, valuation_id, document_id))[0]


async def _document_link(
    db: AsyncSession, valuation_id: str, document_id: str
) -> tuple[SourceDocument, ValuationDocument]:
    await _valuation(db, valuation_id)
    link = await db.scalar(
        select(ValuationDocument).where(
            ValuationDocument.valuation_id == valuation_id,
            ValuationDocument.document_id == document_id,
        )
    )
    document = await db.get(SourceDocument, document_id)
    if link is None or document is None:
        raise HTTPException(404, "Document is not linked to this valuation")
    return document, link


@router.patch("/valuations/{valuation_id}/documents/{document_id}")
async def classify_document(
    valuation_id: str, document_id: str, body: dict, db: AsyncSession = Depends(get_session)
) -> dict:
    """Correct the detected document type, or choose whether this valuation uses the file.

    The type describes the file itself, so a correction applies wherever it is linked; using or
    skipping it is this valuation's choice only.
    """
    document, link = await _document_link(db, valuation_id, document_id)
    if "document_type" in body:
        if body["document_type"] not in DOCUMENT_TYPES:
            raise HTTPException(422, "Unknown document type")
        document.document_type = body["document_type"]
    if "relevant" in body:
        link.relevant_override = bool(body["relevant"])
    await db.commit()
    await db.refresh(document)
    return _row(document, {"extraction_json"}) | {"relevant": link.relevant_override}


@router.delete(
    "/valuations/{valuation_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_document(
    valuation_id: str, document_id: str, db: AsyncSession = Depends(get_session)
) -> None:
    """Detach a document and its extracted facts from this valuation.

    The stored file is kept: it is content-addressed and may back other valuations.
    """
    await _linked_document(db, valuation_id, document_id)
    await db.execute(
        delete(ExtractedFact).where(
            ExtractedFact.valuation_id == valuation_id,
            ExtractedFact.document_id == document_id,
        )
    )
    await db.execute(
        delete(ValuationDocument).where(
            ValuationDocument.valuation_id == valuation_id,
            ValuationDocument.document_id == document_id,
        )
    )
    await db.commit()


@router.get("/valuations/{valuation_id}/documents")
async def list_documents(valuation_id: str, db: AsyncSession = Depends(get_session)) -> list[dict]:
    await _valuation(db, valuation_id)
    relevance = await _relevance(db, valuation_id)
    return [
        _row(doc, {"extraction_json"}) | {"relevant": relevance.get(doc.id, doc.relevant)}
        for doc in await _documents(db, valuation_id)
    ]


@router.get("/valuations/{valuation_id}/documents/{document_id}/content")
async def document_content(
    valuation_id: str, document_id: str, db: AsyncSession = Depends(get_session)
) -> FileResponse:
    linked = await db.execute(
        select(ValuationDocument.id).where(
            ValuationDocument.valuation_id == valuation_id,
            ValuationDocument.document_id == document_id,
        )
    )
    document = await db.get(SourceDocument, document_id)
    if document is None or linked.scalar_one_or_none() is None:
        raise HTTPException(404, "Document is not linked to this valuation")
    root = Path(settings.document_store_path).resolve()
    target = (root / document.storage_key).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, "Stored document content is unavailable")
    return FileResponse(
        target,
        media_type=document.media_type,
        filename=document.original_filename,
        content_disposition_type="inline",
    )


@router.post("/valuations/{valuation_id}/documents/{document_id}/process")
async def process_document(
    valuation_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_session),
) -> dict:
    await _valuation(db, valuation_id)
    link = await db.execute(
        select(ValuationDocument).where(
            ValuationDocument.valuation_id == valuation_id,
            ValuationDocument.document_id == document_id,
        )
    )
    if link.scalar_one_or_none() is None:
        raise HTTPException(404, "Document is not linked to this valuation")
    document = await db.get(SourceDocument, document_id)
    assert document is not None
    # A completed extraction is reusable even if an earlier response-formatting
    # error incorrectly left the status as failed.
    # An extraction without a facts list was cut off (older output limit): read the file again.
    extraction = await _copy_finished_extraction(db, valuation_id, document)
    if extraction is not None:
        document.status = "processed"
        document.error_message = None
        await db.commit()
        await db.refresh(document)
        return {
            **_row(document, {"extraction_json"}),
            "reused_extraction": True,
            "extraction": extraction,
        }
    document.status = "processing"
    await db.commit()
    # AsyncSession expires ORM state on commit. Refresh before the blocking AI
    # call so assigning extracted fields later cannot trigger implicit async IO.
    await db.refresh(document)
    try:
        extraction = await asyncio.to_thread(
            extract_with_anthropic,
            read_content(document.storage_key),
            document.media_type,
            document.original_filename,
        )
        document.document_type = extraction["document_type"]
        document.relevant = extraction["relevant"]
        document.confidence = extraction["confidence"]
        document.reason = extraction["reason"]
        document.family_key = extraction.get("family_key")
        document.amendment_number = extraction.get("amendment_number")
        document.document_date = extraction.get("document_date")
        document.as_of_date = extraction.get("as_of_date")
        document.extraction_model = settings.anthropic_document_model
        serializable = {
            **extraction,
            "document_date": _json_value(extraction.get("document_date")),
            "as_of_date": _json_value(extraction.get("as_of_date")),
        }
        document.extraction_json = json.dumps(serializable, default=str)
        document.status = "processed"
        document.error_message = None  # a retry that succeeds clears the earlier failure
        for fact in extraction.get("facts", []):
            db.add(
                ExtractedFact(
                    valuation_id=valuation_id,
                    document_id=document.id,
                    field_path=fact["field_path"],
                    value_json=json.dumps(fact.get("value")),
                    confidence=fact.get("confidence"),
                    page_number=fact.get("page_number"),
                    source_quote=fact.get("source_quote"),
                    record_key=fact.get("record_key"),
                )
            )
        await db.commit()
        await db.refresh(document)
        return {
            **_row(document, {"extraction_json"}),
            "reused_extraction": False,
            "extraction": serializable,
        }
    except Exception as exc:
        await db.rollback()
        await db.refresh(document)
        document.status = "failed"
        document.error_message = str(exc)[:2000]
        await db.commit()
        raise HTTPException(422, str(exc)) from exc


@router.get("/valuations/{valuation_id}/document-review")
async def document_review(valuation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    valuation = await _valuation(db, valuation_id)
    documents = await _documents(db, valuation_id)
    suites = (
        (await db.execute(select(Suite.id).where(Suite.valuation_id == valuation.id)))
        .scalars()
        .all()
    )
    leases = list(
        (await db.execute(select(Lease).where(Lease.suite_id.in_(suites)))).scalars().all()
    )
    effective = (
        valuation.analysis_start_date_override
        or (await db.get(Property, valuation.property_id)).analysis_start_date
    )
    issues = completeness_issues(documents, await _relevance(db, valuation_id)) + staleness_issues(
        documents, effective, leases
    )
    facts = (
        (await db.execute(select(ExtractedFact).where(ExtractedFact.valuation_id == valuation_id)))
        .scalars()
        .all()
    )
    # Multiple extraction attempts can yield the same supported fact. Present
    # one review item per source/value while retaining the strongest decision.
    status_rank = {"accepted": 2, "rejected": 1, "proposed": 0}
    unique_facts: dict[tuple, ExtractedFact] = {}
    for fact in facts:
        key = (
            fact.document_id, fact.field_path, fact.value_json, fact.page_number, fact.record_key
        )
        current = unique_facts.get(key)
        if current is None or status_rank.get(fact.status, 0) > status_rank.get(current.status, 0):
            unique_facts[key] = fact
    return {
        "effective_date": str(effective),
        "issues": issues,
        "facts": [
            _row(fact) | {"value": json.loads(fact.value_json)}
            for fact in unique_facts.values()
        ],
    }


@router.patch("/valuations/{valuation_id}/facts/{fact_id}")
async def review_fact(
    valuation_id: str, fact_id: str, body: dict, db: AsyncSession = Depends(get_session)
) -> dict:
    fact = await db.get(ExtractedFact, fact_id)
    if fact is None or fact.valuation_id != valuation_id:
        raise HTTPException(404, "Extracted fact not found")
    decision = body.get("status")
    if decision not in {"accepted", "rejected", "proposed"}:
        raise HTTPException(422, "status must be accepted, rejected, or proposed")
    fact.status = decision
    if "value" in body:
        fact.value_json = json.dumps(body["value"], default=str)
    await db.commit()
    await db.refresh(fact)
    return _row(fact) | {"value": json.loads(fact.value_json)}


@router.post("/valuations/{valuation_id}/facts/bulk-review")
async def bulk_review_facts(
    valuation_id: str, body: dict, db: AsyncSession = Depends(get_session)
) -> dict:
    await _valuation(db, valuation_id)
    decision = body.get("status")
    if decision not in {"accepted", "rejected", "proposed"}:
        raise HTTPException(422, "status must be accepted, rejected, or proposed")
    fact_ids = body.get("fact_ids")
    query = select(ExtractedFact).where(ExtractedFact.valuation_id == valuation_id)
    if fact_ids is not None:
        if not isinstance(fact_ids, list):
            raise HTTPException(422, "fact_ids must be an array")
        query = query.where(ExtractedFact.id.in_(fact_ids))
    facts = list((await db.execute(query)).scalars().all())
    for fact in facts:
        fact.status = decision
    await db.commit()
    return {"updated": len(facts), "status": decision}


@router.get("/valuations/{valuation_id}/package")
async def export_package(
    valuation_id: str, format: str = "json", db: AsyncSession = Depends(get_session)
) -> Response:
    """The valuation's model and evidence as a portable package: `format=json` gives the
    .odcf.json manifest; `format=zip` a .odcf.zip deal package that also carries the source
    documents and their extractions."""
    if format not in {"json", "zip"}:
        raise HTTPException(422, "format must be json or zip")
    # The package leaves out the per-tenant result blobs, so they are not loaded either
    valuation = await db.scalar(select(Valuation).where(Valuation.id == valuation_id).options(
        defer(Valuation.result_tenant_cash_flows_json), defer(Valuation.result_recovery_audit_json),
    ))
    if valuation is None:
        raise HTTPException(404, "Valuation not found")
    # The live model, or for a frozen valuation the model as frozen (as a copy of it takes)
    tables = await source_tables(db, valuation)

    def rows(table: str) -> list[dict]:
        return [{k: _json_value(v) for k, v in row.items()} for row in tables.get(table, [])]

    documents = await _documents(db, valuation_id)
    overrides = {
        link.document_id: link.relevant_override
        for link in (await db.execute(
            select(ValuationDocument).where(ValuationDocument.valuation_id == valuation_id)
        )).scalars()
    }
    facts = list(
        (await db.execute(select(ExtractedFact).where(ExtractedFact.valuation_id == valuation_id)))
        .scalars()
        .all()
    )
    review = await document_review(valuation_id, db)
    manifest = portable_manifest(
        rows("properties")[0],
        # Without the per-tenant result blobs (the recovery audit can be 100+ MB); a run rebuilds them
        rows("valuations")[0]
        | {
            "model": {
                "suites": rows("suites"),
                "tenants": rows("tenants"),
                "market_leasing_profiles": rows("market_leasing_profiles"),
                "expenses": rows("property_expenses"),
                "other_income": rows("property_other_income"),
                "capital_projects": rows("property_capital_projects"),
                "recovery_structures": rows("recovery_structures"),
                "recovery_pools": rows("recovery_pools"),
                "recovery_structure_items": rows("recovery_structure_items"),
                "leases": rows("leases"),
                "rent_steps": rows("rent_steps"),
                "free_rent_periods": rows("free_rent_periods"),
                "lease_expense_recoveries": rows("lease_expense_recoveries"),
            }
        },
        [
            _row(d, {"storage_key", "extraction_json"}) | {"relevant_override": overrides.get(d.id)}
            for d in documents
        ],
        [_row(f) | {"value": json.loads(f.value_json)} for f in facts],
        review["issues"],
    )
    # Decimals nested in JSON columns and review issues go out as strings, like the columns
    body = json.dumps(manifest, default=_json_value)
    if format == "json":
        headers = {"Content-Disposition": f'attachment; filename="valuation-{valuation_id}.odcf.json"'}
        return Response(body, media_type="application/json", headers=headers)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", body)
        for document in documents:
            if document.extraction_json:
                archive.writestr(f"extractions/{document.sha256}.json", document.extraction_json)
            try:
                content = read_content(document.storage_key)
            except (OSError, ValueError):
                continue  # file missing from the store: the manifest still lists it and its facts
            name = Path(document.original_filename).name or document.sha256
            archive.writestr(f"documents/{document.sha256}/{name}", content)
    headers = {"Content-Disposition": f'attachment; filename="valuation-{valuation_id}.odcf.zip"'}
    return Response(buffer.getvalue(), media_type="application/zip", headers=headers)
