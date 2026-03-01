from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.models.market import MarketLeasingProfile
from src.models.property import Property
from src.schemas.market import (
    MarketLeasingProfileCreate,
    MarketLeasingProfileRead,
    MarketLeasingProfileUpdate,
)

router = APIRouter(prefix="/api/v1/properties", tags=["market-assumptions"])


@router.post(
    "/{property_id}/market-profiles",
    response_model=MarketLeasingProfileRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_market_profile(
    property_id: str,
    body: MarketLeasingProfileCreate,
    db: AsyncSession = Depends(get_session),
) -> MarketLeasingProfileRead:
    result = await db.execute(select(Property).where(Property.id == property_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Property not found")
    profile = MarketLeasingProfile(property_id=property_id, **body.model_dump())
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/{property_id}/market-profiles", response_model=list[MarketLeasingProfileRead])
async def list_market_profiles(
    property_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[MarketLeasingProfileRead]:
    result = await db.execute(
        select(MarketLeasingProfile).where(MarketLeasingProfile.property_id == property_id)
    )
    return list(result.scalars().all())


@router.get("/{property_id}/market-profiles/{profile_id}", response_model=MarketLeasingProfileRead)
async def get_market_profile(
    property_id: str,
    profile_id: str,
    db: AsyncSession = Depends(get_session),
) -> MarketLeasingProfileRead:
    result = await db.execute(
        select(MarketLeasingProfile).where(
            MarketLeasingProfile.id == profile_id,
            MarketLeasingProfile.property_id == property_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Market profile not found")
    return profile


@router.put("/{property_id}/market-profiles/{profile_id}", response_model=MarketLeasingProfileRead)
async def update_market_profile(
    property_id: str,
    profile_id: str,
    body: MarketLeasingProfileUpdate,
    db: AsyncSession = Depends(get_session),
) -> MarketLeasingProfileRead:
    result = await db.execute(
        select(MarketLeasingProfile).where(
            MarketLeasingProfile.id == profile_id,
            MarketLeasingProfile.property_id == property_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Market profile not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete("/{property_id}/market-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_market_profile(
    property_id: str,
    profile_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(MarketLeasingProfile).where(
            MarketLeasingProfile.id == profile_id,
            MarketLeasingProfile.property_id == property_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Market profile not found")
    await db.delete(profile)
    await db.commit()
