from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.models.expense import PropertyExpense
from src.models.property import Property
from src.schemas.expense import PropertyExpenseCreate, PropertyExpenseRead, PropertyExpenseUpdate

router = APIRouter(prefix="/api/v1/properties", tags=["expenses"])


@router.post(
    "/{property_id}/expenses",
    response_model=PropertyExpenseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_expense(
    property_id: str,
    body: PropertyExpenseCreate,
    db: AsyncSession = Depends(get_session),
) -> PropertyExpenseRead:
    result = await db.execute(select(Property).where(Property.id == property_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Property not found")
    expense = PropertyExpense(property_id=property_id, **body.model_dump())
    db.add(expense)
    await db.commit()
    await db.refresh(expense)
    return expense


@router.get("/{property_id}/expenses", response_model=list[PropertyExpenseRead])
async def list_expenses(
    property_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[PropertyExpenseRead]:
    result = await db.execute(
        select(PropertyExpense).where(PropertyExpense.property_id == property_id)
    )
    return list(result.scalars().all())


@router.get("/{property_id}/expenses/{expense_id}", response_model=PropertyExpenseRead)
async def get_expense(
    property_id: str,
    expense_id: str,
    db: AsyncSession = Depends(get_session),
) -> PropertyExpenseRead:
    result = await db.execute(
        select(PropertyExpense).where(
            PropertyExpense.id == expense_id,
            PropertyExpense.property_id == property_id,
        )
    )
    expense = result.scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


@router.put("/{property_id}/expenses/{expense_id}", response_model=PropertyExpenseRead)
async def update_expense(
    property_id: str,
    expense_id: str,
    body: PropertyExpenseUpdate,
    db: AsyncSession = Depends(get_session),
) -> PropertyExpenseRead:
    result = await db.execute(
        select(PropertyExpense).where(
            PropertyExpense.id == expense_id,
            PropertyExpense.property_id == property_id,
        )
    )
    expense = result.scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(expense, field, value)
    await db.commit()
    await db.refresh(expense)
    return expense


@router.delete("/{property_id}/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    property_id: str,
    expense_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(PropertyExpense).where(
            PropertyExpense.id == expense_id,
            PropertyExpense.property_id == property_id,
        )
    )
    expense = result.scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    await db.delete(expense)
    await db.commit()
