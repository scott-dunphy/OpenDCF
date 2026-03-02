from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.models.property import Property
from src.models.valuation import Valuation
from src.schemas.cashflow import (
    AnnualCashFlowSummary,
    KeyMetricsSummary,
    LeaseExpirationEntry,
    RentRollEntry,
    TenantCashFlowDetail,
    TenantRecoveryAuditEntry,
    ValuationRunResponse,
)
from src.schemas.valuation import ValuationCreate, ValuationRead, ValuationUpdate
from src.services.valuation_service import ValuationService

router = APIRouter(prefix="/api/v1", tags=["valuations"])


@router.post(
    "/properties/{property_id}/valuations",
    response_model=ValuationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_valuation(
    property_id: str,
    body: ValuationCreate,
    db: AsyncSession = Depends(get_session),
) -> ValuationRead:
    result = await db.execute(select(Property).where(Property.id == property_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Property not found")
    valuation = Valuation(property_id=property_id, **body.model_dump())
    db.add(valuation)
    await db.commit()
    await db.refresh(valuation)
    return valuation


@router.get("/properties/{property_id}/valuations", response_model=list[ValuationRead])
async def list_valuations(
    property_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[ValuationRead]:
    result = await db.execute(
        select(Valuation).where(Valuation.property_id == property_id)
    )
    return list(result.scalars().all())


@router.get("/valuations/{valuation_id}", response_model=ValuationRead)
async def get_valuation(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> ValuationRead:
    result = await db.execute(select(Valuation).where(Valuation.id == valuation_id))
    v = result.scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return v


@router.put("/valuations/{valuation_id}", response_model=ValuationRead)
async def update_valuation(
    valuation_id: str,
    body: ValuationUpdate,
    db: AsyncSession = Depends(get_session),
) -> ValuationRead:
    result = await db.execute(select(Valuation).where(Valuation.id == valuation_id))
    v = result.scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(v, field, value)
    await db.commit()
    await db.refresh(v)
    return v


@router.delete("/valuations/{valuation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_valuation(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(select(Valuation).where(Valuation.id == valuation_id))
    v = result.scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    await db.delete(v)
    await db.commit()


@router.post("/valuations/{valuation_id}/run", response_model=ValuationRunResponse)
async def run_valuation(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> ValuationRunResponse:
    """
    Execute the DCF engine for this valuation.
    Loads all property data, runs the engine, persists results, returns full output.
    """
    result = await db.execute(select(Valuation).where(Valuation.id == valuation_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Valuation not found")

    service = ValuationService(db)
    try:
        return await service.execute_valuation(valuation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Engine error: {exc!s}")


# ---- Reports ----

@router.get("/valuations/{valuation_id}/reports/cash-flow-summary", response_model=list[AnnualCashFlowSummary])
async def report_cash_flow_summary(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[AnnualCashFlowSummary]:
    service = ValuationService(db)
    response = await service.get_results(valuation_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response.annual_cash_flows


@router.get("/valuations/{valuation_id}/reports/rent-roll", response_model=list[RentRollEntry])
async def report_rent_roll(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[RentRollEntry]:
    service = ValuationService(db)
    response = await service.get_results(valuation_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response.rent_roll


@router.get("/valuations/{valuation_id}/reports/lease-expirations", response_model=list[LeaseExpirationEntry])
async def report_lease_expirations(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[LeaseExpirationEntry]:
    service = ValuationService(db)
    response = await service.get_results(valuation_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response.lease_expiration_schedule


@router.get("/valuations/{valuation_id}/reports/key-metrics", response_model=KeyMetricsSummary)
async def report_key_metrics(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> KeyMetricsSummary:
    service = ValuationService(db)
    response = await service.get_results(valuation_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    if response.key_metrics is None:
        raise HTTPException(status_code=400, detail="Valuation has not been run yet")
    return response.key_metrics


@router.get("/valuations/{valuation_id}/reports/tenant-detail", response_model=list[TenantCashFlowDetail])
async def report_tenant_detail(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[TenantCashFlowDetail]:
    service = ValuationService(db)
    response = await service.get_results(valuation_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response.tenant_cash_flows


@router.get("/valuations/{valuation_id}/reports/recovery-audit", response_model=list[TenantRecoveryAuditEntry])
async def report_recovery_audit(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[TenantRecoveryAuditEntry]:
    service = ValuationService(db)
    response = await service.get_results(valuation_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response.recovery_audit


@router.get("/valuations/{valuation_id}/reports/full", response_model=ValuationRunResponse)
async def report_full(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> ValuationRunResponse:
    service = ValuationService(db)
    response = await service.get_results(valuation_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return response
