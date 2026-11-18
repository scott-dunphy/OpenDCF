import asyncio
import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.session import get_session
from src.models.document import AiModelAction
from src.models.lease import Lease, Tenant
from src.models.market import MarketLeasingProfile
from src.models.property import Property, Suite
from src.models.valuation import Valuation
from src.schemas.self_storage import parse_storage_model
from src.services.audit import row_dict
from src.services.valuation_copilot import (
    STORAGE_UNUSED_ENTITIES,
    apply_changes,
    ask_copilot,
    ask_scenario,
    assert_proposal_is_current,
    resolve_scenario_changes,
    resolve_storage_changes,
    validate_changes,
)
from src.services.valuation_service import ValuationService

router = APIRouter(prefix="/api/v1", tags=["valuation copilot"])


async def _state(db: AsyncSession, valuation_id: str) -> tuple[Valuation, dict, dict]:
    valuation = await db.get(Valuation, valuation_id)
    if valuation is None:
        raise HTTPException(404, "Valuation not found")
    if valuation.review_status != "draft":
        # A frozen valuation's model cannot change
        raise HTTPException(409, "The copilot and what-if chat work on drafts. Duplicate this valuation "
                                 "to explore changes.")
    prop = await db.get(Property, valuation.property_id)
    suites = list((await db.execute(select(Suite).where(Suite.valuation_id == valuation.id))).scalars())
    suite_ids = [s.id for s in suites]
    leases = (
        list((await db.execute(select(Lease).where(Lease.suite_id.in_(suite_ids)))).scalars())
        if suite_ids
        else []
    )
    tenants = list(
        (await db.execute(select(Tenant).where(Tenant.valuation_id == valuation.id))).scalars()
    )
    profiles = list(
        (
            await db.execute(
                select(MarketLeasingProfile).where(MarketLeasingProfile.valuation_id == valuation.id)
            )
        ).scalars()
    )
    groups = {
        "valuation": [valuation],
        "property": [prop],
        "suite": suites,
        "lease": leases,
        "tenant": tenants,
        "market_leasing_profile": profiles,
    }
    entities = {(kind, item.id): item for kind, items in groups.items() for item in items}
    context = {kind: [row_dict(item) for item in items] for kind, items in groups.items()}
    return valuation, entities, context


def _serial_changes(changes: list[dict]) -> list[dict]:
    return [json.loads(json.dumps(change, default=str)) for change in changes]


@router.post("/valuations/{valuation_id}/copilot")
async def copilot(valuation_id: str, body: dict, db: AsyncSession = Depends(get_session)) -> dict:
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(422, "message is required")
    valuation, entities, context = await _state(db, valuation_id)
    try:
        result = ask_copilot(message, context)
        validated = validate_changes(result.get("changes", []), entities)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    action_type = result["action_type"]
    auto_apply = action_type == "propose_changes" and valuation.ai_permission_mode == "always_allow"
    action = AiModelAction(
        valuation_id=valuation_id,
        user_message=message,
        assistant_message=result["message"],
        action_type=action_type,
        proposal_json=json.dumps(_serial_changes(validated)) if validated else None,
        status="applied" if auto_apply else ("pending_confirmation" if validated else "answered"),
        model_name=settings.anthropic_document_model,
    )
    db.add(action)
    if auto_apply:
        apply_changes(validated, entities)
    await db.commit()
    return {
        "action_id": action.id,
        "message": action.assistant_message,
        "status": action.status,
        "changes": _serial_changes(validated),
        "permission_mode": valuation.ai_permission_mode,
    }


@router.post("/valuations/{valuation_id}/copilot/{action_id}/confirm")
async def confirm_action(
    valuation_id: str, action_id: str, db: AsyncSession = Depends(get_session)
) -> dict:
    action = await db.get(AiModelAction, action_id)
    if action is None or action.valuation_id != valuation_id:
        raise HTTPException(404, "Copilot action not found")
    if action.status != "pending_confirmation":
        raise HTTPException(409, f"Action is already {action.status}")
    _, entities, _ = await _state(db, valuation_id)
    try:
        proposal = json.loads(action.proposal_json or "[]")
        assert_proposal_is_current(proposal, entities)
        validated = validate_changes(proposal, entities)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    apply_changes(validated, entities)
    action.status = "applied"
    await db.commit()
    return {"action_id": action.id, "status": "applied", "changes": _serial_changes(validated)}


@router.post("/valuations/{valuation_id}/copilot/{action_id}/reject")
async def reject_action(
    valuation_id: str, action_id: str, db: AsyncSession = Depends(get_session)
) -> dict:
    action = await db.get(AiModelAction, action_id)
    if action is None or action.valuation_id != valuation_id:
        raise HTTPException(404, "Copilot action not found")
    if action.status != "pending_confirmation":
        raise HTTPException(409, f"Action is already {action.status}")
    action.status = "rejected"
    await db.commit()
    return {"action_id": action.id, "status": "rejected"}


