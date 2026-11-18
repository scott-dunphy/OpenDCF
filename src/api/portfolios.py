import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.validation import reject_null_columns
from src.db.session import get_session
from src.models.portfolio import (
    AssumptionProfile,
    Portfolio,
    PortfolioRun,
    PortfolioScenario,
    portfolio_properties,
)
from src.models.property import Property
from src.schemas.portfolio import (
    AssumptionSettingsRead,
    AssumptionSettingsUpdate,
    RangeBounds,
    check_ranges,
    AllocationSensitivityRequest,
    AllocationSensitivityResult,
    AssumptionProfileCreate,
    AssumptionProfileRead,
    AssumptionProfileUpdate,
    AssumptionValues,
    PortfolioCreate,
    PortfolioMembership,
    PortfolioInterestUpdate,
    PortfolioPropertySummary,
    PortfolioRead,
    PortfolioRunListItem,
    PortfolioRunRead,
    PortfolioRunRequest,
    PortfolioScenarioCreate,
    PortfolioScenarioRead,
    PortfolioScenarioUpdate,
    PortfolioUpdate,
    ResolvedAssumptionsRead,
    ScenarioOverride,
)
from src.services.portfolio_disposition import analyze_dispositions
from src.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/api/v1", tags=["portfolios"])


# =========================================================================
# Helpers
# =========================================================================


