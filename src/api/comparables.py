from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.session import get_session
from src.models.comparable import ComparableSale, ComparableSelection
from src.models.property import Property
from src.models.valuation import Valuation
from src.schemas.comparable import (
    ComparableSaleCreate,
    ComparableSaleRead,
    ComparableSaleUpdate,
    ComparableSelectionRead,
    ComparableSelectionWrite,
    ManualComparableAnalysis,
    ReconciliationRequest,
    ReconciliationResult,
    StatisticalValuationRequest,
    StatisticalValuationResult,
)
from src.services.comparable_service import ComparableService

router = APIRouter(prefix="/api/v1", tags=["comparable sales"])


@router.post("/comparable-sales", response_model=ComparableSaleRead, status_code=status.HTTP_201_CREATED)
async def create_sale(body: ComparableSaleCreate, db: AsyncSession = Depends(get_session)):
    sale = ComparableSale(**body.model_dump())
    db.add(sale)
    await db.commit()
    await db.refresh(sale)
    return sale


@router.get("/comparable-sales", response_model=list[ComparableSaleRead])
async def list_sales(
    property_type: str | None = None,
    market: str | None = None,
    verified_only: bool = False,
    limit: int = Query(default=250, ge=1, le=2000),
    db: AsyncSession = Depends(get_session),
):
    query = select(ComparableSale).order_by(ComparableSale.sale_date.desc()).limit(limit)
    if property_type:
        query = query.where(ComparableSale.property_type == property_type)
    if market:
        query = query.where(ComparableSale.market == market)
    if verified_only:
        query = query.where(ComparableSale.verification_status == "verified")
    return list((await db.execute(query)).scalars().all())


@router.get("/comparable-sales/{sale_id}", response_model=ComparableSaleRead)
async def get_sale(sale_id: str, db: AsyncSession = Depends(get_session)):
    sale = await db.get(ComparableSale, sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="Comparable sale not found")
    return sale


@router.put("/comparable-sales/{sale_id}", response_model=ComparableSaleRead)
async def update_sale(
    sale_id: str, body: ComparableSaleUpdate, db: AsyncSession = Depends(get_session)
):
    sale = await db.get(ComparableSale, sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="Comparable sale not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(sale, key, value)
    await db.commit()
    await db.refresh(sale)
    return sale


@router.delete("/comparable-sales/{sale_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sale(sale_id: str, db: AsyncSession = Depends(get_session)):
    sale = await db.get(ComparableSale, sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="Comparable sale not found")
    await db.delete(sale)
    await db.commit()


async def _property(property_id: str, db: AsyncSession) -> Property:
    prop = await db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


@router.put(
    "/properties/{property_id}/comparable-sales/{sale_id}", response_model=ComparableSelectionRead
)
async def select_comparable(
    property_id: str,
    sale_id: str,
    body: ComparableSelectionWrite,
    db: AsyncSession = Depends(get_session),
):
    await _property(property_id, db)
    if await db.get(ComparableSale, sale_id) is None:
        raise HTTPException(status_code=404, detail="Comparable sale not found")
    selection = (await db.execute(select(ComparableSelection).where(
        ComparableSelection.property_id == property_id,
        ComparableSelection.sale_id == sale_id,
    ))).scalar_one_or_none()
    if selection is None:
        selection = ComparableSelection(property_id=property_id, sale_id=sale_id)
        db.add(selection)
    values = body.model_dump()
    values["adjustments"] = {key: float(value) for key, value in body.adjustments.items()}
    for key, value in values.items():
        setattr(selection, key, value)
    await db.commit()
    result = await db.execute(select(ComparableSelection).where(
        ComparableSelection.id == selection.id
    ).options(selectinload(ComparableSelection.sale)))
    return result.scalar_one()


@router.get("/properties/{property_id}/comparable-sales", response_model=list[ComparableSelectionRead])
async def selected_comparables(property_id: str, db: AsyncSession = Depends(get_session)):
    await _property(property_id, db)
    result = await db.execute(select(ComparableSelection).where(
        ComparableSelection.property_id == property_id
    ).options(selectinload(ComparableSelection.sale)))
    return list(result.scalars().all())


@router.get(
    "/properties/{property_id}/comparable-analysis/manual", response_model=ManualComparableAnalysis
)
async def manual_analysis(property_id: str, db: AsyncSession = Depends(get_session)):
    prop = await _property(property_id, db)
    return await ComparableService(db).manual_analysis(prop)


@router.post(
    "/properties/{property_id}/comparable-analysis/statistical",
    response_model=StatisticalValuationResult,
)
async def statistical_analysis(
    property_id: str,
    body: StatisticalValuationRequest,
    db: AsyncSession = Depends(get_session),
):
    prop = await _property(property_id, db)
    return await ComparableService(db).statistical_analysis(prop, body)


@router.post(
    "/properties/{property_id}/comparable-analysis/reconcile",
    response_model=ReconciliationResult,
)
async def reconcile(
    property_id: str,
    body: ReconciliationRequest,
    db: AsyncSession = Depends(get_session),
):
    prop = await _property(property_id, db)
    manual = await ComparableService(db).manual_analysis(prop)
    indications: dict[str, Decimal] = {}
    warnings: list[str] = list(manual.warnings)
    if manual.indicated_value is not None:
        indications["sales_comparison"] = manual.indicated_value
    if body.statistical_price_per_area is not None:
        indications["statistical"] = body.statistical_price_per_area * prop.total_area
    if body.valuation_id:
        valuation = await db.get(Valuation, body.valuation_id)
        if valuation is None or valuation.property_id != property_id:
            raise HTTPException(status_code=422, detail="Valuation does not belong to the property")
        if valuation.result_npv is not None:
            indications["dcf"] = valuation.result_npv
        if valuation.result_direct_cap_value is not None:
            indications["direct_cap"] = valuation.result_direct_cap_value
    positive = {key: Decimal(str(value)) for key, value in body.weights.items()
                if value > 0 and key in indications}
    total = sum(positive.values(), Decimal(0))
    if total <= 0:
        raise HTTPException(status_code=422, detail="At least one available indication needs positive weight")
    normalized = {key: value / total for key, value in positive.items()}
    if len(normalized) == 1:
        warnings.append("Reconciliation relies on only one available valuation method.")
    reconciled = sum((indications[key] * weight for key, weight in normalized.items()), Decimal(0))
    return ReconciliationResult(
        indications=indications,
        normalized_weights=normalized,
        reconciled_value=reconciled,
        warnings=warnings,
    )
