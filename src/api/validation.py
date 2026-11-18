from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import Base


def update_changes(model: type[Base], body) -> dict:
    """The fields an update sets: those sent, where an explicit null clears an optional column and
    is ignored for a required one (it keeps its value); omitted fields are left alone."""
    columns = model.__table__.columns
    return {
        f: v for f, v in body.model_dump(exclude_unset=True).items()
        if v is not None or f not in columns or columns[f].nullable
    }


def reject_null_columns(model: type[Base], changes: dict) -> None:
    """An update may not set a NOT NULL column to null (422 instead of a database error)."""
    columns = model.__table__.columns
    bad = sorted(f for f, v in changes.items() if v is None and f in columns and not columns[f].nullable)
    if bad:
        raise HTTPException(status_code=422, detail=f"{', '.join(bad)} cannot be null")


async def check_same_valuation(
    db: AsyncSession, model: type[Base], record_id: str | None, valuation_id: str, label: str
) -> None:
    """A reference to another input row (e.g. a recovery structure) must be the same valuation's."""
    if record_id is None:
        return
    record = await db.get(model, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    if record.valuation_id != valuation_id:
        raise HTTPException(status_code=400, detail=f"{label} belongs to a different valuation")


async def owning_valuation(db, valuation_id: str):
    """The valuation whose inputs a route edits (404 when missing)."""
    from fastapi import HTTPException

    from src.models.valuation import Valuation

    valuation = await db.get(Valuation, valuation_id)
    if valuation is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return valuation
