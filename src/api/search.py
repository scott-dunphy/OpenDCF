"""Global search for the command palette: properties, valuations and tenants by name."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from src.api.properties import INTAKE_PREFIX
from src.db.session import get_session
from src.models.lease import Tenant
from src.models.property import Property
from src.models.valuation import Valuation

router = APIRouter(prefix="/api/v1/search", tags=["search"])


class SearchResult(BaseModel):
    kind: str  # "property" | "valuation" | "tenant"
    id: str
    title: str
    subtitle: str
    property_id: str | None
    href: str


def _rank(name: str, q: str) -> int:
    """0 = prefix match, 1 = word-start match, 2 = substring elsewhere."""
    n = name.lower()
    if n.startswith(q):
        return 0
    if any(word.startswith(q) for word in n.replace("-", " ").split()):
        return 1
    return 2


def _not_intake():
    return (Property.external_id.is_(None)) | (~Property.external_id.startswith(INTAKE_PREFIX))


@router.get("", response_model=list[SearchResult])
async def search(
    q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
) -> list[SearchResult]:
    q = q.strip().lower()
    if not q:
        return []
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    scored: list[tuple[int, int, str, SearchResult]] = []

    props = (await db.execute(
        select(Property)
        .options(load_only(Property.id, Property.name, Property.city, Property.state, Property.property_type))
        .where(_not_intake(), func.lower(Property.name).like(pattern, escape="\\"))
    )).scalars()
    for p in props:
        place = ", ".join(x for x in (p.city, p.state) if x)
        subtitle = " · ".join(x for x in (place, p.property_type.replace("_", " ").title()) if x)
        scored.append((_rank(p.name, q), 0, p.name.lower(), SearchResult(
            kind="property", id=p.id, title=p.name, subtitle=subtitle,
            property_id=p.id, href=f"#/property/{p.id}",
        )))

    vals = (await db.execute(
        select(Valuation.id, Valuation.name, Valuation.status, Valuation.property_id, Property.name)
        .join(Property, Valuation.property_id == Property.id)
        .where(_not_intake(), func.lower(Valuation.name).like(pattern, escape="\\"))
    )).all()
    for v_id, v_name, v_status, v_prop_id, prop_name in vals:
        scored.append((_rank(v_name, q), 1, v_name.lower(), SearchResult(
            kind="valuation", id=v_id, title=v_name, subtitle=f"{prop_name} · {v_status}",
            property_id=v_prop_id, href=f"#/valuation/{v_id}",
        )))

    # Each valuation has its own tenant rows: one result per tenant name and property
    tenants = (await db.execute(
        select(func.min(Tenant.id), Tenant.name, Property.id, Property.name)
        .join(Property, Property.id == Tenant.property_id)
        .where(_not_intake(), func.lower(Tenant.name).like(pattern, escape="\\"))
        .group_by(Tenant.name, Property.id, Property.name)
    )).all()
    for t_id, t_name, p_id, p_name in tenants:
        scored.append((_rank(t_name, q), 2, t_name.lower(), SearchResult(
            kind="tenant", id=t_id, title=t_name, subtitle=p_name,
            property_id=p_id, href=f"#/property/{p_id}",
        )))

    scored.sort(key=lambda s: s[:3])
    return [s[3] for s in scored[:limit]]