@router.put("/valuations/{valuation_id}/copilot-permission")
async def set_permission(
    valuation_id: str, body: dict, db: AsyncSession = Depends(get_session)
) -> dict:
    valuation = await db.get(Valuation, valuation_id)
    if valuation is None:
        raise HTTPException(404, "Valuation not found")
    mode = body.get("mode")
    if mode not in {"confirm", "always_allow"}:
        raise HTTPException(422, "mode must be confirm or always_allow")
    valuation.ai_permission_mode = mode
    await db.commit()
    return {
        "valuation_id": valuation_id,
        "mode": mode,
        "warning": "AI changes apply without confirmation." if mode == "always_allow" else None,
    }


def _scenario_metrics(result, has_price: bool) -> dict:
    """Headline outputs, rounded. IRR only means something against a purchase price."""
    cents, rate = Decimal("0.01"), Decimal("0.000001")
    flows = result.annual_cash_flows
    return {
        "value": result.npv.quantize(cents),
        "irr": result.irr.quantize(rate) if has_price and result.irr is not None else None,
        "avg_occupancy_pct": result.avg_occupancy_pct.quantize(rate),
        "year1_noi": flows[0].net_operating_income.quantize(cents) if flows else None,
        "total_noi": sum((cf.net_operating_income for cf in flows), Decimal(0)).quantize(cents),
    }


def _entity_label(kind: str, entity, entities: dict) -> str:
    if kind == "lease":
        tenant = entities.get(("tenant", entity.tenant_id))
        suite = entities.get(("suite", entity.suite_id))
        return f"{tenant.name if tenant else 'Lease'}" + (f" (suite {suite.suite_name})" if suite else "")
    if kind == "market_leasing_profile":
        return f"{entity.space_type} market leasing"
    if kind == "suite":
        return f"Suite {entity.suite_name}"
    if kind == "tenant":
        return entity.name
    return kind.replace("_", " ").capitalize()


@router.post("/valuations/{valuation_id}/what-if-chat")
async def what_if_chat(valuation_id: str, body: dict, db: AsyncSession = Depends(get_session)) -> dict:
    """Answer a what-if question by running the engine on a temporary copy of the model.

    Nothing is saved: changes are applied with autoflush off and rolled back before returning.
    """
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(422, "message is required")
    history = [str(h) for h in (body.get("history") or [])][-6:]
    valuation, entities, context = await _state(db, valuation_id)
    prop = entities[("property", valuation.property_id)]
    if prop.property_type in {"marina", "seniors_housing"}:
        raise HTTPException(422, "What-if questions are not available for marina or seniors housing valuations yet")
    # A storage unit mix replaces suites, leases and markets: the AI changes the model instead
    storage = (
        parse_storage_model(valuation.self_storage_assumptions_json) if prop.property_type == "self_storage" else None
    )
    if storage is not None:
        for kind in STORAGE_UNUSED_ENTITIES:
            context.pop(kind)
        context["storage_model"] = [{"id": valuation.id, **storage.model_dump(mode="json")}]
    try:
        answer = ask_scenario(message, history, context)
        operations = answer.get("changes", [])
        storage_changes, scenario_storage = [], None
        if storage is None:
            changes = resolve_scenario_changes(operations, entities)
        else:
            storage_ops = [op for op in operations if op["entity_type"] in {"storage_model", "storage_unit_type"}]
            changes = resolve_scenario_changes(
                [op for op in operations if op not in storage_ops], entities, storage_model=True
            )
            storage_changes, scenario_storage = resolve_storage_changes(storage_ops, storage, valuation.id)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    response = {"scenario": answer["scenario"], "changes": [], "base": None, "result": None}
    if not changes and not storage_changes:
        return response
    # Labels read model rows, so build them before the rollback expires those rows
    labelled = _serial_changes([
        {**c, "label": _entity_label(c["entity_type"], entities[(c["entity_type"], c["entity_id"])], entities)}
        for c in changes
    ] + [
        {**c, "label": "Storage model" if c["entity_type"] == "storage_model" else f"Unit type {c['entity_id']}"}
        for c in storage_changes
    ])
    service = ValuationService(db)
    try:
        with db.no_autoflush:
            base_inputs = await service.build_engine_inputs(valuation, prop)
            for change in changes:
                setattr(entities[(change["entity_type"], change["entity_id"])], change["field"], change["new_value"])
            scenario_inputs = await service.build_engine_inputs(valuation, prop)
            if storage_changes:  # on the engine inputs only; the stored model is never touched
                scenario_inputs.storage_model = scenario_storage
            has_price = bool(valuation.purchase_price)
        # The engine is CPU-bound; run both cases off the event loop
        base_run, scenario_run = await asyncio.gather(
            asyncio.to_thread(base_inputs.run), asyncio.to_thread(scenario_inputs.run)
        )
        base = _scenario_metrics(base_run, has_price)
        result = _scenario_metrics(scenario_run, has_price)
    except (ValueError, ZeroDivisionError) as exc:
        raise HTTPException(422, f"The engine could not run this scenario: {exc}") from exc
    finally:
        await db.rollback()
    response["changes"] = labelled
    response["base"] = json.loads(json.dumps(base, default=str))
    response["result"] = json.loads(json.dumps(result, default=str))
    return response
