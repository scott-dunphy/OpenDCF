from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.session import get_session
from src.models.property import Property
from src.models.recovery_structure import RecoveryStructure, RecoveryStructureItem
from src.schemas.recovery_structure import (
    RecoveryStructureCreate,
    RecoveryStructureItemCreate,
    RecoveryStructureItemRead,
    RecoveryStructureRead,
    RecoveryStructureUpdate,
)

router = APIRouter(prefix="/api/v1/properties", tags=["recovery-structures"])


def _rs_options():
    return [selectinload(RecoveryStructure.items)]


@router.post(
    "/{property_id}/recovery-structures",
    response_model=RecoveryStructureRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_recovery_structure(
    property_id: str,
    body: RecoveryStructureCreate,
    db: AsyncSession = Depends(get_session),
) -> RecoveryStructureRead:
    result = await db.execute(select(Property).where(Property.id == property_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Property not found")
    rs = RecoveryStructure(
        property_id=property_id,
        name=body.name,
        description=body.description,
        comment=body.comment,
        default_recovery_type=body.default_recovery_type.value,
    )
    for item_data in body.items:
        rs.items.append(RecoveryStructureItem(
            expense_category=item_data.expense_category,
            recovery_type=item_data.recovery_type.value,
            base_year_stop_amount=item_data.base_year_stop_amount,
            cap_per_sf_annual=item_data.cap_per_sf_annual,
            floor_per_sf_annual=item_data.floor_per_sf_annual,
            admin_fee_pct=item_data.admin_fee_pct,
            comment=item_data.comment,
        ))
    db.add(rs)
    await db.commit()
    # Re-fetch with items loaded
    result = await db.execute(
        select(RecoveryStructure).where(RecoveryStructure.id == rs.id).options(*_rs_options())
    )
    return result.scalar_one()


@router.get("/{property_id}/recovery-structures", response_model=list[RecoveryStructureRead])
async def list_recovery_structures(
    property_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[RecoveryStructureRead]:
    result = await db.execute(
        select(RecoveryStructure)
        .where(RecoveryStructure.property_id == property_id)
        .options(*_rs_options())
    )
    return list(result.scalars().all())


@router.get("/{property_id}/recovery-structures/{rs_id}", response_model=RecoveryStructureRead)
async def get_recovery_structure(
    property_id: str,
    rs_id: str,
    db: AsyncSession = Depends(get_session),
) -> RecoveryStructureRead:
    result = await db.execute(
        select(RecoveryStructure)
        .where(RecoveryStructure.id == rs_id, RecoveryStructure.property_id == property_id)
        .options(*_rs_options())
    )
    rs = result.scalar_one_or_none()
    if rs is None:
        raise HTTPException(status_code=404, detail="Recovery structure not found")
    return rs


@router.put("/{property_id}/recovery-structures/{rs_id}", response_model=RecoveryStructureRead)
async def update_recovery_structure(
    property_id: str,
    rs_id: str,
    body: RecoveryStructureUpdate,
    db: AsyncSession = Depends(get_session),
) -> RecoveryStructureRead:
    result = await db.execute(
        select(RecoveryStructure)
        .where(RecoveryStructure.id == rs_id, RecoveryStructure.property_id == property_id)
        .options(*_rs_options())
    )
    rs = result.scalar_one_or_none()
    if rs is None:
        raise HTTPException(status_code=404, detail="Recovery structure not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(rs, field, value.value if hasattr(value, 'value') else value)
    await db.commit()
    result = await db.execute(
        select(RecoveryStructure).where(RecoveryStructure.id == rs_id).options(*_rs_options())
    )
    return result.scalar_one()


@router.delete("/{property_id}/recovery-structures/{rs_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recovery_structure(
    property_id: str,
    rs_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(RecoveryStructure)
        .where(RecoveryStructure.id == rs_id, RecoveryStructure.property_id == property_id)
    )
    rs = result.scalar_one_or_none()
    if rs is None:
        raise HTTPException(status_code=404, detail="Recovery structure not found")
    await db.delete(rs)
    await db.commit()


# --- Items sub-resource ---

@router.post(
    "/{property_id}/recovery-structures/{rs_id}/items",
    response_model=RecoveryStructureItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_item(
    property_id: str,
    rs_id: str,
    body: RecoveryStructureItemCreate,
    db: AsyncSession = Depends(get_session),
) -> RecoveryStructureItemRead:
    result = await db.execute(
        select(RecoveryStructure)
        .where(RecoveryStructure.id == rs_id, RecoveryStructure.property_id == property_id)
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
        comment=body.comment,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete(
    "/{property_id}/recovery-structures/{rs_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_item(
    property_id: str,
    rs_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(RecoveryStructureItem)
        .where(
            RecoveryStructureItem.id == item_id,
            RecoveryStructureItem.recovery_structure_id == rs_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.delete(item)
    await db.commit()
