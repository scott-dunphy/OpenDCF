from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.validation import owning_valuation, update_changes
from src.db.session import get_session
from src.models.lease import Tenant
from src.schemas.lease import TenantCreate, TenantRead, TenantUpdate

router = APIRouter(prefix="/api/v1/valuations", tags=["tenants"])


@router.post("/{valuation_id}/tenants", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    valuation_id: str,
    body: TenantCreate,
    db: AsyncSession = Depends(get_session),
) -> TenantRead:
    valuation = await owning_valuation(db, valuation_id)
    tenant = Tenant(property_id=valuation.property_id, valuation_id=valuation_id, **body.model_dump())
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant


@router.get("/{valuation_id}/tenants", response_model=list[TenantRead])
async def list_tenants(
    valuation_id: str,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_session),
) -> list[TenantRead]:
    result = await db.execute(
        select(Tenant)
        .where(Tenant.valuation_id == valuation_id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/{valuation_id}/tenants/{tenant_id}", response_model=TenantRead)
async def get_tenant(
    valuation_id: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_session),
) -> TenantRead:
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.valuation_id == valuation_id)
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.put("/{valuation_id}/tenants/{tenant_id}", response_model=TenantRead)
async def update_tenant(
    valuation_id: str,
    tenant_id: str,
    body: TenantUpdate,
    db: AsyncSession = Depends(get_session),
) -> TenantRead:
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.valuation_id == valuation_id)
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    for field, value in update_changes(Tenant, body).items():
        setattr(tenant, field, value)
    await db.commit()
    await db.refresh(tenant)
    return tenant


@router.delete("/{valuation_id}/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    valuation_id: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.valuation_id == valuation_id)
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await db.delete(tenant)
    await db.commit()
