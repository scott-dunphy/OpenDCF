"""
Automatic audit trail: a session flush hook records every create, update and
delete of input rows in audit_log, with before/after values per field and the
request that made the change.
"""
from __future__ import annotations

import json
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, insert, inspect
from sqlalchemy.orm import Session

from src.models.audit import AuditLog

# Set per request by middleware in src.main ("PUT /api/v1/loans/..."); None outside requests
audit_source: ContextVar[str | None] = ContextVar("audit_source", default=None)

AUDITED_TABLES = {
    "properties", "suites", "tenants", "leases", "rent_steps", "free_rent_periods",
    "lease_expense_recoveries", "market_leasing_profiles", "property_expenses", "property_other_income",
    "property_capital_projects", "recovery_structures", "recovery_structure_items", "valuations",
    "portfolios", "assumption_profiles", "portfolio_scenarios", "mortgage_loans", "risk_parameter_sets",
}

# Bookkeeping and bulky result blobs; scalar valuation results (NPV, IRR, ...) are kept
IGNORED_FIELDS = {
    "created_at", "updated_at", "status", "error_message", "last_run_at", "inputs_updated_at", "result_engine_version",
    "result_cash_flows_json", "result_tenant_cash_flows_json", "result_recovery_audit_json", "result_returns_json",
}


def jsonable(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def row_dict(obj) -> dict:
    """Column values of an ORM row, JSON-ready."""
    return {
        attr.key: jsonable(getattr(obj, attr.key))
        for attr in inspect(obj).mapper.column_attrs
        if attr.key not in IGNORED_FIELDS
    }


def _property_id(obj) -> str | None:
    if obj.__tablename__ == "properties":
        return obj.id
    return getattr(obj, "property_id", None)


def _entry(obj, action: str, changes: dict) -> dict:
    return {
        "entity_type": obj.__tablename__,
        "entity_id": obj.id,
        "property_id": _property_id(obj),
        "action": action,
        "changes_json": json.dumps(changes),
        "source": audit_source.get() or "system",
    }


def _as_stored(attr, value):
    """
    Normalize to what the database keeps, so re-saving an unchanged value is not a change:
    Decimals rounded to the column scale and compared as floats (SQLite stores NUMERIC as REAL),
    empty lists as null.
    """
    if value == []:
        return None
    scale = getattr(attr.columns[0].type, "scale", None)
    if isinstance(value, Decimal) and scale is not None:
        return float(value.quantize(Decimal(1).scaleb(-scale)))
    return value


def _changes(obj) -> dict:
    """{field: [before, after]} for columns changed in this flush."""
    state = inspect(obj)
    out = {}
    for attr in state.mapper.column_attrs:
        if attr.key in IGNORED_FIELDS:
            continue
        hist = state.attrs[attr.key].history
        if not hist.has_changes():
            continue
        before = _as_stored(attr, hist.deleted[0] if hist.deleted else None)
        after = _as_stored(attr, hist.added[0] if hist.added else None)
        if before == after:
            continue
        out[attr.key] = [jsonable(before), jsonable(after)]
    return out


@event.listens_for(Session, "after_flush")
def _record(session: Session, flush_context) -> None:
    # The new/dirty/deleted lists and attribute history still hold their pre-flush state here
    rows = []
    for obj in session.new:
        if getattr(obj, "__tablename__", None) in AUDITED_TABLES:
            rows.append(_entry(obj, "create", {k: [None, v] for k, v in row_dict(obj).items() if v is not None}))
    for obj in session.dirty:
        if getattr(obj, "__tablename__", None) in AUDITED_TABLES and obj not in session.deleted:
            changes = _changes(obj)
            if changes:
                rows.append(_entry(obj, "update", changes))
    for obj in session.deleted:
        if getattr(obj, "__tablename__", None) in AUDITED_TABLES:
            rows.append(_entry(obj, "delete", {k: [v, None] for k, v in row_dict(obj).items() if v is not None}))
    if rows:
        session.connection().execute(insert(AuditLog), rows)
