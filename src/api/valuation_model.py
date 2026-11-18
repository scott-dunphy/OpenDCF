"""The valuation page's model: everything a valuation owns, its readiness, unit-mix conversion."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.capital import list_capital_projects
from src.api.expenses import list_expenses
from src.api.leases import list_valuation_leases
from src.api.other_income import list_other_income
from src.api.recovery_pools import list_recovery_pools
from src.api.recovery_structures import list_recovery_structures
from src.api.suites import list_suites
from src.api.validation import owning_valuation
from src.db.session import get_session
from src.models.property import Property, Suite
from src.models.valuation import Valuation
from src.schemas.capital import PropertyCapitalProjectRead
from src.schemas.expense import PropertyExpenseRead
from src.schemas.lease import LeaseRead
from src.schemas.other_income import PropertyOtherIncomeRead
from src.schemas.property import PropertyRead, SuiteRead
from src.schemas.recovery_pool import RecoveryPoolRead
from src.schemas.recovery_structure import RecoveryStructureRead
from src.schemas.valuation import ValuationRead
from src.services.readiness import Readiness
from src.services.readiness import assess as assess_readiness

router = APIRouter(prefix="/api/v1", tags=["valuation-model"])


@router.get("/valuations/{valuation_id}/readiness", response_model=Readiness)
async def valuation_readiness(valuation_id: str, db: AsyncSession = Depends(get_session)) -> Readiness:
    """What the valuation's model still needs before a run means anything."""
    valuation = await owning_valuation(db, valuation_id)
    return await assess_readiness(db, await db.get(Property, valuation.property_id), valuation)


class ValuationWorkspace(BaseModel):
    """Everything the valuation's model pages show, in the same shapes as the individual endpoints."""
    property: PropertyRead
    valuation: ValuationRead
    suites: list[SuiteRead]
    leases: list[LeaseRead]
    expenses: list[PropertyExpenseRead]
    other_income: list[PropertyOtherIncomeRead]
    capital_projects: list[PropertyCapitalProjectRead]
    recovery_structures: list[RecoveryStructureRead]
    recovery_pools: list[RecoveryPoolRead]
    readiness: Readiness | None


@router.get("/valuations/{valuation_id}/workspace", response_model=ValuationWorkspace)
async def valuation_workspace(valuation_id: str, db: AsyncSession = Depends(get_session)) -> ValuationWorkspace:
    """The valuation's model in one request, reusing each list endpoint's query."""
    valuation = await owning_valuation(db, valuation_id)
    prop = await db.get(Property, valuation.property_id)
    try:
        readiness = await assess_readiness(db, prop, valuation)
    except Exception:  # the page shows without its checklist
        readiness = None
    return ValuationWorkspace(
        property=prop,
        valuation=valuation,
        suites=await list_suites(valuation_id, db),
        leases=await list_valuation_leases(valuation_id, db),
        expenses=await list_expenses(valuation_id, db),
        other_income=await list_other_income(valuation_id, db),
        capital_projects=await list_capital_projects(valuation_id, db),
        recovery_structures=await list_recovery_structures(valuation_id, db),
        recovery_pools=await list_recovery_pools(valuation_id, db),
        readiness=readiness,
    )


@router.post("/valuations/{valuation_id}/self-storage/convert-rent-roll", response_model=ValuationRead)
async def convert_storage_rent_roll(valuation_id: str, db: AsyncSession = Depends(get_session)) -> Valuation:
    """Start a self storage unit mix from the valuation's suites, market profiles and leases.

    Each suite of a unit-based rent roll becomes a unit type: units = suite area, street rate = its market rent, in-place
    rate = the lease in force at the analysis start (else street), occupied = units less general
    vacancy, monthly move-outs = (1 - renewal probability) / lease term, street-rate growth = the
    unit-weighted growth of the profiles used. SF per unit is not in the
    rent roll and is set to 100 for the user to correct; the property's area becomes that rentable SF.
    Suites and leases are left in place but no longer valued.
    """
    import json

    from src.models.lease import Lease
    from src.models.market import MarketLeasingProfile
    from src.schemas.self_storage import SelfStorageOperatingModel

    valuation = await owning_valuation(db, valuation_id)
    prop = await db.get(Property, valuation.property_id)
    if prop.property_type != "self_storage":
        raise HTTPException(422, "Only self storage properties have a unit mix")
    if valuation.self_storage_assumptions_json:
        raise HTTPException(409, "This valuation already has a unit mix")
    suites = list((await db.execute(select(Suite).where(Suite.valuation_id == valuation.id))).scalars())
    if not suites:
        raise HTTPException(422, "There is no rent roll to convert")
    if prop.area_unit != "unit":
        raise HTTPException(422, "This rent roll is in square feet, so unit counts are unknown. "
                                 "Enter the unit mix on the Unit Mix tab instead.")
    # The property's area becomes rentable SF, which would re-read any other valuation's unit rent roll
    sibling = (await db.execute(
        select(Valuation.name).join(Suite, Suite.valuation_id == Valuation.id)
        .where(Valuation.property_id == prop.id, Valuation.id != valuation.id,
               Valuation.self_storage_assumptions_json.is_(None)).limit(1)
    )).scalar()
    if sibling is not None:
        raise HTTPException(409, f"Valuation '{sibling}' still values this property from its unit rent roll. "
                                 "Convert or delete it first.")
    profiles = {
        p.space_type: p
        for p in (await db.execute(
            select(MarketLeasingProfile).where(MarketLeasingProfile.valuation_id == valuation.id)
        )).scalars()
    }
    leases = list((await db.execute(select(Lease).where(Lease.suite_id.in_([s.id for s in suites])))).scalars())
    start = valuation.analysis_start_date_override or prop.analysis_start_date
    unit_types, churn, weighted_growth = [], [], []
    for suite in suites:
        market = profiles.get(suite.market_space_type or suite.space_type)  # as the engine matches it
        street = market.market_rent_per_unit if market else Decimal(0)
        active = next(
            (l for l in leases if l.suite_id == suite.id and l.lease_type != "market"
             and l.lease_start_date <= start <= l.lease_end_date),
            None,
        )
        count = int(suite.area)
        vacancy = market.general_vacancy_pct if market else Decimal(0)
        unit_types.append({
            "name": suite.suite_name,
            "sf_per_unit": "100",
            "count": count,
            "occupied_units": str(round(Decimal(count) * (1 - vacancy), 2)),
            "in_place_rate": str(active.base_rent_per_unit if active else street),
            "street_rate": str(street),
        })
        if market and market.new_lease_term_months:
            churn.append((1 - market.renewal_probability) / market.new_lease_term_months)
        if market:
            weighted_growth.append((count, market.rent_growth_rate_pct))
    total_units = sum(c for c, _ in weighted_growth)
    growth = sum(c * g for c, g in weighted_growth) / total_units if total_units else Decimal(0)
    model = {
        "unit_types": unit_types,
        "street_rate_growth_pct": str(growth),
        "churn": {"monthly_move_out_pct": str(sum(churn) / len(churn)) if churn else "0"},
    }
    names = [u["name"] for u in unit_types]
    if len(set(names)) != len(names):
        raise HTTPException(422, "Suite names must be unique to become unit types")
    parsed = SelfStorageOperatingModel.model_validate(model)
    valuation.self_storage_assumptions_json = json.dumps(model)
    prop.area_unit, prop.total_area = "sf", parsed.rentable_sf
    await db.commit()
    await db.refresh(valuation)
    return valuation
