from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.validation import owning_valuation
from src.db.session import get_session
from src.models.property import Suite
from src.models.recovery_pool import RecoveryPool
from src.schemas.recovery_pool import RecoveryPoolCreate, RecoveryPoolRead, RecoveryPoolUpdate

router = APIRouter(prefix="/api/v1/valuations", tags=["recovery-pools"])


async def _validate(db: AsyncSession, valuation_id: str, body: RecoveryPoolCreate, pool_id: str | None) -> None:
    """Each expense category sits in one pool; excluded suites belong to the valuation."""
    await owning_valuation(db, valuation_id)
    others = (await db.execute(
        select(RecoveryPool).where(RecoveryPool.valuation_id == valuation_id, RecoveryPool.id != (pool_id or ""))
    )).scalars()
    for other in others:
        taken = set(other.expense_categories or []) & set(body.expense_categories)
        if taken:
            raise HTTPException(
                status_code=422,
                detail=f"{', '.join(sorted(taken))} already in recovery pool '{other.name}'",
            )
    if body.excluded_suite_ids:
        found = set((await db.execute(
            select(Suite.id).where(Suite.valuation_id == valuation_id, Suite.id.in_(body.excluded_suite_ids))
        )).scalars())
        if found != set(body.excluded_suite_ids):
            raise HTTPException(status_code=422, detail="excluded_suite_ids must be suites of this valuation")


async def _get(db: AsyncSession, valuation_id: str, pool_id: str) -> RecoveryPool:
    pool = await db.get(RecoveryPool, pool_id)
    if pool is None or pool.valuation_id != valuation_id:
        raise HTTPException(status_code=404, detail="Recovery pool not found")
    return pool


@router.get("/{valuation_id}/recovery-pools", response_model=list[RecoveryPoolRead])
async def list_recovery_pools(valuation_id: str, db: AsyncSession = Depends(get_session)) -> list[RecoveryPool]:
    return list((await db.execute(
        select(RecoveryPool).where(RecoveryPool.valuation_id == valuation_id).order_by(RecoveryPool.created_at)
    )).scalars())


@router.post("/{valuation_id}/recovery-pools", response_model=RecoveryPoolRead, status_code=status.HTTP_201_CREATED)
async def create_recovery_pool(
    valuation_id: str, body: RecoveryPoolCreate, db: AsyncSession = Depends(get_session),
) -> RecoveryPool:
    await _validate(db, valuation_id, body, None)
    valuation = await owning_valuation(db, valuation_id)
    pool = RecoveryPool(property_id=valuation.property_id, valuation_id=valuation_id, **body.model_dump())
    db.add(pool)
    await db.commit()
    await db.refresh(pool)
    return pool


@router.get("/{valuation_id}/recovery-pools/{pool_id}", response_model=RecoveryPoolRead)
async def get_recovery_pool(valuation_id: str, pool_id: str, db: AsyncSession = Depends(get_session)) -> RecoveryPool:
    return await _get(db, valuation_id, pool_id)


@router.put("/{valuation_id}/recovery-pools/{pool_id}", response_model=RecoveryPoolRead)
async def update_recovery_pool(
    valuation_id: str, pool_id: str, body: RecoveryPoolUpdate, db: AsyncSession = Depends(get_session),
) -> RecoveryPool:
    pool = await _get(db, valuation_id, pool_id)
    await _validate(db, valuation_id, body, pool_id)
    for field, value in body.model_dump().items():
        setattr(pool, field, value)
    await db.commit()
    await db.refresh(pool)
    return pool


@router.delete("/{valuation_id}/recovery-pools/{pool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recovery_pool(valuation_id: str, pool_id: str, db: AsyncSession = Depends(get_session)) -> None:
    await db.delete(await _get(db, valuation_id, pool_id))
    await db.commit()
