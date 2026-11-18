import json
import asyncio
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.models.document import (
    AppraisalReconstruction,
    ExtractedFact,
    SourceDocument,
    ValuationDocument,
)
from src.models.property import Property
from src.models.valuation import Valuation
from src.services.appraisal_reconstruction import (
    build_plan,
    enrich_plan_leases_from_pdf,
    materialize_plan,
    normalize_structured_plan,
    refresh_fact_overlays,
    structure_plan_with_anthropic,
    update_existing_roots,
)
from src.services.document_intelligence import read_content
from src.api.properties import INTAKE_PREFIX

router = APIRouter(prefix="/api/v1", tags=["appraisal reconstruction"])


def _read(item: AppraisalReconstruction) -> dict:
    return {
        "id": item.id,
        "source_valuation_id": item.source_valuation_id,
        "source_document_id": item.source_document_id,
        "status": item.status,
        "plan": json.loads(item.plan_json),
        "unresolved": json.loads(item.unresolved_json),
        "rebuilt_property_id": item.rebuilt_property_id,
        "rebuilt_valuation_id": item.rebuilt_valuation_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _default_analysis_start(
    plan: dict, documents: list[SourceDocument], prop: Property
) -> None:
    """Start an imported model at the rent roll's date unless a document states the start.

    Only applies to import workspaces, whose placeholder start is simply today's month.
    """
    if not (prop.external_id or "").startswith(INTAKE_PREFIX):
        return
    if any(f.get("mapped_to") == "property.analysis_start_date" for f in plan["appraisal_facts"]):
        return
    as_of = max(
        (doc.as_of_date for doc in documents if doc.document_type == "rent_roll" and doc.as_of_date),
        default=None,
    )
    if as_of is None:
        return
    # Analysis periods begin on the first of a month: the rent roll's month if dated the 1st,
    # otherwise the following month.
    if as_of.day != 1:
        as_of = (as_of.replace(day=1) + timedelta(days=32)).replace(day=1)
    plan["property"]["analysis_start_date"] = as_of.isoformat()


@router.post(
    "/valuations/{valuation_id}/appraisal-reconstructions",
    status_code=status.HTTP_201_CREATED,
)
async def create_reconstruction(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Build a staged valuation from the reviewed facts of every processed document."""
    valuation = await db.get(Valuation, valuation_id)
    if valuation is None:
        raise HTTPException(404, "Valuation not found")
    documents = list(
        (
            await db.execute(
                select(SourceDocument)
                .join(ValuationDocument)
                .where(
                    ValuationDocument.valuation_id == valuation_id,
                    SourceDocument.status == "processed",
                    func.coalesce(ValuationDocument.relevant_override, SourceDocument.relevant).is_not(False),
                )
                .order_by(SourceDocument.created_at)
            )
        ).scalars()
    )
    if not documents:
        raise HTTPException(409, "Process at least one document before building the model")
    document_types = {doc.id: doc.document_type or "other" for doc in documents}
    facts = list(
        (
            await db.execute(
                select(ExtractedFact).where(
                    ExtractedFact.valuation_id == valuation_id,
                    ExtractedFact.document_id.in_(document_types),
                    ExtractedFact.status != "rejected",
                )
            )
        ).scalars()
    )
    # The rent-roll table pass reads the PDF that best documents the tenant schedule.
    rank = {"rent_roll": 0, "appraisal": 1, "offering_memorandum": 2}
    primary = min(documents, key=lambda doc: rank.get(doc.document_type, 9))
    plan, unresolved = await build_plan(db, valuation, facts)
    _default_analysis_start(plan, documents, await db.get(Property, valuation.property_id))
    try:
        plan = await asyncio.to_thread(structure_plan_with_anthropic, plan, facts, document_types)
        modeled_area = sum(float(row.get("area", 0) or 0) for row in plan.get("suites", []))
        total_area = float(plan.get("property", {}).get("total_area", 0) or 0)
        if (
            primary.media_type == "application/pdf"
            and primary.document_type in rank
            and total_area > 0
            and modeled_area / total_area < 0.9
        ):
            plan = await asyncio.to_thread(
                enrich_plan_leases_from_pdf,
                plan,
                [fact for fact in facts if fact.document_id == primary.id],
                read_content(primary.storage_key),
            )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, f"Could not prepare structured valuation inputs: {exc}") from exc
    item = AppraisalReconstruction(
        source_valuation_id=valuation_id,
        source_document_id=primary.id,
        plan_json=json.dumps(plan, default=str),
        unresolved_json=json.dumps(unresolved, default=str),
    )
    db.add(item)
    await db.commit()
    return _read(item)


@router.get("/valuations/{valuation_id}/appraisal-reconstructions")
async def list_reconstructions(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await db.execute(
            select(AppraisalReconstruction)
            .where(AppraisalReconstruction.source_valuation_id == valuation_id)
            .order_by(AppraisalReconstruction.created_at.desc())
        )
    ).scalars()
    return [_read(item) for item in rows]


@router.put("/appraisal-reconstructions/{reconstruction_id}")
async def update_reconstruction(
    reconstruction_id: str,
    body: dict,
    db: AsyncSession = Depends(get_session),
) -> dict:
    item = await db.get(AppraisalReconstruction, reconstruction_id)
    if item is None:
        raise HTTPException(404, "Reconstruction not found")
    if item.status != "staged":
        raise HTTPException(409, "Only staged reconstructions can be edited")
    plan = body.get("plan")
    if (
        not isinstance(plan, dict)
        or not {"property", "valuation", "suites", "leases"} <= plan.keys()
    ):
        raise HTTPException(422, "Plan must contain property, valuation, suites, and leases")
    item.plan_json = json.dumps(plan, default=str)
    await db.commit()
    await db.refresh(item)
    return _read(item)


@router.post("/appraisal-reconstructions/{reconstruction_id}/materialize")
async def materialize_reconstruction(
    reconstruction_id: str,
    property_id: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Create the staged valuation and its model: under an existing property when property_id
    is given (a new valuation in that property), else under a new property."""
    item = await db.get(AppraisalReconstruction, reconstruction_id)
    if item is None:
        raise HTTPException(404, "Reconstruction not found")
    if item.status == "materialized" and item.rebuilt_valuation_id:
        plan = refresh_fact_overlays(json.loads(item.plan_json))
        prop = await db.get(Property, item.rebuilt_property_id)
        valuation = await db.get(Valuation, item.rebuilt_valuation_id)
        if prop is not None and valuation is not None:
            update_existing_roots(prop, valuation, plan)
            item.plan_json = json.dumps(plan, default=str)
            await db.commit()
            await db.refresh(item)
        return _read(item)
    if item.status != "staged":
        raise HTTPException(409, f"Valuation setup is already {item.status}")
    plan = json.loads(item.plan_json)
    normalize_structured_plan(refresh_fact_overlays(plan))
    target = None
    if property_id:
        target = await db.get(Property, property_id)
        if target is None:
            raise HTTPException(404, "Property not found")
        plan["target_property_id"] = property_id
    item.plan_json = json.dumps(plan, default=str)
    if any(
        fact.get("field_path", "").startswith("leases[]")
        for fact in plan.get("appraisal_facts", [])
    ) and not plan.get("leases"):
        raise HTTPException(
            409,
            "The documents contain lease facts but no structured leases. Build the model again.",
        )
    unresolved = json.loads(item.unresolved_json or "[]")
    resolved_paths = {
        fact.get("field_path")
        for fact in plan.get("appraisal_facts", [])
        if fact.get("resolved") or fact.get("review_status") == "rejected"
    }
    remaining = [fact for fact in unresolved if fact.get("field_path") not in resolved_paths]
    if remaining:
        raise HTTPException(
            409,
            {
                "message": "Review every material fact before creating the valuation",
                "unresolved_field_paths": [fact.get("field_path") for fact in remaining],
            },
        )
    try:
        prop, valuation = await materialize_plan(db, plan, target)
        source_links = (
            await db.execute(
                select(ValuationDocument.document_id).where(
                    ValuationDocument.valuation_id == item.source_valuation_id
                )
            )
        ).scalars()
        for document_id in source_links:
            db.add(ValuationDocument(valuation_id=valuation.id, document_id=document_id))
        source_facts = (
            await db.execute(
                select(ExtractedFact).where(
                    ExtractedFact.valuation_id == item.source_valuation_id,
                )
            )
        ).scalars()
        for fact in source_facts:
            db.add(
                ExtractedFact(
                    valuation_id=valuation.id,
                    document_id=fact.document_id,
                    field_path=fact.field_path,
                    value_json=fact.value_json,
                    confidence=fact.confidence,
                    page_number=fact.page_number,
                    source_quote=fact.source_quote,
                    status=fact.status,
                    record_key=fact.record_key,
                )
            )
        item.rebuilt_property_id = prop.id
        item.rebuilt_valuation_id = valuation.id
        item.status = "materialized"
        await db.commit()
        await db.refresh(item)
    except (ValueError, TypeError, KeyError) as exc:
        await db.rollback()
        raise HTTPException(422, f"Invalid staged model: {exc}") from exc
    return _read(item)


@router.get("/appraisal-reconstructions/{reconstruction_id}/comparison")
async def reconstruction_comparison(
    reconstruction_id: str,
    db: AsyncSession = Depends(get_session),
) -> dict:
    item = await db.get(AppraisalReconstruction, reconstruction_id)
    if item is None:
        raise HTTPException(404, "Reconstruction not found")
    source = await db.get(Valuation, item.source_valuation_id)
    rebuilt = (
        await db.get(Valuation, item.rebuilt_valuation_id) if item.rebuilt_valuation_id else None
    )
    metrics = ("result_npv", "result_going_in_cap_rate", "result_exit_value", "result_irr")
    comparison = {}
    for metric in metrics:
        left = getattr(source, metric) if source else None
        right = getattr(rebuilt, metric) if rebuilt else None
        comparison[metric] = {
            "source": str(left) if left is not None else None,
            "rebuilt": str(right) if right is not None else None,
            "variance": str(right - left) if left is not None and right is not None else None,
        }
    return {
        "reconstruction_id": item.id,
        "status": item.status,
        "rebuilt_valuation_id": item.rebuilt_valuation_id,
        "metrics": comparison,
        "unresolved": json.loads(item.unresolved_json),
    }
