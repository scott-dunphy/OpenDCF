"""Merge duplicate properties: one property keeps every valuation and property-level row of the others.

A property is a folder (docs/valuation-owned-inputs-plan.md), so merging only re-points property_id.
Rows are moved with Core statements, which bypass the ORM flush hooks: the frozen-valuation lock
(moving a folder is not a model change) and input staleness (nothing a valuation runs on changes,
except the property-level fields listed in `ENGINE_FIELDS`, which are reported). Snapshots are not
touched; they keep the property as it was frozen, so a frozen valuation still verifies.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import delete, exists, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Base
from src.models.audit import AuditLog
from src.models.property import Property
from src.models.valuation import Valuation
from src.services.audit import audit_source, jsonable

# Property fields a draft valuation runs on (overrides aside); a source that differs from the target
# on any of them values differently after the merge
ENGINE_FIELDS = ("total_area", "fiscal_year_end_month", "ownership_pct", "analysis_start_date",
                 "analysis_period_months")

# Unique per (property, x): a source row the target already has is dropped, not moved
_UNIQUE_WITH = {"comparable_selections": "sale_id", "portfolio_properties": "portfolio_id"}


class MergeError(ValueError):
    """The properties cannot be merged."""


def _property_refs() -> list[tuple]:
    """(table, column) for every column that references properties.id, plus the audit log's."""
    refs = [(t, c) for t in Base.metadata.sorted_tables for c in t.columns
            if any(fk.column.table.name == "properties" for fk in c.foreign_keys)]
    return refs + [(AuditLog.__table__, AuditLog.__table__.c.property_id)]


def differences(target: Property, source: Property) -> dict:
    """{field: [source value, target value]} for engine fields that differ."""
    return {f: [jsonable(getattr(source, f)), jsonable(getattr(target, f))]
            for f in ENGINE_FIELDS if getattr(source, f) != getattr(target, f)}


async def merge(db: AsyncSession, target_id: str, source_ids: list[str], exclude_prefix: str | None = None) -> dict:
    """Move everything from the sources to the target and delete the sources, in one transaction."""
    source_ids = list(dict.fromkeys(source_ids))
    if not source_ids:
        raise MergeError("Choose at least one property to merge in")
    if target_id in source_ids:
        raise MergeError("A property cannot be merged into itself")
    props = {p.id: p for p in (await db.execute(
        select(Property).where(Property.id.in_([target_id, *source_ids]))
    )).scalars()}
    target = props.get(target_id)
    missing = [i for i in [target_id, *source_ids] if i not in props]
    if missing:
        raise LookupError(f"Property not found: {', '.join(missing)}")
    if exclude_prefix and any((p.external_id or "").startswith(exclude_prefix) for p in props.values()):
        raise MergeError("An appraisal import's working property cannot be merged")
    sources = [props[i] for i in source_ids]
    for s in sources:
        if (s.property_type, s.area_unit) != (target.property_type, target.area_unit):
            raise MergeError(
                f"'{s.name}' is {s.property_type} measured in {s.area_unit}; '{target.name}' is "
                f"{target.property_type} in {target.area_unit}. Only properties of the same type merge."
            )
    moved_valuations = list((await db.execute(
        select(Valuation.id, Valuation.name, Valuation.review_status, Valuation.property_id)
        .where(Valuation.property_id.in_(source_ids))
    )).all())
    report = {
        "target_id": target_id,
        "merged": [{"id": s.id, "name": s.name, "differences": differences(target, s)} for s in sources],
        "valuations": [{"id": v.id, "name": v.name, "review_status": v.review_status, "from_property_id": v.property_id}
                       for v in moved_valuations],
        "moved": {}, "dropped": {},
    }
    deleted_rows = {s.id: {k: v for k, v in _row(s).items() if v is not None} for s in sources}
    try:
        for table, col in _property_refs():
            key = _UNIQUE_WITH.get(table.name)
            moved = 0
            # One source at a time, so a row two sources share is kept once
            for batch in ([[sid] for sid in source_ids] if key else [source_ids]):
                if key:
                    kept = select(table.c[key]).where(col == target_id)
                    dropped = (await db.execute(
                        delete(table).where(col.in_(batch), table.c[key].in_(kept))
                    )).rowcount
                    if dropped:
                        report["dropped"][table.name] = report["dropped"].get(table.name, 0) + dropped
                moved += (await db.execute(
                    update(table).where(col.in_(batch)).values({col.name: target_id})
                )).rowcount
            if moved:
                name = table.name if col.name == "property_id" else f"{table.name}.{col.name}"
                report["moved"][name] = report["moved"].get(name, 0) + moved
        for table, col in _property_refs():  # ON DELETE CASCADE would silently take anything left
            if (await db.execute(select(exists().where(col.in_(source_ids))))).scalar():
                raise RuntimeError(f"{table.name}.{col.name} still references a merged property")
        await db.execute(delete(Property.__table__).where(Property.__table__.c.id.in_(source_ids)))
        source = audit_source.get() or "system"
        await db.execute(insert(AuditLog), [
            {"entity_type": "properties", "entity_id": target_id, "property_id": target_id, "action": "update",
             "changes_json": json.dumps({"merged_from": [None, [s.id for s in sources]]}), "source": source},
            *({"entity_type": "properties", "entity_id": sid, "property_id": target_id, "action": "delete",
               "changes_json": json.dumps({k: [v, None] for k, v in row.items()} | {"merged_into": [None, target_id]}),
               "source": source} for sid, row in deleted_rows.items()),
        ])
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for s in sources:
        db.expunge(s)
    return report


def _row(p: Property) -> dict:
    return {c.key: jsonable(getattr(p, c.key)) for c in Property.__table__.columns
            if c.key not in {"created_at", "updated_at"}}


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


async def duplicate_groups(db: AsyncSession, exclude_prefix: str) -> list[dict]:
    """Groups of properties that are likely the same building: same name and type, and the same
    area or address."""
    props = list((await db.execute(
        select(Property).where((Property.external_id.is_(None)) | (~Property.external_id.startswith(exclude_prefix)))
        .order_by(Property.created_at)
    )).scalars())
    vals: dict[str, list] = {}
    for v in (await db.execute(select(Valuation.id, Valuation.name, Valuation.review_status, Valuation.property_id)
                               .order_by(Valuation.created_at))).all():
        vals.setdefault(v.property_id, []).append({"id": v.id, "name": v.name, "review_status": v.review_status})

    clusters: list[list[Property]] = []
    for p in props:
        address = _norm(p.address_line1)
        for c in clusters:
            first = c[0]
            if (_norm(first.name), first.property_type) == (_norm(p.name), p.property_type) and any(
                (q.total_area == p.total_area and q.area_unit == p.area_unit)
                or (address and _norm(q.address_line1) == address) for q in c
            ):
                c.append(p)
                break
        else:
            clusters.append([p])
    return [
        {"name": c[0].name, "property_type": c[0].property_type, "properties": [
            {"id": p.id, "name": p.name, "property_type": p.property_type, "total_area": p.total_area,
             "area_unit": p.area_unit, "address_line1": p.address_line1, "city": p.city, "state": p.state,
             "created_at": p.created_at, "valuations": vals.get(p.id, [])} for p in c
        ]}
        for c in clusters if len(c) > 1
    ]
