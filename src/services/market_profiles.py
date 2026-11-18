"""Market leasing profiles belong to a valuation: each valuation holds its own market view."""
from __future__ import annotations

from sqlalchemy import literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.valuation import Valuation

# created_at has 1-second resolution; SQLite's rowid breaks ties in insert order
_NEWEST = (literal_column("valuations.rowid").desc(),)


async def latest_valuation_id(db: AsyncSession, property_id: str) -> str | None:
    """The property's newest valuation: a new valuation copies its market leasing."""
    return (await db.execute(
        select(Valuation.id).where(Valuation.property_id == property_id)
        .order_by(Valuation.created_at.desc(), *_NEWEST).limit(1)
    )).scalar()