async def _get_portfolio(db: AsyncSession, portfolio_id: str) -> Portfolio:
    portfolio = await PortfolioService(db).load_portfolio(portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


async def _load_properties(db: AsyncSession, property_ids: list[str]) -> list[Property]:
    if not property_ids:
        return []
    rows = (await db.execute(select(Property).where(Property.id.in_(property_ids)))).scalars().all()
    missing = set(property_ids) - {p.id for p in rows}
    if missing:
        raise HTTPException(
            status_code=404, detail=f"Property not found: {', '.join(sorted(missing))}"
        )
    return list(rows)


async def _portfolio_read(db: AsyncSession, portfolio: Portfolio) -> PortfolioRead:
    interests = (
        (
            await db.execute(
                select(portfolio_properties).where(
                    portfolio_properties.c.portfolio_id == portfolio.id
                )
            )
        )
        .mappings()
        .all()
    )
    by_property = {row["property_id"]: row for row in interests}
    return PortfolioRead(
        id=portfolio.id,
        name=portfolio.name,
        description=portfolio.description,
        created_at=portfolio.created_at,
        updated_at=portfolio.updated_at,
        properties=[
            PortfolioPropertySummary(
                id=prop.id,
                name=prop.name,
                property_type=prop.property_type,
                market=prop.market,
                latitude=prop.latitude,
                longitude=prop.longitude,
                ownership_pct=Decimal(str(by_property[prop.id]["ownership_pct"])),
                property_ownership_pct=prop.ownership_pct,
                effective_from=by_property[prop.id]["effective_from"],
                effective_to=by_property[prop.id]["effective_to"],
                acquisition_cost=by_property[prop.id]["acquisition_cost"],
                commitment=by_property[prop.id]["commitment"],
                currency=by_property[prop.id]["currency"],
            )
            for prop in portfolio.properties
        ],
    )


async def _initialize_interests(
    db: AsyncSession,
    portfolio_id: str,
    properties: list[Property],
) -> None:
    for prop in properties:
        await db.execute(
            update(portfolio_properties)
            .where(
                portfolio_properties.c.portfolio_id == portfolio_id,
                portfolio_properties.c.property_id == prop.id,
            )
            .values(
                ownership_pct=(
                    prop.ownership_pct if prop.ownership_pct is not None else Decimal(1)
                )
            )
        )
    await db.commit()


def _profile_read(p: AssumptionProfile) -> AssumptionProfileRead:
    from src.services import cbsa

    return AssumptionProfileRead(
        id=p.id,
        name=p.name,
        portfolio_id=p.portfolio_id,
        property_type=p.property_type,
        market=p.market,
        values=AssumptionValues.model_validate(json.loads(p.values_json or "{}")),
        ranges={k: RangeBounds(**v) for k, v in json.loads(p.ranges_json or "{}").items()},
        comment=p.comment,
        cbsa_code=p.cbsa_code,
        cbsa_title=cbsa.title(p.cbsa_code),
        state=p.state,
        quality_score=p.quality_score,
        as_of=p.as_of,
        source=p.source,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _ranges_json(ranges: dict[str, RangeBounds] | None) -> str:
    return json.dumps({k: {"low": str(r.low), "high": str(r.high)} for k, r in (ranges or {}).items()})


async def _check_unique_scope(db: AsyncSession, p: AssumptionProfile) -> None:
    """Two profiles at the same scope would tie in the resolver."""
    stmt = select(AssumptionProfile.name).where(AssumptionProfile.id != (p.id or ""))
    for col in ("portfolio_id", "property_type", "cbsa_code", "market", "state", "quality_score"):
        value = getattr(p, col)
        column = getattr(AssumptionProfile, col)
        stmt = stmt.where(column.is_(None) if value is None else column == value)
    other = (await db.execute(stmt)).scalars().first()
    if other is not None:
        raise HTTPException(status_code=409, detail=f"Profile '{other}' already covers this scope; edit it instead")


def _scenario_read(s: PortfolioScenario) -> PortfolioScenarioRead:
    return PortfolioScenarioRead(
        id=s.id,
        portfolio_id=s.portfolio_id,
        name=s.name,
        description=s.description,
        probability_pct=s.probability_pct,
        overrides=[
            ScenarioOverride.model_validate(o) for o in json.loads(s.overrides_json or "[]")
        ],
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _values_json(values: AssumptionValues) -> str:
    return values.model_dump_json(exclude_none=True)


def _overrides_json(overrides: list[ScenarioOverride]) -> str:
    return json.dumps([o.model_dump(mode="json", exclude_none=True) for o in overrides])


# =========================================================================
# Portfolios
# =========================================================================


@router.post("/portfolios", response_model=PortfolioRead, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    body: PortfolioCreate, db: AsyncSession = Depends(get_session)
) -> PortfolioRead:
    portfolio = Portfolio(name=body.name, description=body.description)
    portfolio.properties = await _load_properties(db, body.property_ids)
    db.add(portfolio)
    await db.commit()
    await _initialize_interests(db, portfolio.id, portfolio.properties)
    return await _portfolio_read(db, await _get_portfolio(db, portfolio.id))


@router.get("/portfolios", response_model=list[PortfolioRead])
async def list_portfolios(db: AsyncSession = Depends(get_session)) -> list[PortfolioRead]:
    rows = await db.execute(
        select(Portfolio).options(selectinload(Portfolio.properties)).order_by(Portfolio.name)
    )
    return [await _portfolio_read(db, item) for item in rows.scalars().all()]


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioRead)
async def get_portfolio(
    portfolio_id: str, db: AsyncSession = Depends(get_session)
) -> PortfolioRead:
    return await _portfolio_read(db, await _get_portfolio(db, portfolio_id))


@router.put("/portfolios/{portfolio_id}", response_model=PortfolioRead)
async def update_portfolio(
    portfolio_id: str, body: PortfolioUpdate, db: AsyncSession = Depends(get_session)
) -> PortfolioRead:
    portfolio = await _get_portfolio(db, portfolio_id)
    changes = body.model_dump(exclude_unset=True)
    reject_null_columns(Portfolio, changes)
    for k, v in changes.items():
        setattr(portfolio, k, v)
    await db.commit()
    return await _portfolio_read(db, await _get_portfolio(db, portfolio_id))


@router.delete("/portfolios/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio(portfolio_id: str, db: AsyncSession = Depends(get_session)) -> None:
    portfolio = await _get_portfolio(db, portfolio_id)
    await db.delete(portfolio)
    await db.commit()


@router.post("/portfolios/{portfolio_id}/properties", response_model=PortfolioRead)
async def add_portfolio_properties(
    portfolio_id: str, body: PortfolioMembership, db: AsyncSession = Depends(get_session)
) -> PortfolioRead:
    portfolio = await _get_portfolio(db, portfolio_id)
    existing = {p.id for p in portfolio.properties}
    added = await _load_properties(db, [pid for pid in body.property_ids if pid not in existing])
    for prop in added:
        portfolio.properties.append(prop)
    await db.commit()
    await _initialize_interests(db, portfolio.id, added)
    return await _portfolio_read(db, await _get_portfolio(db, portfolio_id))


@router.delete("/portfolios/{portfolio_id}/properties/{property_id}", response_model=PortfolioRead)
async def remove_portfolio_property(
    portfolio_id: str, property_id: str, db: AsyncSession = Depends(get_session)
) -> PortfolioRead:
    portfolio = await _get_portfolio(db, portfolio_id)
    portfolio.properties = [p for p in portfolio.properties if p.id != property_id]
    await db.commit()
    return await _portfolio_read(db, await _get_portfolio(db, portfolio_id))


@router.put(
    "/portfolios/{portfolio_id}/properties/{property_id}/interest",
    response_model=PortfolioRead,
)
async def update_portfolio_interest(
    portfolio_id: str,
    property_id: str,
    body: PortfolioInterestUpdate,
    db: AsyncSession = Depends(get_session),
) -> PortfolioRead:
    portfolio = await _get_portfolio(db, portfolio_id)
    if property_id not in {prop.id for prop in portfolio.properties}:
        raise HTTPException(status_code=404, detail="Property is not in portfolio")
    if body.effective_from and body.effective_to and body.effective_to < body.effective_from:
        raise HTTPException(
            status_code=422, detail="effective_to must be on or after effective_from"
        )
    await db.execute(
        update(portfolio_properties)
        .where(
            portfolio_properties.c.portfolio_id == portfolio_id,
            portfolio_properties.c.property_id == property_id,
        )
        .values(**body.model_dump())
    )
    await db.commit()
    return await _portfolio_read(db, await _get_portfolio(db, portfolio_id))


# =========================================================================
# Assumption profiles
# =========================================================================


@router.post(
    "/assumption-profiles",
    response_model=AssumptionProfileRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_assumption_profile(
    body: AssumptionProfileCreate, db: AsyncSession = Depends(get_session)
) -> AssumptionProfileRead:
    if body.portfolio_id:
        await _get_portfolio(db, body.portfolio_id)
    profile = AssumptionProfile(
        name=body.name,
        portfolio_id=body.portfolio_id,
        property_type=body.property_type.value if body.property_type else None,
        market=body.market,
        values_json=_values_json(body.values),
        ranges_json=_ranges_json(body.ranges),
        comment=body.comment,
        cbsa_code=body.cbsa_code,
        state=body.state,
        quality_score=body.quality_score,
        as_of=body.as_of,
        source=body.source,
    )
    await _check_unique_scope(db, profile)
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return _profile_read(profile)


@router.get("/assumption-profiles", response_model=list[AssumptionProfileRead])
async def list_assumption_profiles(
    portfolio_id: str | None = None,
    include_house: bool = True,
    db: AsyncSession = Depends(get_session),
) -> list[AssumptionProfileRead]:
    stmt = select(AssumptionProfile)
    if portfolio_id is not None:
        cond = AssumptionProfile.portfolio_id == portfolio_id
        if include_house:
            cond = cond | AssumptionProfile.portfolio_id.is_(None)
        stmt = stmt.where(cond)
    rows = (await db.execute(stmt.order_by(AssumptionProfile.name))).scalars().all()
    return [_profile_read(p) for p in rows]


@router.get("/assumption-settings", response_model=AssumptionSettingsRead)
async def get_assumption_settings(db: AsyncSession = Depends(get_session)) -> AssumptionSettingsRead:
    from src.services.portfolio_service import library_directions

    directions = await library_directions(db)
    from src.engine.assumption_overrides import RESERVES_BY_BASIS

    # The per-SF / per-unit reserves position with capital_reserves_per_unit's direction
    return AssumptionSettingsRead(directions={
        f: directions.get(f, "none") for f in AssumptionValues.model_fields if f not in RESERVES_BY_BASIS
    })


@router.put("/assumption-settings", response_model=AssumptionSettingsRead)
async def update_assumption_settings(
    body: AssumptionSettingsUpdate, db: AsyncSession = Depends(get_session)
) -> AssumptionSettingsRead:
    """Which end of each field's range a quality-5 property takes. Applies to every profile."""
    from src.models.portfolio import AssumptionSettings

    settings = await db.get(AssumptionSettings, 1) or AssumptionSettings(id=1)
    current = json.loads(settings.directions_json or "{}")
    settings.directions_json = json.dumps({**current, **body.directions})
    db.add(settings)
    await db.commit()
    return await get_assumption_settings(db)


@router.get("/assumption-profiles/template.xlsx")
async def assumption_profiles_template(include_existing: bool = False, db: AsyncSession = Depends(get_session)) -> Response:
    """Workbook for building the library in Excel; import it on the Import page. With
    include_existing, house-wide profiles are filled in so they can be edited and re-imported."""
    from src.services.assumption_template import build_template
    from src.services.portfolio_service import library_directions

    rows = []
    if include_existing:
        stmt = select(AssumptionProfile).where(AssumptionProfile.portfolio_id.is_(None)).order_by(AssumptionProfile.name)
        rows = [_profile_read(p) for p in (await db.execute(stmt)).scalars()]
    return Response(
        content=build_template(rows, await library_directions(db)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="assumptions-library-template.xlsx"'},
    )


@router.get("/assumption-profiles/{profile_id}", response_model=AssumptionProfileRead)
async def get_assumption_profile(
    profile_id: str, db: AsyncSession = Depends(get_session)
) -> AssumptionProfileRead:
    profile = await db.get(AssumptionProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Assumption profile not found")
    return _profile_read(profile)


@router.put("/assumption-profiles/{profile_id}", response_model=AssumptionProfileRead)
async def update_assumption_profile(
    profile_id: str, body: AssumptionProfileUpdate, db: AsyncSession = Depends(get_session)
) -> AssumptionProfileRead:
    profile = await db.get(AssumptionProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Assumption profile not found")
    data = body.model_dump(exclude_unset=True)
    if "values" in data:
        profile.values_json = _values_json(body.values) if body.values else "{}"
        data.pop("values")
    if "ranges" in data:
        profile.ranges_json = _ranges_json(body.ranges)
        data.pop("ranges")
    try:
        check_ranges(json.loads(profile.values_json or "{}"), json.loads(profile.ranges_json or "{}"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "property_type" in data:
        data["property_type"] = body.property_type.value if body.property_type else None
    reject_null_columns(AssumptionProfile, data)
    for k, v in data.items():
        setattr(profile, k, v)
    await _check_unique_scope(db, profile)
    await db.commit()
    await db.refresh(profile)
    return _profile_read(profile)


@router.delete("/assumption-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assumption_profile(
    profile_id: str, db: AsyncSession = Depends(get_session)
) -> None:
    profile = await db.get(AssumptionProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Assumption profile not found")
    await db.delete(profile)
    await db.commit()


@router.get(
    "/properties/{property_id}/resolved-assumptions", response_model=ResolvedAssumptionsRead
)
async def get_resolved_assumptions(
    property_id: str,
    portfolio_id: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> ResolvedAssumptionsRead:
    """Merged assumption values for a property, with the profile each field came from."""
    prop = await db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")
    from src.services import cbsa

    resolved = await PortfolioService(db).resolve_for_property(prop, portfolio_id)
    return ResolvedAssumptionsRead(
        property_id=prop.id,
        property_type=prop.property_type,
        market=prop.market,
        cbsa_code=prop.cbsa_code,
        cbsa_title=cbsa.title(prop.cbsa_code),
        quality_score=prop.quality_score,
        values=resolved.values,
        sources=resolved.sources,
        ranges={k: {"low": lo, "base": b, "high": hi} for k, (lo, b, hi) in resolved.ranges.items()},
    )


# =========================================================================
# Scenarios
# =========================================================================


@router.post(
    "/portfolios/{portfolio_id}/scenarios",
    response_model=PortfolioScenarioRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_scenario(
    portfolio_id: str, body: PortfolioScenarioCreate, db: AsyncSession = Depends(get_session)
) -> PortfolioScenarioRead:
    await _get_portfolio(db, portfolio_id)
    scenario = PortfolioScenario(
        portfolio_id=portfolio_id,
        name=body.name,
        description=body.description,
        probability_pct=float(body.probability_pct) if body.probability_pct is not None else None,
        overrides_json=_overrides_json(body.overrides),
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    return _scenario_read(scenario)


@router.get("/portfolios/{portfolio_id}/scenarios", response_model=list[PortfolioScenarioRead])
async def list_scenarios(
    portfolio_id: str, db: AsyncSession = Depends(get_session)
) -> list[PortfolioScenarioRead]:
    portfolio = await _get_portfolio(db, portfolio_id)
    return [_scenario_read(s) for s in portfolio.scenarios]


async def _get_scenario(db: AsyncSession, portfolio_id: str, scenario_id: str) -> PortfolioScenario:
    scenario = await db.get(PortfolioScenario, scenario_id)
    if scenario is None or scenario.portfolio_id != portfolio_id:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario


@router.put(
    "/portfolios/{portfolio_id}/scenarios/{scenario_id}", response_model=PortfolioScenarioRead
)
async def update_scenario(
    portfolio_id: str,
    scenario_id: str,
    body: PortfolioScenarioUpdate,
    db: AsyncSession = Depends(get_session),
) -> PortfolioScenarioRead:
    scenario = await _get_scenario(db, portfolio_id, scenario_id)
    data = body.model_dump(exclude_unset=True)
    if "overrides" in data:
        scenario.overrides_json = _overrides_json(body.overrides or [])
        data.pop("overrides")
    reject_null_columns(PortfolioScenario, data)
    for k, v in data.items():
        setattr(scenario, k, v)
    await db.commit()
    await db.refresh(scenario)
    return _scenario_read(scenario)


@router.delete(
    "/portfolios/{portfolio_id}/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_scenario(
    portfolio_id: str, scenario_id: str, db: AsyncSession = Depends(get_session)
) -> None:
    scenario = await _get_scenario(db, portfolio_id, scenario_id)
    await db.delete(scenario)
    await db.commit()


# =========================================================================
# Runs
# =========================================================================


@router.post(
    "/portfolios/{portfolio_id}/runs",
    response_model=PortfolioRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def run_portfolio(
    portfolio_id: str, body: PortfolioRunRequest, db: AsyncSession = Depends(get_session)
) -> PortfolioRunRead:
    """Value every property under the base case and each requested scenario."""
    service = PortfolioService(db)
    portfolio = await _get_portfolio(db, portfolio_id)
    if not body.include_base and not body.scenario_ids:
        raise HTTPException(
            status_code=400, detail="Nothing to run: include the base case or a scenario"
        )
    try:
        run = await service.run(portfolio, body.scenario_ids, body.include_base, body.name, as_of=body.as_of)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return service.run_to_read(run)


@router.get("/portfolios/{portfolio_id}/approved-dates")
async def approved_dates(portfolio_id: str, db: AsyncSession = Depends(get_session)) -> list[dict]:
    """Dates of value with approved valuations among the portfolio's properties, newest first,
    with how many properties have an approved valuation as of each."""
    portfolio = await _get_portfolio(db, portfolio_id)
    approved = await PortfolioService(db).approved_snapshots([p.id for p in portfolio.properties])
    dates = sorted({s.value_date for rows in approved.values() for _, s in rows}, reverse=True)
    return [
        {"value_date": d, "properties": sum(any(s.value_date <= d for _, s in rows) for rows in approved.values()),
         "of": len(portfolio.properties)}
        for d in dates
    ]


@router.get("/portfolios/{portfolio_id}/runs", response_model=list[PortfolioRunListItem])
async def list_portfolio_runs(
    portfolio_id: str, db: AsyncSession = Depends(get_session)
) -> list[PortfolioRunListItem]:
    await _get_portfolio(db, portfolio_id)
    rows = (
        (
            await db.execute(
                select(PortfolioRun)
                .where(PortfolioRun.portfolio_id == portfolio_id)
                .order_by(PortfolioRun.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        PortfolioRunListItem(
            id=r.id,
            portfolio_id=r.portfolio_id,
            name=r.name,
            as_of=r.as_of,
            created_at=r.created_at,
            scenario_names=[s["scenario_name"] for s in json.loads(r.results_json or "[]")],
        )
        for r in rows
    ]


@router.get("/portfolios/{portfolio_id}/runs/{run_id}", response_model=PortfolioRunRead)
async def get_portfolio_run(
    portfolio_id: str, run_id: str, db: AsyncSession = Depends(get_session)
) -> PortfolioRunRead:
    run = await db.get(PortfolioRun, run_id)
    if run is None or run.portfolio_id != portfolio_id:
        raise HTTPException(status_code=404, detail="Portfolio run not found")
    return PortfolioService.run_to_read(run)


@router.post(
    "/portfolios/{portfolio_id}/runs/{run_id}/allocation-sensitivity",
    response_model=AllocationSensitivityResult,
)
async def allocation_sensitivity(
    portfolio_id: str,
    run_id: str,
    body: AllocationSensitivityRequest,
    db: AsyncSession = Depends(get_session),
) -> AllocationSensitivityResult:
    run = await db.get(PortfolioRun, run_id)
    if run is None or run.portfolio_id != portfolio_id:
        raise HTTPException(status_code=404, detail="Portfolio run not found")
    scenarios = PortfolioService.run_to_read(run).scenarios
    scenario = next((item for item in scenarios if item.scenario_id == body.scenario_id), None)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found in portfolio run")
    try:
        return analyze_dispositions(scenario, body.dispositions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/portfolios/{portfolio_id}/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio_run(
    portfolio_id: str, run_id: str, db: AsyncSession = Depends(get_session)
) -> None:
    run = await db.get(PortfolioRun, run_id)
    if run is None or run.portfolio_id != portfolio_id:
        raise HTTPException(status_code=404, detail="Portfolio run not found")
    await db.delete(run)
    await db.commit()
