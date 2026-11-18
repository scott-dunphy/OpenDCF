from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.validation import owning_valuation, update_changes
from src.db.session import get_session
from src.models.other_income import PropertyOtherIncome
from src.schemas.other_income import (
    PropertyOtherIncomeCreate,
    PropertyOtherIncomeRead,
    PropertyOtherIncomeUpdate,
)

router = APIRouter(prefix="/api/v1/valuations", tags=["other-income"])


@router.post(
    "/{valuation_id}/other-income",
    response_model=PropertyOtherIncomeRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_other_income(
    valuation_id: str,
    body: PropertyOtherIncomeCreate,
    db: AsyncSession = Depends(get_session),
) -> PropertyOtherIncomeRead:
    valuation = await owning_valuation(db, valuation_id)
    item = PropertyOtherIncome(property_id=valuation.property_id, valuation_id=valuation_id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/{valuation_id}/other-income", response_model=list[PropertyOtherIncomeRead])
async def list_other_income(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[PropertyOtherIncomeRead]:
    result = await db.execute(
        select(PropertyOtherIncome).where(PropertyOtherIncome.valuation_id == valuation_id)
    )
    return list(result.scalars().all())


@router.put("/{valuation_id}/other-income/{item_id}", response_model=PropertyOtherIncomeRead)
async def update_other_income(
    valuation_id: str,
    item_id: str,
    body: PropertyOtherIncomeUpdate,
    db: AsyncSession = Depends(get_session),
) -> PropertyOtherIncomeRead:
    result = await db.execute(
        select(PropertyOtherIncome).where(
            PropertyOtherIncome.id == item_id,
            PropertyOtherIncome.valuation_id == valuation_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Other income item not found")
    for field, value in update_changes(PropertyOtherIncome, body).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/{valuation_id}/other-income/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_other_income(
    valuation_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(PropertyOtherIncome).where(
            PropertyOtherIncome.id == item_id,
            PropertyOtherIncome.valuation_id == valuation_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Other income item not found")
    await db.delete(item)
    await db.commit()
