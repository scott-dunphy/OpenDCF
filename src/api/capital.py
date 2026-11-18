from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.validation import owning_valuation, update_changes
from src.db.session import get_session
from src.models.capital import PropertyCapitalProject
from src.schemas.capital import (
    PropertyCapitalProjectCreate,
    PropertyCapitalProjectRead,
    PropertyCapitalProjectUpdate,
)

router = APIRouter(prefix="/api/v1/valuations", tags=["capital-projects"])


@router.post(
    "/{valuation_id}/capital-projects",
    response_model=PropertyCapitalProjectRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_capital_project(
    valuation_id: str,
    body: PropertyCapitalProjectCreate,
    db: AsyncSession = Depends(get_session),
) -> PropertyCapitalProjectRead:
    valuation = await owning_valuation(db, valuation_id)
    project = PropertyCapitalProject(property_id=valuation.property_id, valuation_id=valuation_id, **body.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{valuation_id}/capital-projects", response_model=list[PropertyCapitalProjectRead])
async def list_capital_projects(
    valuation_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[PropertyCapitalProjectRead]:
    result = await db.execute(
        select(PropertyCapitalProject).where(PropertyCapitalProject.valuation_id == valuation_id)
    )
    return list(result.scalars().all())


@router.put("/{valuation_id}/capital-projects/{project_id}", response_model=PropertyCapitalProjectRead)
async def update_capital_project(
    valuation_id: str,
    project_id: str,
    body: PropertyCapitalProjectUpdate,
    db: AsyncSession = Depends(get_session),
) -> PropertyCapitalProjectRead:
    result = await db.execute(
        select(PropertyCapitalProject).where(
            PropertyCapitalProject.id == project_id,
            PropertyCapitalProject.valuation_id == valuation_id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Capital project not found")
    for field, value in update_changes(PropertyCapitalProject, body).items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{valuation_id}/capital-projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_capital_project(
    valuation_id: str,
    project_id: str,
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(PropertyCapitalProject).where(
            PropertyCapitalProject.id == project_id,
            PropertyCapitalProject.valuation_id == valuation_id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Capital project not found")
    await db.delete(project)
    await db.commit()
