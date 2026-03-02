from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.models.lease import Tenant
from src.models.property import Property
from src.schemas.lease import TenantCreate, TenantRead, TenantUpdate

router = APIRouter(prefix="/api/v1/properties", tags=["tenants"])


@router.post("/{property_id}/tenants", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    property_id: str,
    body: TenantCreate,
    db: AsyncSession = Depends(get_session),
) -> TenantRead:
    property_result = await db.execute(select(Property).where(Property.id == property_id))
    if property_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Property not found")
    tenant = Tenant(property_id=property_id, **body.model_dump())
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant


@router.get("/{property_id}/tenants", response_model=list[TenantRead])
async def list_tenants(
    property_id: str,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_session),
) -> list[TenantRead]:
    result = await db.execute(
        select(Tenant)
        .where(Tenant.property_id == property_id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/{property_id}/tenants/{tenant_id}", response_model=TenantRead)
async def get_tenant(
    property_id: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_session),
) -> TenantRead:
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.property_id == property_id)
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.put("/{property_id}/tenants/{tenant_id}", response_model=TenantRead)
async def update_tenant(
    property_id: str,
    tenant_id: str,
    body: TenantUpdate,
    db: AsyncSession = Depends(get_session),
) -> TenantRead:
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.property_id == property_id)
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(tenant, field, value)
    await db.commit()
    await db.refresh(tenant)
    return tenant


@router.delete("/{property_id}/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    property_id: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.property_id == property_id)
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await db.delete(tenant)
    await db.commit()
