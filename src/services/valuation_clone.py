"""Copy a valuation's whole model (docs/valuation-owned-inputs-plan.md).

A valuation owns its rent roll, tenants, market leasing, expenses, other income, capital and
recovery setup. Copying gives every row a new id and points every reference at the copy.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Base  # noqa: F401  (all tables registered on Base.metadata)
from src.models.valuation import Valuation

# Owned tables, parents before children (insert order)
OWNED_TABLES = (
    "tenants",
    "suites",
    "recovery_structures",
    "recovery_structure_items",
    "recovery_pools",
    "market_leasing_profiles",
    "leases",
    "rent_steps",
    "free_rent_periods",
    "lease_expense_recoveries",
    "property_expenses",
    "property_other_income",
    "property_capital_projects",
)

# Tables carrying valuation_id / property_id (children reach the valuation through their parent)
VALUATION_TABLES = {
    "tenants", "suites", "recovery_structures", "recovery_pools", "market_leasing_profiles",
    "property_expenses", "property_other_income", "property_capital_projects",
}

# Columns holding another owned row's id
REFERENCES: dict[str, dict[str, str]] = {
    "recovery_structure_items": {"recovery_structure_id": "recovery_structures"},
    "market_leasing_profiles": {
        "next_profile_id": "market_leasing_profiles",
        "recovery_structure_id": "recovery_structures",
    },
    "leases": {"suite_id": "suites", "tenant_id": "tenants", "recovery_structure_id": "recovery_structures"},
    "rent_steps": {"lease_id": "leases"},
    "free_rent_periods": {"lease_id": "leases"},
    "lease_expense_recoveries": {"lease_id": "leases"},
}


def remap(tables: dict[str, list[dict]], valuation_id: str, property_id: str) -> dict[str, list[dict]]:
    """The rows with new ids, every reference re-pointed, owned by the given valuation.

    A reference to a row that was not copied becomes None.
    """
    new_ids = {name: {r["id"]: str(uuid.uuid4()) for r in tables.get(name, [])} for name in OWNED_TABLES}
    out: dict[str, list[dict]] = {}
    for name in OWNED_TABLES:
        refs = REFERENCES.get(name, {})
        rows = []
        for r in tables.get(name, []):
            row = {**r, "id": new_ids[name][r["id"]]}
            for column, target in refs.items():
                if row.get(column) is not None:
                    row[column] = new_ids[target].get(row[column])
            if name in VALUATION_TABLES:
                row["valuation_id"] = valuation_id
                row["property_id"] = property_id
            if name == "recovery_pools":
                row["excluded_suite_ids"] = [
                    new_ids["suites"][s] for s in (row.get("excluded_suite_ids") or []) if s in new_ids["suites"]
                ]
            rows.append(row)
        out[name] = rows
    return out


async def insert_tables(db: AsyncSession, tables: dict[str, list[dict[str, Any]]]) -> None:
    """Insert plain rows (no ORM events) in dependency order; unknown columns are dropped."""
    for name in OWNED_TABLES:
        rows = tables.get(name) or []
        if not rows:
            continue
        table = Base.metadata.tables[name]
        known = set(table.c.keys())
        await db.execute(insert(table), [{k: v for k, v in r.items() if k in known} for r in rows])


async def source_tables(db: AsyncSession, source: Valuation) -> dict[str, list[dict]]:
    """The source's input rows: as frozen when it is frozen, else its live rows."""
    from src.services.valuation_snapshot import capture, frozen_tables

    if source.review_status != "draft" and source.snapshot_id:
        from src.models.valuation import ValuationSnapshot

        snapshot = await db.get(ValuationSnapshot, source.snapshot_id)
        if snapshot is not None:
            import json

            return frozen_tables(json.loads(snapshot.inputs_json))
    return frozen_tables(await capture(db, source))


