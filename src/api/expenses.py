from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.validation import owning_valuation, update_changes
from src.db.session import get_session
from src.models.expense import PropertyExpense
from src.schemas.expense import PropertyExpenseCreate, PropertyExpenseRead, PropertyExpenseUpdate

router = APIRouter(prefix="/api/v1/valuations", tags=["expenses"])

# Marks the management fee line a new property gets from the assumptions library (api/properties.py)
LIBRARY_FEE_COMMENT = "From the assumptions library"


@router.post(
    "/{valuation_id}/expenses",
    response_model=PropertyExpenseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_expense(
    valuation_id: str,
    body: PropertyExpenseCreate,
    db: AsyncSession = Depends(get_session),
) -> PropertyExpenseRead:
    valuation = await owning_valuation(db, valuation_id)
    expense = PropertyExpense(property_id=valuation.property_id, valuation_id=valuation_id, **body.model_dump())
    if expense.category == "management_fee":
        # The user's own fee replaces the library default rather than charging twice
        defaults = await db.execute(select(PropertyExpense).where(
            PropertyExpense.valuation_id == valuation_id, PropertyExpense.category == "management_fee",
            PropertyExpense.comment.startswith(LIBRARY_FEE_COMMENT),
        ))
        for old in defaults.scalars():
            await db.delete(old)
    db.add(expense)
    await db.commit()
    await db.refresh(expense)
    return expense


@router.get("/{valuation_id}/expenses", response_model=list[PropertyExpenseRead])
async def list_expenses(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[PropertyExpenseRead]:
    result = await db.execute(
        select(PropertyExpense).where(PropertyExpense.valuation_id == valuation_id)
    )
    return list(result.scalars().all())


@router.get("/{valuation_id}/expenses/{expense_id}", response_model=PropertyExpenseRead)
async def get_expense(
    valuation_id: str,
    expense_id: str,
    db: AsyncSession = Depends(get_session),
) -> PropertyExpenseRead:
    result = await db.execute(
        select(PropertyExpense).where(
            PropertyExpense.id == expense_id,
            PropertyExpense.valuation_id == valuation_id,
        )
    )
    expense = result.scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


@router.put("/{valuation_id}/expenses/{expense_id}", response_model=PropertyExpenseRead)
async def update_expense(
    valuation_id: str,
    expense_id: str,
    body: PropertyExpenseUpdate,
    db: AsyncSession = Depends(get_session),
) -> PropertyExpenseRead:
    result = await db.execute(
        select(PropertyExpense).where(
            PropertyExpense.id == expense_id,
            PropertyExpense.valuation_id == valuation_id,
        )
    )
    expense = result.scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    for field, value in update_changes(PropertyExpense, body).items():
        setattr(expense, field, value)
    if expense.is_memo and expense.is_pct_of_egi:
        raise HTTPException(status_code=422, detail="A % of EGI line cannot be a memo line")
    await db.commit()
    await db.refresh(expense)
    return expense


@router.delete("/{valuation_id}/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    valuation_id: str,
    expense_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(PropertyExpense).where(
            PropertyExpense.id == expense_id,
            PropertyExpense.valuation_id == valuation_id,
        )
    )
    expense = result.scalar_one_or_none()
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    await db.delete(expense)
    await db.commit()
