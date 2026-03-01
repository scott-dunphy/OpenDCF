from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.models.property import Property, Suite
from src.schemas.property import SuiteCreate, SuiteRead, SuiteUpdate

router = APIRouter(prefix="/api/v1/properties", tags=["suites"])


@router.post("/{property_id}/suites", response_model=SuiteRead, status_code=status.HTTP_201_CREATED)
async def create_suite(
    property_id: str,
    body: SuiteCreate,
    db: AsyncSession = Depends(get_session),
) -> SuiteRead:
    result = await db.execute(select(Property).where(Property.id == property_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Property not found")
    suite = Suite(property_id=property_id, **body.model_dump())
    db.add(suite)
    await db.commit()
    await db.refresh(suite)
    return suite


@router.get("/{property_id}/suites", response_model=list[SuiteRead])
async def list_suites(
    property_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[SuiteRead]:
    result = await db.execute(select(Suite).where(Suite.property_id == property_id))
    return list(result.scalars().all())


@router.get("/{property_id}/suites/{suite_id}", response_model=SuiteRead)
async def get_suite(
    property_id: str,
    suite_id: str,
    db: AsyncSession = Depends(get_session),
) -> SuiteRead:
    result = await db.execute(
        select(Suite).where(Suite.id == suite_id, Suite.property_id == property_id)
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


@router.put("/{property_id}/suites/{suite_id}", response_model=SuiteRead)
async def update_suite(
    property_id: str,
    suite_id: str,
    body: SuiteUpdate,
    db: AsyncSession = Depends(get_session),
) -> SuiteRead:
    result = await db.execute(
        select(Suite).where(Suite.id == suite_id, Suite.property_id == property_id)
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(suite, field, value)
    await db.commit()
    await db.refresh(suite)
    return suite


@router.delete("/{property_id}/suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_suite(
    property_id: str,
    suite_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(Suite).where(Suite.id == suite_id, Suite.property_id == property_id)
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    await db.delete(suite)
    await db.commit()
