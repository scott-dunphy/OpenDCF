"""
Valuation readiness: what a valuation's model still needs before its result means anything.

Each check is "done", "warning" (the run works but the result is probably incomplete)
or "missing" (the run is refused: it would only produce a number from nothing).
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.expense import PropertyExpense
from src.models.lease import Lease
from src.models.market import MarketLeasingProfile
from src.models.property import Property, Suite
from src.models.valuation import Valuation

OPERATING_MODEL_TYPES = {"marina": "marina", "seniors_housing": "seniors_housing"}


class ReadinessItem(BaseModel):
    key: str
    label: str
    status: str  # done | warning | missing
    detail: str
    section: str  # property workspace section that fixes it
    valuation_id: str | None = None  # for items fixed on a valuation (market leasing)


class Readiness(BaseModel):
    ready: bool  # no "missing" items
    items: list[ReadinessItem]

    def blocking_message(self) -> str:
        return "; ".join(i.detail for i in self.items if i.status == "missing")


async def assess(db: AsyncSession, prop: Property, valuation: Valuation | None) -> Readiness:
    """What the valuation's own model still needs before it can run."""
    if valuation is None:
        return Readiness(ready=False, items=[ReadinessItem(
            key="valuation", label="Valuation", status="missing", detail="Add a valuation", section="valuations")])
    if prop.property_type in OPERATING_MODEL_TYPES:
        return await _assess_operating_business(prop, valuation)
    if prop.property_type == "self_storage" and valuation.self_storage_assumptions_json:
        return await _assess_storage(db, prop, valuation)
    return await _assess_leased(db, prop, valuation)


async def _assess_operating_business(prop: Property, valuation: Valuation) -> Readiness:
    column = f"{OPERATING_MODEL_TYPES[prop.property_type]}_assumptions_json"
    has_model = bool(getattr(valuation, column))
    noun = "slip inventory and marina operations" if prop.property_type == "marina" else "unit mix and operations"
    if has_model:
        item = ReadinessItem(key="operating_model", label="Operating model", status="done",
                             detail=f"{noun.capitalize()} entered", section="operations")
    elif prop.property_type == "marina":
        item = ReadinessItem(key="operating_model", label="Operating model", status="warning",
                             detail=f"No {noun} entered; runs use generic marina defaults sized to the slip count",
                             section="operations")
    else:
        item = ReadinessItem(key="operating_model", label="Operating model", status="missing",
                             detail=f"Enter the {noun}", section="operations")
    return Readiness(ready=item.status != "missing", items=[item])


async def _assess_storage(db: AsyncSession, prop: Property, valuation: Valuation) -> Readiness:
    from src.schemas.self_storage import parse_storage_model

    model = parse_storage_model(valuation.self_storage_assumptions_json)
    units = sum(u.count for u in model.unit_types)
    items = [ReadinessItem(key="operating_model", label="Unit mix", status="done",
                           detail=f"{len(model.unit_types)} unit types, {units:,} units", section="operations")]
    rentable, total = model.rentable_sf, prop.total_area or Decimal(0)
    if total and abs(rentable - total) > total * Decimal("0.01"):
        items[0] = ReadinessItem(
            key="operating_model", label="Unit mix", status="warning",
            detail=f"Unit types add up to {rentable:,.0f} SF but the property is {total:,.0f} SF",
            section="operations")
    expense_count = (await db.execute(
        select(func.count()).select_from(PropertyExpense).where(PropertyExpense.valuation_id == valuation.id)
    )).scalar_one()
    items.append(ReadinessItem(
        key="expenses", label="Operating expenses", status="done" if expense_count else "warning",
        detail=f"{expense_count} expense lines" if expense_count else "No operating expenses entered",
        section="expenses"))
    return Readiness(ready=True, items=items)


async def _assess_leased(db: AsyncSession, prop: Property, valuation: Valuation) -> Readiness:
    is_unit = prop.area_unit == "unit"
    suites = list((await db.execute(select(Suite).where(Suite.valuation_id == valuation.id))).scalars())
    leases = list((await db.execute(
        select(Lease).join(Suite, Lease.suite_id == Suite.id).where(Suite.valuation_id == valuation.id)
    )).scalars())
    profiles = list((await db.execute(
        select(MarketLeasingProfile).where(MarketLeasingProfile.valuation_id == valuation.id)
    )).scalars())
    expense_count = (await db.execute(
        select(func.count()).select_from(PropertyExpense).where(PropertyExpense.valuation_id == valuation.id)
    )).scalar_one()

    items: list[ReadinessItem] = []
    space = "unit types" if is_unit else "suites"

    # Space
    if not suites:
        items.append(ReadinessItem(key="space", label="Rent roll", status="missing",
                                   detail=f"Add the property's {space}", section="rent-roll"))
    else:
        suite_total = sum((s.area for s in suites), Decimal(0))
        total = prop.total_area or Decimal(0)
        unit = "units" if is_unit else "SF"
        if total and abs(suite_total - total) > total * Decimal("0.01"):
            items.append(ReadinessItem(
                key="space", label="Rent roll", status="warning",
                detail=f"{space.capitalize()} add up to {suite_total:,.0f} {unit} but the property is {total:,.0f} {unit}",
                section="rent-roll"))
        else:
            items.append(ReadinessItem(key="space", label="Rent roll", status="done",
                                       detail=f"{len(suites)} {space}", section="rent-roll"))

    # Leases
    if suites:
        in_place = [l for l in leases if l.lease_type != "market"]
        if in_place:
            items.append(ReadinessItem(key="leases", label="Leases", status="done",
                                       detail=f"{len(in_place)} in-place lease{'s' if len(in_place) != 1 else ''}",
                                       section="rent-roll"))
        else:
            items.append(ReadinessItem(
                key="leases", label="In-place rents" if is_unit else "Leases", status="warning",
                detail=("No in-place rents; every unit is modeled as vacant" if is_unit
                        else "No in-place leases; the property is modeled as fully vacant"),
                section="rent-roll"))

    # Market leasing assumptions: every suite needs one to re-lease after expiry or lease up
    if suites:
        by_type = {p.space_type for p in profiles}
        uncovered = [s for s in suites if (s.market_space_type or s.space_type) not in by_type]
        if uncovered:
            types = sorted({s.market_space_type or s.space_type for s in uncovered})
            items.append(ReadinessItem(
                key="market", label="Market leasing", status="warning",
                detail=f"No market assumptions for {', '.join(types)} in '{valuation.name}'; that space is never re-leased",
                section="market", valuation_id=valuation.id))
        else:
            items.append(ReadinessItem(key="market", label="Market leasing", status="done",
                                       detail=f"{len(profiles)} market profile{'s' if len(profiles) != 1 else ''} in '{valuation.name}'",
                                       section="market", valuation_id=valuation.id))

    # Operating expenses
    if expense_count:
        items.append(ReadinessItem(key="expenses", label="Operating expenses", status="done",
                                   detail=f"{expense_count} expense line{'s' if expense_count != 1 else ''}",
                                   section="operating"))
    else:
        items.append(ReadinessItem(key="expenses", label="Operating expenses", status="warning",
                                   detail="No operating expenses; NOI equals revenue", section="operating"))

    return Readiness(ready=all(i.status != "missing" for i in items), items=items)
