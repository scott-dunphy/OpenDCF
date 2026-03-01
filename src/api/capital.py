from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.models.capital import PropertyCapitalProject
from src.models.property import Property
from src.schemas.capital import (
    PropertyCapitalProjectCreate,
    PropertyCapitalProjectRead,
    PropertyCapitalProjectUpdate,
)

router = APIRouter(prefix="/api/v1/properties", tags=["capital-projects"])


@router.post(
    "/{property_id}/capital-projects",
    response_model=PropertyCapitalProjectRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_capital_project(
    property_id: str,
    body: PropertyCapitalProjectCreate,
    db: AsyncSession = Depends(get_session),
) -> PropertyCapitalProjectRead:
    result = await db.execute(select(Property).where(Property.id == property_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Property not found")
    project = PropertyCapitalProject(property_id=property_id, **body.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{property_id}/capital-projects", response_model=list[PropertyCapitalProjectRead])
async def list_capital_projects(
    property_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[PropertyCapitalProjectRead]:
    result = await db.execute(
        select(PropertyCapitalProject).where(PropertyCapitalProject.property_id == property_id)
    )
    return list(result.scalars().all())


@router.put("/{property_id}/capital-projects/{project_id}", response_model=PropertyCapitalProjectRead)
async def update_capital_project(
    property_id: str,
    project_id: str,
    body: PropertyCapitalProjectUpdate,
    db: AsyncSession = Depends(get_session),
) -> PropertyCapitalProjectRead:
    result = await db.execute(
        select(PropertyCapitalProject).where(
            PropertyCapitalProject.id == project_id,
            PropertyCapitalProject.property_id == property_id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Capital project not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{property_id}/capital-projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_capital_project(
    property_id: str,
    project_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(PropertyCapitalProject).where(
            PropertyCapitalProject.id == project_id,
            PropertyCapitalProject.property_id == property_id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Capital project not found")
    await db.delete(project)
    await db.commit()
