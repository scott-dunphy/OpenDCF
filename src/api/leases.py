from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.session import get_session
import src.models  # ensure all models registered before selectinload
from src.models.lease import FreeRentPeriod, Lease, LeaseExpenseRecovery, RentStep
from src.models.property import Suite
from src.schemas.lease import (
    FreeRentPeriodCreate,
    FreeRentPeriodRead,
    LeaseCreate,
    LeaseExpenseRecoveryCreate,
    LeaseExpenseRecoveryRead,
    LeaseRead,
    LeaseUpdate,
    RentStepCreate,
    RentStepRead,
)

router = APIRouter(prefix="/api/v1", tags=["leases"])


def _lease_options():
    return [
        selectinload(Lease.rent_steps),
        selectinload(Lease.free_rent_periods),
        selectinload(Lease.expense_recovery_overrides),
        selectinload(Lease.tenant),
        selectinload(Lease.recovery_structure),
    ]


async def _get_lease_or_404(lease_id: str, db: AsyncSession) -> Lease:
    result = await db.execute(
        select(Lease).where(Lease.id == lease_id).options(*_lease_options())
    )
    lease = result.scalar_one_or_none()
    if lease is None:
        raise HTTPException(status_code=404, detail="Lease not found")
    return lease


async def _ensure_no_overlap(
    db: AsyncSession,
    suite_id: str,
    lease_start_date: date,
    lease_end_date: date,
    exclude_lease_id: str | None = None,
) -> None:
    stmt = select(Lease).where(
        Lease.suite_id == suite_id,
        Lease.lease_start_date <= lease_end_date,
        Lease.lease_end_date >= lease_start_date,
    )
    if exclude_lease_id is not None:
        stmt = stmt.where(Lease.id != exclude_lease_id)
    result = await db.execute(stmt.limit(1))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lease date range overlaps an existing lease for this suite",
        )


@router.post("/suites/{suite_id}/leases", response_model=LeaseRead, status_code=status.HTTP_201_CREATED)
async def create_lease(
    suite_id: str,
    body: LeaseCreate,
    db: AsyncSession = Depends(get_session),
) -> LeaseRead:
    result = await db.execute(select(Suite).where(Suite.id == suite_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    await _ensure_no_overlap(db, suite_id, body.lease_start_date, body.lease_end_date)
    lease = Lease(suite_id=suite_id, **body.model_dump())
    db.add(lease)
    await db.commit()
    result = await db.execute(
        select(Lease).where(Lease.id == lease.id).options(*_lease_options())
    )
    return result.scalar_one()


@router.get("/suites/{suite_id}/leases", response_model=list[LeaseRead])
async def list_leases(
    suite_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[LeaseRead]:
    result = await db.execute(
        select(Lease).where(Lease.suite_id == suite_id).options(*_lease_options())
    )
    return list(result.scalars().all())


@router.get("/leases/{lease_id}", response_model=LeaseRead)
async def get_lease(
    lease_id: str,
    db: AsyncSession = Depends(get_session),
) -> LeaseRead:
    return await _get_lease_or_404(lease_id, db)


@router.put("/leases/{lease_id}", response_model=LeaseRead)
async def update_lease(
    lease_id: str,
    body: LeaseUpdate,
    db: AsyncSession = Depends(get_session),
) -> LeaseRead:
    lease = await _get_lease_or_404(lease_id, db)
    new_start = body.lease_start_date or lease.lease_start_date
    new_end = body.lease_end_date or lease.lease_end_date
    if new_end <= new_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="lease_end_date must be after lease_start_date",
        )
    await _ensure_no_overlap(
        db,
        suite_id=lease.suite_id,
        lease_start_date=new_start,
        lease_end_date=new_end,
        exclude_lease_id=lease.id,
    )
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(lease, field, value)
    await db.commit()
    return await _get_lease_or_404(lease_id, db)


@router.delete("/leases/{lease_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lease(
    lease_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    lease = await _get_lease_or_404(lease_id, db)
    await db.delete(lease)
    await db.commit()


# ---- Rent steps ----

@router.post("/leases/{lease_id}/rent-steps", response_model=RentStepRead, status_code=201)
async def add_rent_step(
    lease_id: str,
    body: RentStepCreate,
    db: AsyncSession = Depends(get_session),
) -> RentStepRead:
    await _get_lease_or_404(lease_id, db)
    step = RentStep(lease_id=lease_id, **body.model_dump())
    db.add(step)
    await db.commit()
    await db.refresh(step)
    return step


@router.delete("/leases/{lease_id}/rent-steps/{step_id}", status_code=204)
async def delete_rent_step(
    lease_id: str,
    step_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(RentStep).where(RentStep.id == step_id, RentStep.lease_id == lease_id)
    )
    step = result.scalar_one_or_none()
    if step is None:
        raise HTTPException(status_code=404, detail="Rent step not found")
    await db.delete(step)
    await db.commit()


# ---- Free rent periods ----

@router.post("/leases/{lease_id}/free-rent-periods", response_model=FreeRentPeriodRead, status_code=201)
async def add_free_rent_period(
    lease_id: str,
    body: FreeRentPeriodCreate,
    db: AsyncSession = Depends(get_session),
) -> FreeRentPeriodRead:
    await _get_lease_or_404(lease_id, db)
    frp = FreeRentPeriod(lease_id=lease_id, **body.model_dump())
    db.add(frp)
    await db.commit()
    await db.refresh(frp)
    return frp


@router.delete("/leases/{lease_id}/free-rent-periods/{frp_id}", status_code=204)
async def delete_free_rent_period(
    lease_id: str,
    frp_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(FreeRentPeriod).where(
            FreeRentPeriod.id == frp_id, FreeRentPeriod.lease_id == lease_id
        )
    )
    frp = result.scalar_one_or_none()
    if frp is None:
        raise HTTPException(status_code=404, detail="Free rent period not found")
    await db.delete(frp)
    await db.commit()


# ---- Expense recovery overrides ----

@router.post("/leases/{lease_id}/expense-recoveries", response_model=LeaseExpenseRecoveryRead, status_code=201)
async def add_expense_recovery_override(
    lease_id: str,
    body: LeaseExpenseRecoveryCreate,
    db: AsyncSession = Depends(get_session),
) -> LeaseExpenseRecoveryRead:
    await _get_lease_or_404(lease_id, db)
    override = LeaseExpenseRecovery(lease_id=lease_id, **body.model_dump())
    db.add(override)
    await db.commit()
    await db.refresh(override)
    return override


@router.delete("/leases/{lease_id}/expense-recoveries/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense_recovery_override(
    lease_id: str,
    override_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(LeaseExpenseRecovery).where(
            LeaseExpenseRecovery.id == override_id,
            LeaseExpenseRecovery.lease_id == lease_id,
        )
    )
    override = result.scalar_one_or_none()
    if override is None:
        raise HTTPException(status_code=404, detail="Expense recovery override not found")
    await db.delete(override)
    await db.commit()
