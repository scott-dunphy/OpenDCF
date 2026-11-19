from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.validation import owning_valuation
from src.db.session import get_session
from src.models.recovery_structure import RecoveryStructure, RecoveryStructureItem
from src.schemas.recovery_structure import (
    RecoveryStructureCreate,
    RecoveryStructureItemCreate,
    RecoveryStructureItemRead,
    RecoveryStructureItemUpdate,
    RecoveryStructureRead,
    RecoveryStructureUpdate,
)

router = APIRouter(prefix="/api/v1/valuations", tags=["recovery-structures"])


def _rs_options():
    return [selectinload(RecoveryStructure.items)]


@router.post(
    "/{valuation_id}/recovery-structures",
    response_model=RecoveryStructureRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_recovery_structure(
    valuation_id: str,
    body: RecoveryStructureCreate,
    db: AsyncSession = Depends(get_session),
) -> RecoveryStructureRead:
    valuation = await owning_valuation(db, valuation_id)
    rs = RecoveryStructure(
        property_id=valuation.property_id,
        valuation_id=valuation_id,
        name=body.name,
        description=body.description,
        comment=body.comment,
        default_recovery_type=body.default_recovery_type.value,
        expense_stop_per_sf=body.expense_stop_per_sf,
    )
    for item_data in body.items:
        rs.items.append(RecoveryStructureItem(
            expense_category=item_data.expense_category,
            recovery_type=item_data.recovery_type.value,
            base_year_stop_amount=item_data.base_year_stop_amount,
            cap_per_sf_annual=item_data.cap_per_sf_annual,
            floor_per_sf_annual=item_data.floor_per_sf_annual,
            admin_fee_pct=item_data.admin_fee_pct,
            cap_group=item_data.cap_group,
            cap_growth_pct=item_data.cap_growth_pct,
            expense_stop_per_sf=item_data.expense_stop_per_sf,
            recoverable_pct=item_data.recoverable_pct,
            comment=item_data.comment,
        ))
    db.add(rs)
    await db.commit()
    # Re-fetch with items loaded
    result = await db.execute(
        select(RecoveryStructure).where(RecoveryStructure.id == rs.id).options(*_rs_options())
    )
    return result.scalar_one()


@router.get("/{valuation_id}/recovery-structures", response_model=list[RecoveryStructureRead])
async def list_recovery_structures(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[RecoveryStructureRead]:
    result = await db.execute(
        select(RecoveryStructure)
        .where(RecoveryStructure.valuation_id == valuation_id)
        .options(*_rs_options())
    )
    return list(result.scalars().all())


@router.get("/{valuation_id}/recovery-structures/{rs_id}", response_model=RecoveryStructureRead)
async def get_recovery_structure(
    valuation_id: str,
    rs_id: str,
    db: AsyncSession = Depends(get_session),
) -> RecoveryStructureRead:
    result = await db.execute(
        select(RecoveryStructure)
        .where(RecoveryStructure.id == rs_id, RecoveryStructure.valuation_id == valuation_id)
        .options(*_rs_options())
    )
    rs = result.scalar_one_or_none()
    if rs is None:
        raise HTTPException(status_code=404, detail="Recovery structure not found")
    return rs


@router.put("/{valuation_id}/recovery-structures/{rs_id}", response_model=RecoveryStructureRead)
async def update_recovery_structure(
    valuation_id: str,
    rs_id: str,
    body: RecoveryStructureUpdate,
    db: AsyncSession = Depends(get_session),
) -> RecoveryStructureRead:
    result = await db.execute(
        select(RecoveryStructure)
        .where(RecoveryStructure.id == rs_id, RecoveryStructure.valuation_id == valuation_id)
        .options(*_rs_options())
    )
    rs = result.scalar_one_or_none()
    if rs is None:
        raise HTTPException(status_code=404, detail="Recovery structure not found")
    # Null clears an optional field; name and default recovery type cannot be cleared
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None and field in ("name", "default_recovery_type"):
            continue
        setattr(rs, field, value.value if hasattr(value, 'value') else value)
    await db.commit()
    result = await db.execute(
        select(RecoveryStructure).where(RecoveryStructure.id == rs_id).options(*_rs_options())
    )
    return result.scalar_one()


@router.delete("/{valuation_id}/recovery-structures/{rs_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recovery_structure(
    valuation_id: str,
    rs_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(RecoveryStructure)
        .where(RecoveryStructure.id == rs_id, RecoveryStructure.valuation_id == valuation_id)
    )
    rs = result.scalar_one_or_none()
    if rs is None:
        raise HTTPException(status_code=404, detail="Recovery structure not found")
    await db.delete(rs)
    await db.commit()


# --- Items sub-resource ---

@router.post(
    "/{valuation_id}/recovery-structures/{rs_id}/items",
    response_model=RecoveryStructureItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_item(
    valuation_id: str,
    rs_id: str,
    body: RecoveryStructureItemCreate,
    db: AsyncSession = Depends(get_session),
) -> RecoveryStructureItemRead:
    result = await db.execute(
        select(RecoveryStructure)
        .where(RecoveryStructure.id == rs_id, RecoveryStructure.valuation_id == valuation_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Recovery structure not found")
    item = RecoveryStructureItem(
        recovery_structure_id=rs_id,
        expense_category=body.expense_category,
        recovery_type=body.recovery_type.value,
        base_year_stop_amount=body.base_year_stop_amount,
        cap_per_sf_annual=body.cap_per_sf_annual,
        floor_per_sf_annual=body.floor_per_sf_annual,
        admin_fee_pct=body.admin_fee_pct,
        cap_group=body.cap_group,
        cap_growth_pct=body.cap_growth_pct,
        expense_stop_per_sf=body.expense_stop_per_sf,
        recoverable_pct=body.recoverable_pct,
        comment=body.comment,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _owned_item(db: AsyncSession, valuation_id: str, rs_id: str, item_id: str) -> RecoveryStructureItem:
    item = (await db.execute(
        select(RecoveryStructureItem)
        .join(RecoveryStructure, RecoveryStructure.id == RecoveryStructureItem.recovery_structure_id)
        .where(
            RecoveryStructureItem.id == item_id,
            RecoveryStructureItem.recovery_structure_id == rs_id,
            RecoveryStructure.valuation_id == valuation_id,
        )
    )).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.put(
    "/{valuation_id}/recovery-structures/{rs_id}/items/{item_id}",
    response_model=RecoveryStructureItemRead,
)
async def update_item(
    valuation_id: str,
    rs_id: str,
    item_id: str,
    body: RecoveryStructureItemUpdate,
    db: AsyncSession = Depends(get_session),
) -> RecoveryStructureItemRead:
    item = await _owned_item(db, valuation_id, rs_id, item_id)
    # Null clears an optional field; category and recovery type cannot be cleared
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None and field in ("expense_category", "recovery_type"):
            continue
        setattr(item, field, value.value if hasattr(value, "value") else value)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete(
    "/{valuation_id}/recovery-structures/{rs_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_item(
    valuation_id: str,
    rs_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    item = await _owned_item(db, valuation_id, rs_id, item_id)
    await db.delete(item)
    await db.commit()
