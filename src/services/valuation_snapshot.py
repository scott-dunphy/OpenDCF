"""Frozen valuation inputs (docs/valuation-lifecycle-plan.md).

`capture` copies every input row a valuation runs on (the property, its rent roll, market,
expenses, other income, capital, recovery structures and the valuation itself) exactly, ids
included. `restored` rebuilds those rows in a private in-memory database so the engine can re-run
a frozen valuation without reading, or ever writing, the live model.
"""
from __future__ import annotations

import subprocess
from contextlib import asynccontextmanager
from functools import cache
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal
from typing import Any, AsyncIterator

from types import SimpleNamespace

from sqlalchemy import Table, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.models import Base  # noqa: F401  (all models registered on Base.metadata)
from src.models.capital import PropertyCapitalProject
from src.models.expense import PropertyExpense
from src.models.lease import FreeRentPeriod, Lease, LeaseExpenseRecovery, RentStep, Tenant
from src.models.market import MarketLeasingProfile
from src.models.other_income import PropertyOtherIncome
from src.models.property import Property, Suite
from src.models.recovery_pool import RecoveryPool
from src.models.recovery_structure import RecoveryStructure, RecoveryStructureItem
from src.models.valuation import Valuation

SNAPSHOT_FORMAT = 1


class SnapshotRestoreError(ValueError):
    """A frozen valuation's inputs could not be rebuilt (e.g. the schema has moved on since)."""

# Valuation columns that describe the review, not the model
REVIEW_COLUMNS = {"review_status", "snapshot_id"}


def _tag(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"$d": str(value)}
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, (list, tuple)):
        return [_tag(v) for v in value]
    return value


def _untag(value: Any) -> Any:
    if isinstance(value, dict) and len(value) == 1:
        (key, raw), = value.items()
        if key == "$d":
            return Decimal(raw)
        if key == "$dt":
            return datetime.fromisoformat(raw)
        if key == "$date":
            return date.fromisoformat(raw)
    if isinstance(value, list):
        return [_untag(v) for v in value]
    return value


def _rows(objs, exclude: set[str] = frozenset()) -> list[dict]:
    return [
        {c.key: _tag(getattr(o, c.key)) for c in o.__table__.columns if c.key not in exclude}
        for o in objs
    ]


async def _all(db: AsyncSession, stmt) -> list:
    return list((await db.execute(stmt)).scalars().all())


async def capture(db: AsyncSession, valuation: Valuation) -> dict:
    """Every input row the valuation runs on, as JSON-safe data."""
    vid = valuation.id
    prop = await db.get(Property, valuation.property_id)
    suites = await _all(db, select(Suite).where(Suite.valuation_id == vid))
    leases = await _all(db, select(Lease).where(Lease.suite_id.in_([s.id for s in suites]))) if suites else []
    lease_ids = [l.id for l in leases]
    structures = await _all(db, select(RecoveryStructure).where(RecoveryStructure.valuation_id == vid))

    def by_lease(model):
        return _all(db, select(model).where(model.lease_id.in_(lease_ids))) if lease_ids else _none()

    def owned(model):
        return _all(db, select(model).where(model.valuation_id == vid))

    tables = {
        "properties": [prop],
        "tenants": await owned(Tenant),
        "suites": suites,
        "market_leasing_profiles": await owned(MarketLeasingProfile),
        "recovery_structures": structures,
        "recovery_pools": await owned(RecoveryPool),
        "recovery_structure_items": await _all(db, select(RecoveryStructureItem).where(
            RecoveryStructureItem.recovery_structure_id.in_([s.id for s in structures])
        )) if structures else [],
        "leases": leases,
        "rent_steps": await by_lease(RentStep),
        "free_rent_periods": await by_lease(FreeRentPeriod),
        "lease_expense_recoveries": await by_lease(LeaseExpenseRecovery),
        "property_expenses": await owned(PropertyExpense),
        "property_other_income": await owned(PropertyOtherIncome),
        "property_capital_projects": await owned(PropertyCapitalProject),
    }
    data = {name: _rows(objs) for name, objs in tables.items()}
    # Results stay (repricing reads the annual cash flows and checks the saved value) except the two
    # bulky per-tenant blobs, which are stored once, in the snapshot's results
    blobs = {"result_tenant_cash_flows_json", "result_recovery_audit_json"}
    data["valuations"] = _rows([valuation], REVIEW_COLUMNS | blobs)
    return {"format": SNAPSHOT_FORMAT, "valuation_id": valuation.id, "tables": data}


