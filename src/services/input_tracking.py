"""
Input staleness: a session flush hook stamps valuations.inputs_updated_at whenever one of the
valuation's own inputs changes (suites, leases and their schedules, tenants, market leasing,
expenses, other income, recovery structures and pools, capital projects), and on every valuation
of a property whose modeling fields change. A valuation whose last_run_at is older is stale.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import column, event, inspect, select, table, update
from sqlalchemy.orm import Session

from src.services.audit import _changes

# Property columns that only describe or label the asset; editing them keeps results current
_COSMETIC_PROPERTY_FIELDS = {
    "name", "address_line1", "address_line2", "city", "state", "zip_code",
    "latitude", "longitude", "external_id", "comment", "year_built", "inputs_updated_at",
    # Defaults for new valuations only; each valuation has its own
    "analysis_start_date", "analysis_period_months",
    "marina_assumptions_json", "seniors_housing_assumptions_json", "self_storage_assumptions_json",
    "cbsa_code", "quality_score",
}

# Rows a valuation owns directly (valuation_id column)
_DIRECT = {
    "suites", "tenants", "property_expenses", "property_other_income",
    "property_capital_projects", "recovery_structures", "recovery_pools", "market_leasing_profiles",
}
_LEASE_CHILDREN = {"rent_steps", "free_rent_periods", "lease_expense_recoveries"}

_suites = table("suites", column("id"), column("valuation_id"))
_leases = table("leases", column("id"), column("suite_id"))
_structures = table("recovery_structures", column("id"), column("valuation_id"))
_valuations = table("valuations", column("id"), column("property_id"))


def _lookup(conn, query) -> str | None:
    return conn.execute(query).scalar()


def valuation_id_of(conn, obj) -> str | None:
    """The valuation that owns an input row (None for anything else)."""
    name = getattr(obj, "__tablename__", None)
    if name in _DIRECT:
        return obj.valuation_id
    if name == "leases":
        return _lookup(conn, select(_suites.c.valuation_id).where(_suites.c.id == obj.suite_id))
    if name in _LEASE_CHILDREN:
        return _lookup(
            conn,
            select(_suites.c.valuation_id)
            .join(_leases, _leases.c.suite_id == _suites.c.id)
            .where(_leases.c.id == obj.lease_id),
        )
    if name == "recovery_structure_items":
        return _lookup(
            conn, select(_structures.c.valuation_id).where(_structures.c.id == obj.recovery_structure_id)
        )
    return None


def _tracked(obj) -> bool:
    name = getattr(obj, "__tablename__", None)
    return name in _DIRECT or name in _LEASE_CHILDREN or name in {"properties", "leases", "recovery_structure_items"}


@event.listens_for(Session, "after_flush")
def _stamp(session: Session, flush_context) -> None:
    candidates = [o for o in session.new if _tracked(o) and o.__tablename__ != "properties"]
    candidates += [o for o in session.deleted if _tracked(o) and o.__tablename__ != "properties"]
    for obj in session.dirty:
        if not _tracked(obj) or obj in session.deleted:
            continue
        changes = _changes(obj)
        if obj.__tablename__ == "properties":
            changes = {k: v for k, v in changes.items() if k not in _COSMETIC_PROPERTY_FIELDS}
        if changes:
            candidates.append(obj)
    if not candidates:
        return
    conn = session.connection()
    ids = {vid for vid in (valuation_id_of(conn, o) for o in candidates) if vid}
    # A modeling change to the property itself (area, type...) affects all its valuations
    property_ids = {o.id for o in candidates if o.__tablename__ == "properties"}
    if property_ids:
        ids |= set(conn.execute(
            select(_valuations.c.id).where(_valuations.c.property_id.in_(property_ids))
        ).scalars())
    if not ids:
        return
    from src.models.valuation import Valuation

    now = datetime.now(timezone.utc)
    conn.execute(update(Valuation.__table__).where(Valuation.__table__.c.id.in_(ids)).values(inputs_updated_at=now))
    for obj in session.identity_map.values():
        if isinstance(obj, Valuation) and obj.id in ids:
            # Keep the in-memory row in step without marking it dirty
            inspect(obj).committed_state.pop("inputs_updated_at", None)
            obj.__dict__["inputs_updated_at"] = now
