from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

import src.engine
from src.api.validation import update_changes
from src.api.valuations import list_valuations
from src.db.session import get_session
from src.models.property import Property, Suite
from src.models.valuation import Valuation
from src.schemas.property import (
    PropertyCreate,
    PropertyList,
    PropertyRead,
    PropertySummary,
    PropertyUpdate,
    ValuationSnapshot,
)
from src.schemas.valuation import ValuationRead
from src.services import property_merge

# Upload-first appraisal imports park their source model in a temporary property
INTAKE_PREFIX = "__appraisal_intake__:"

router = APIRouter(prefix="/api/v1/properties", tags=["properties"])


@router.post("", response_model=PropertyRead, status_code=status.HTTP_201_CREATED)
async def create_property(
    body: PropertyCreate,
    db: AsyncSession = Depends(get_session),
) -> PropertyRead:
    prop = Property(**body.model_dump())  # CBSA filled on insert when blank (models/property.py)
    db.add(prop)
    await db.commit()
    await db.refresh(prop)
    return prop


@router.get("", response_model=list[PropertyList])
async def list_properties(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
) -> list[PropertyList]:
    result = await db.execute(select(Property).offset(skip).limit(limit))
    return list(result.scalars().all())


@router.get("/summary", response_model=list[PropertySummary])
async def property_summaries(db: AsyncSession = Depends(get_session)) -> list[PropertySummary]:
    """
    One row per property for the home screen: size, suite and valuation counts, and the
    primary valuation (the most recently run completed one), flagged stale when inputs
    changed after it ran. Temporary appraisal-intake properties are left out.
    """
    props = list((await db.execute(
        select(Property).where(
            (Property.external_id.is_(None)) | (~Property.external_id.startswith(INTAKE_PREFIX))
        ).order_by(Property.name)
    )).scalars())
    suite_counts = dict((await db.execute(
        select(Suite.valuation_id, func.count()).group_by(Suite.valuation_id)
    )).all())
    valuations = list((await db.execute(
        select(Valuation).options(load_only(
            Valuation.id, Valuation.property_id, Valuation.name, Valuation.status,
            Valuation.result_npv, Valuation.result_irr, Valuation.result_going_in_cap_rate,
            Valuation.purchase_price, Valuation.last_run_at, Valuation.updated_at, Valuation.review_status,
            Valuation.inputs_updated_at, Valuation.result_engine_version,
        ))
    )).scalars())
    by_property: dict[str, list[Valuation]] = {}
    for v in valuations:
        by_property.setdefault(v.property_id, []).append(v)

    out = []
    for p in props:
        vals = by_property.get(p.id, [])
        completed = [v for v in vals if v.status == "completed"]
        primary = max(completed, key=lambda v: v.last_run_at or v.updated_at, default=None)
        shown = primary or max(vals, key=lambda v: v.updated_at, default=None)
        snapshot = None
        if primary is not None:
            stale_reason = _stale_reason(primary)
            snapshot = ValuationSnapshot(
                id=primary.id, name=primary.name, value=primary.result_npv,
                going_in_cap_rate=primary.result_going_in_cap_rate,
                irr=primary.result_irr if primary.purchase_price else None,
                purchase_price=primary.purchase_price, last_run_at=primary.last_run_at,
                is_stale=stale_reason is not None, stale_reason=stale_reason,
            )
        out.append(PropertySummary(
            id=p.id, name=p.name, property_type=p.property_type, city=p.city, state=p.state,
            market=p.market, total_area=p.total_area, area_unit=p.area_unit,
            ownership_pct=p.ownership_pct, latitude=p.latitude, longitude=p.longitude,
            suite_count=suite_counts.get(shown.id, 0) if shown else 0, valuation_count=len(vals),
            inputs_updated_at=max((v.inputs_updated_at for v in vals if v.inputs_updated_at), key=_naive, default=None),
            primary_valuation=snapshot,
        ))
    return out


@router.get("/duplicates")
async def duplicate_properties(db: AsyncSession = Depends(get_session)) -> list[dict]:
    """Likely duplicates: same name and type, and the same area or address."""
    return await property_merge.duplicate_groups(db, INTAKE_PREFIX)


class MergeRequest(BaseModel):
    source_ids: list[str]


@router.post("/{property_id}/merge")
async def merge_properties(property_id: str, body: MergeRequest, db: AsyncSession = Depends(get_session)) -> dict:
    """Move every valuation and property-level row of the source properties here, then delete them."""
    try:
        return await property_merge.merge(db, property_id, body.source_ids, INTAKE_PREFIX)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except property_merge.MergeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _stale_reason(v: Valuation) -> str | None:
    """Why a completed valuation needs a re-run: its inputs changed, or the engine did."""
    if v.review_status != "draft":  # frozen: re-running is not an option (verify instead)
        return None
    ran = v.last_run_at or v.updated_at
    if v.inputs_updated_at is not None and ran is not None and _naive(ran) < _naive(v.inputs_updated_at):
        return "inputs"
    if src.engine.engine_outdated(v.result_engine_version):
        return "engine"
    return None


def _naive(dt):
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


class PropertyWorkspace(BaseModel):
    """The property page: the property and its valuations."""
    property: PropertyRead
    valuations: list[ValuationRead]


@router.get("/{property_id}/workspace", response_model=PropertyWorkspace)
async def property_workspace(property_id: str, db: AsyncSession = Depends(get_session)) -> PropertyWorkspace:
    prop = await get_property(property_id, db)  # 404s when missing
    return PropertyWorkspace(property=prop, valuations=await list_valuations(property_id, db))


@router.get("/{property_id}", response_model=PropertyRead)
async def get_property(
    property_id: str,
    db: AsyncSession = Depends(get_session),
) -> PropertyRead:
    prop = await db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


@router.put("/{property_id}", response_model=PropertyRead)
async def update_property(
    property_id: str,
    body: PropertyUpdate,
    db: AsyncSession = Depends(get_session),
) -> PropertyRead:
    result = await db.execute(select(Property).where(Property.id == property_id))
    prop = result.scalar_one_or_none()
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")
    from src.services import cbsa

    data = update_changes(Property, body)
    if data.get("cbsa_code") == "":
        data["cbsa_code"] = None
    elif "cbsa_code" not in data and data.get("zip_code") and data["zip_code"] != prop.zip_code:
        after = {f: data.get(f, getattr(prop, f)) for f in ("market", "city", "state")}
        data["cbsa_code"] = cbsa.for_property(data["zip_code"], after["market"], after["city"], after["state"])
    for field, value in data.items():
        setattr(prop, field, value)
    await db.commit()
    await db.refresh(prop)
    return prop


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property(
    property_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(select(Property).where(Property.id == property_id))
    prop = result.scalar_one_or_none()
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")
    await db.delete(prop)
    await db.commit()
