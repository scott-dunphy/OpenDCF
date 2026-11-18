from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.validation import update_changes
from src.db.session import get_session
from src.models.market import MarketLeasingProfile
from src.models.recovery_structure import RecoveryStructure
from src.models.valuation import Valuation
from src.schemas.market import (
    MarketLeasingProfileCreate,
    MarketLeasingProfileRead,
    MarketLeasingProfileUpdate,
)

router = APIRouter(prefix="/api/v1/valuations", tags=["market-assumptions"])


async def _check_next_profile(db: AsyncSession, valuation_id: str, next_profile_id: str | None) -> None:
    """MLA chaining must point to a profile of the same valuation."""
    if not next_profile_id:
        return
    found = await db.execute(
        select(MarketLeasingProfile.id).where(
            MarketLeasingProfile.id == next_profile_id,
            MarketLeasingProfile.valuation_id == valuation_id,
        )
    )
    if found.scalar_one_or_none() is None:
        raise HTTPException(status_code=422, detail="next_profile_id must be a market profile of this valuation")


async def _check_recovery_structure(db: AsyncSession, valuation_id: str, structure_id: str | None) -> None:
    """A profile's recovery structure must be one of its valuation's."""
    if not structure_id:
        return
    structure = await db.get(RecoveryStructure, structure_id)
    if structure is None or structure.valuation_id != valuation_id:
        raise HTTPException(status_code=422, detail="recovery_structure_id must be a recovery structure of this valuation")


async def _check_unique_space_type(db: AsyncSession, valuation_id: str, space_type: str) -> None:
    """The engine keys market assumptions by space_type, so it must be unique per valuation."""
    query = select(MarketLeasingProfile.id).where(
        MarketLeasingProfile.valuation_id == valuation_id,
        MarketLeasingProfile.space_type == space_type,
    )
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status_code=409, detail=f"A market profile for space type '{space_type}' already exists in this valuation",
        )


@router.post(
    "/{valuation_id}/market-profiles",
    response_model=MarketLeasingProfileRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_market_profile(
    valuation_id: str,
    body: MarketLeasingProfileCreate,
    db: AsyncSession = Depends(get_session),
) -> MarketLeasingProfileRead:
    valuation = await db.get(Valuation, valuation_id)
    if valuation is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    await _check_next_profile(db, valuation_id, body.next_profile_id)
    await _check_recovery_structure(db, valuation_id, body.recovery_structure_id)
    await _check_unique_space_type(db, valuation_id, body.space_type)
    values = body.model_dump() | {"recovery_structure_id": body.recovery_structure_id or None}
    profile = MarketLeasingProfile(valuation_id=valuation_id, property_id=valuation.property_id, **values)
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/{valuation_id}/market-profiles", response_model=list[MarketLeasingProfileRead])
async def list_market_profiles(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[MarketLeasingProfileRead]:
    result = await db.execute(
        select(MarketLeasingProfile).where(MarketLeasingProfile.valuation_id == valuation_id)
    )
    return list(result.scalars().all())


@router.get("/{valuation_id}/market-profiles/{profile_id}", response_model=MarketLeasingProfileRead)
async def get_market_profile(
    valuation_id: str,
    profile_id: str,
    db: AsyncSession = Depends(get_session),
) -> MarketLeasingProfileRead:
    result = await db.execute(
        select(MarketLeasingProfile).where(
            MarketLeasingProfile.id == profile_id,
            MarketLeasingProfile.valuation_id == valuation_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Market profile not found")
    return profile


@router.put("/{valuation_id}/market-profiles/{profile_id}", response_model=MarketLeasingProfileRead)
async def update_market_profile(
    valuation_id: str,
    profile_id: str,
    body: MarketLeasingProfileUpdate,
    db: AsyncSession = Depends(get_session),
) -> MarketLeasingProfileRead:
    result = await db.execute(
        select(MarketLeasingProfile).where(
            MarketLeasingProfile.id == profile_id,
            MarketLeasingProfile.valuation_id == valuation_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Market profile not found")
    await _check_next_profile(db, valuation_id, body.next_profile_id)
    await _check_recovery_structure(db, profile.valuation_id, body.recovery_structure_id)
    for field, value in update_changes(MarketLeasingProfile, body).items():
        setattr(profile, field, value)
    if "recovery_structure_id" in body.model_fields_set and not body.recovery_structure_id:
        profile.recovery_structure_id = None   # blank = copy the expiring lease's recovery terms
    if body.next_profile_id == "":  # empty string clears the chain
        profile.next_profile_id = None
    if profile.lease_escalation_pct is not None and profile.lease_escalation_per_unit is not None:
        await db.rollback()
        raise HTTPException(
            status_code=422, detail="Set the % or the $/SF market lease escalation, not both",
        )
    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete("/{valuation_id}/market-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_market_profile(
    valuation_id: str,
    profile_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(MarketLeasingProfile).where(
            MarketLeasingProfile.id == profile_id,
            MarketLeasingProfile.valuation_id == valuation_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Market profile not found")
    await db.delete(profile)
    await db.commit()
