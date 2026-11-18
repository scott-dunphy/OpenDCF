from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.validation import owning_valuation, update_changes
from src.db.session import get_session
from src.models.property import Suite
from src.schemas.property import SuiteCreate, SuiteRead, SuiteUpdate

router = APIRouter(prefix="/api/v1/valuations", tags=["suites"])


@router.post("/{valuation_id}/suites", response_model=SuiteRead, status_code=status.HTTP_201_CREATED)
async def create_suite(
    valuation_id: str,
    body: SuiteCreate,
    db: AsyncSession = Depends(get_session),
) -> SuiteRead:
    valuation = await owning_valuation(db, valuation_id)
    suite = Suite(property_id=valuation.property_id, valuation_id=valuation_id, **body.model_dump())
    db.add(suite)
    await db.commit()
    await db.refresh(suite)
    return suite


@router.get("/{valuation_id}/suites", response_model=list[SuiteRead])
async def list_suites(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[SuiteRead]:
    result = await db.execute(select(Suite).where(Suite.valuation_id == valuation_id))
    return list(result.scalars().all())


@router.get("/{valuation_id}/suites/{suite_id}", response_model=SuiteRead)
async def get_suite(
    valuation_id: str,
    suite_id: str,
    db: AsyncSession = Depends(get_session),
) -> SuiteRead:
    result = await db.execute(
        select(Suite).where(Suite.id == suite_id, Suite.valuation_id == valuation_id)
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


@router.put("/{valuation_id}/suites/{suite_id}", response_model=SuiteRead)
async def update_suite(
    valuation_id: str,
    suite_id: str,
    body: SuiteUpdate,
    db: AsyncSession = Depends(get_session),
) -> SuiteRead:
    result = await db.execute(
        select(Suite).where(Suite.id == suite_id, Suite.valuation_id == valuation_id)
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    for field, value in update_changes(Suite, body).items():
        setattr(suite, field, value)
    await db.commit()
    await db.refresh(suite)
    return suite


@router.delete("/{valuation_id}/suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_suite(
    valuation_id: str,
    suite_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(Suite).where(Suite.id == suite_id, Suite.valuation_id == valuation_id)
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    await db.delete(suite)
    await db.commit()