@cache
def engine_version() -> str:
    """The code that produced a frozen result: git commit, marked when the tree had local changes."""
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                             text=True, timeout=5, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{sha}+local" if dirty else sha
    except (OSError, subprocess.SubprocessError):
        from src.main import app

        return f"v{app.version}"


async def _none() -> list:
    return []


async def schema_revision(db: AsyncSession) -> str | None:
    """The database's alembic revision, recorded with each snapshot (None for a database built
    without alembic, as in tests)."""
    has_table = (await db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'")
    )).scalar()
    return (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar() if has_table else None


def frozen_rows(snapshot: dict, table: str) -> list[dict]:
    """One table's rows from a snapshot, with Decimals and dates restored."""
    return [{k: _untag(v) for k, v in r.items()} for r in snapshot["tables"].get(table, [])]


def frozen_property(snapshot: dict) -> SimpleNamespace:
    """The property row as frozen, read-only (attribute access like the model)."""
    return SimpleNamespace(**frozen_rows(snapshot, "properties")[0])


def _upgraded(snapshot: dict) -> dict[str, list[dict]]:
    """Snapshot tables in today's shape. Before valuation-owned market leasing (b7e2c4d9a1f3)
    profiles had no valuation_id and suites pointed at a profile id instead of a space type.
    Before valuation-owned inputs (docs/valuation-owned-inputs-plan.md) no input row had a
    valuation_id and operating models were on the property."""
    from src.services.valuation_clone import HOLD_FROM_MODEL_TYPES, VALUATION_TABLES

    tables = dict(snapshot["tables"])
    vid = snapshot["valuation_id"]
    for name in VALUATION_TABLES - {"market_leasing_profiles"}:
        rows = tables.get(name, [])
        if rows and "valuation_id" not in rows[0]:
            tables[name] = [{**r, "valuation_id": vid} for r in rows]
    valuations = tables.get("valuations", [])
    props = tables.get("properties", [])
    if valuations and props and "self_storage_assumptions_json" not in valuations[0]:
        prop = props[0]
        tables["valuations"] = [{
            **v,
            "analysis_start_date_override": v.get("analysis_start_date_override") or prop.get("analysis_start_date"),
            "analysis_period_months_override": v.get("analysis_period_months_override")
            or (None if prop.get("property_type") in HOLD_FROM_MODEL_TYPES else prop.get("analysis_period_months")),
            **{k: prop.get(k) or v.get(k) for k in (
                "marina_assumptions_json", "seniors_housing_assumptions_json", "self_storage_assumptions_json")},
        } for v in valuations]
    profiles = tables.get("market_leasing_profiles", [])
    if profiles and "valuation_id" not in profiles[0]:
        tables["market_leasing_profiles"] = [{**r, "valuation_id": snapshot["valuation_id"]} for r in profiles]
    suites = tables.get("suites", [])
    if suites and "market_leasing_profile_id" in suites[0]:
        space = {r["id"]: r["space_type"] for r in profiles}
        tables["suites"] = [{**r, "market_space_type": space.get(r["market_leasing_profile_id"])} for r in suites]
    return tables


def frozen_tables(snapshot: dict) -> dict[str, list[dict]]:
    """Every table of a snapshot in today's shape, with Decimals and dates restored."""
    return {name: [{k: _untag(v) for k, v in r.items()} for r in rows] for name, rows in _upgraded(snapshot).items()}


@asynccontextmanager
async def restored(snapshot: dict) -> AsyncIterator[AsyncSession]:
    """A session on a private in-memory database holding exactly the snapshot's rows, ids unchanged.

    Nothing done in it reaches the real database; it is discarded on exit. Columns the current
    schema no longer has are dropped; columns added since take their defaults.
    """
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    try:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                for name, rows in _upgraded(snapshot).items():
                    if not rows:
                        continue
                    table: Table = Base.metadata.tables[name]
                    known = set(table.c.keys())
                    # Core inserts: no ORM hooks, so stamps such as inputs_updated_at stay as captured
                    await conn.execute(
                        insert(table), [{k: _untag(v) for k, v in r.items() if k in known} for r in rows]
                    )
        except Exception as exc:  # noqa: BLE001 - reported as one clear error
            raise SnapshotRestoreError(
                "The frozen inputs could not be rebuilt with this version of the app "
                f"({type(exc).__name__}). The reviewed results are unaffected."
            ) from exc
        async with async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)() as session:
            yield session
    finally:
        await engine.dispose()