async def copy_inputs(db: AsyncSession, source: Valuation, target: Valuation) -> None:
    """Give `target` (already flushed) its own copy of the source's whole model."""
    tables = await source_tables(db, source)
    await insert_tables(db, remap(tables, target.id, target.property_id))


# Their operating model's hold_years is the hold unless a valuation sets one, so a new valuation
# of these types does not take the property's default hold period
HOLD_FROM_MODEL_TYPES = {"marina", "seniors_housing"}

# Valuation columns a copy does not take: identity, run state, review state, results
_NOT_COPIED = {"id", "created_at", "updated_at", "status", "error_message", "last_run_at", "inputs_updated_at",
               "name", "review_status", "snapshot_id", "prior_valuation_id"}


async def copy_valuation(db: AsyncSession, source: Valuation, name: str, **changes: Any) -> Valuation:
    """A new draft valuation with the source's assumptions and its own copy of the whole model.

    A frozen source is copied as it was frozen. Results are not copied.
    """
    from src.services.valuation_snapshot import frozen_tables

    if source.review_status != "draft" and source.snapshot_id:
        import json

        from src.models.valuation import ValuationSnapshot

        snapshot = await db.get(ValuationSnapshot, source.snapshot_id)
        row = frozen_tables(json.loads(snapshot.inputs_json))["valuations"][0] if snapshot else None
    else:
        row = None
    values = {
        c.key: (row.get(c.key) if row is not None and c.key in row else getattr(source, c.key))
        for c in Valuation.__table__.columns
        if c.key not in _NOT_COPIED and not c.key.startswith("result_")
    }
    copy = Valuation(**{**values, **changes}, name=name)
    db.add(copy)
    await db.flush()
    await copy_inputs(db, source, copy)
    await copy_documents(db, source.id, copy.id)
    return copy


async def copy_documents(db: AsyncSession, source_id: str, target_id: str) -> None:
    """Link the source's documents and extracted facts to the copy, so document review and AI
    updates carry on from the copy."""
    from sqlalchemy import select

    from src.models.document import ExtractedFact, ValuationDocument

    for link in (await db.execute(select(ValuationDocument).where(ValuationDocument.valuation_id == source_id))).scalars():
        db.add(ValuationDocument(valuation_id=target_id, document_id=link.document_id,
                                 relevant_override=link.relevant_override))
    skip = {"id", "valuation_id", "created_at", "updated_at"}
    for fact in (await db.execute(select(ExtractedFact).where(ExtractedFact.valuation_id == source_id))).scalars():
        db.add(ExtractedFact(valuation_id=target_id,
                             **{c.key: getattr(fact, c.key) for c in ExtractedFact.__table__.columns if c.key not in skip}))


# Types valued from expense lines (marina and seniors carry fees in their own models)
_EXPENSE_LINE_TYPES = {"office", "retail", "industrial", "multifamily", "mixed_use", "self_storage"}


async def library_management_fee(db: AsyncSession, prop, valuation: Valuation) -> None:
    """A property's first valuation starts with the assumptions library's management fee as a % of EGI line."""
    from decimal import Decimal

    from src.api.expenses import LIBRARY_FEE_COMMENT
    from src.models.expense import PropertyExpense
    from src.services.portfolio_service import PortfolioService

    if prop.property_type not in _EXPENSE_LINE_TYPES:
        return
    resolved = await PortfolioService(db).resolve_for_property(prop, None)
    fee = resolved.values.get("management_fee_pct")
    if fee is None:
        return
    db.add(PropertyExpense(
        property_id=prop.id, valuation_id=valuation.id, category="management_fee", description="Management fee",
        base_year_amount=Decimal(0), is_pct_of_egi=True, pct_of_egi=fee, is_recoverable=False,
        growth_rate_pct=Decimal(0),
        comment=f"{LIBRARY_FEE_COMMENT} ({resolved.sources['management_fee_pct'].removeprefix('profile:')})",
    ))
