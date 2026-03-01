from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.session import get_session
from src.models.property import Property, Suite
from src.schemas.property import PropertyCreate, PropertyList, PropertyRead, PropertyUpdate

router = APIRouter(prefix="/api/v1/properties", tags=["properties"])


@router.post("", response_model=PropertyRead, status_code=status.HTTP_201_CREATED)
async def create_property(
    body: PropertyCreate,
    db: AsyncSession = Depends(get_session),
) -> PropertyRead:
    prop = Property(**body.model_dump())
    db.add(prop)
    await db.commit()
    await db.refresh(prop)
    # Load suites relationship
    result = await db.execute(
        select(Property).where(Property.id == prop.id).options(selectinload(Property.suites))
    )
    return result.scalar_one()


@router.get("", response_model=list[PropertyList])
async def list_properties(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
) -> list[PropertyList]:
    result = await db.execute(select(Property).offset(skip).limit(limit))
    return list(result.scalars().all())


@router.get("/{property_id}", response_model=PropertyRead)
async def get_property(
    property_id: str,
    db: AsyncSession = Depends(get_session),
) -> PropertyRead:
    result = await db.execute(
        select(Property)
        .where(Property.id == property_id)
        .options(selectinload(Property.suites))
    )
    prop = result.scalar_one_or_none()
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
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(prop, field, value)
    await db.commit()
    result = await db.execute(
        select(Property).where(Property.id == property_id).options(selectinload(Property.suites))
    )
    return result.scalar_one()


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
