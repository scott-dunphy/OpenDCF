import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.engine.loan_risk.params import RiskParameters
from src.engine.loan_risk.ratings import (
    MOODYS_IDEALIZED_EL_PCT,
    MOODYS_IDEALIZED_PD_PCT,
    NAIC_CM_FACTORS,
)
from src.engine.loan_risk.schedule import weighted_average_life_years
from src.models.audit import AuditLog, RiskParameterSetVersion
from src.models.loan import LoanRiskRun, MortgageLoan, RiskParameterSet
from src.models.property import Property
from src.models.valuation import Valuation
from src.schemas.loan import (
    AuditLogRead,
    LoanRiskRunCreate,
    LoanRiskRunListItem,
    LoanRiskRunRead,
    LoanScheduleRead,
    LoanScheduleRow,
    MortgageLoanCreate,
    MortgageLoanRead,
    MortgageLoanUpdate,
    RiskParameterSetCreate,
    RiskParameterSetRead,
    RiskParameterSetUpdate,
    RiskParameterSetVersionRead,
)
from src.services.loan_risk_service import LoanRiskService, loan_position, record_version
from src.services.rate_curves import fetch_curves, with_live_rates

router = APIRouter(prefix="/api/v1", tags=["loans"])


# --- Loans ---------------------------------------------------------------------------

async def _get_loan(db: AsyncSession, loan_id: str) -> MortgageLoan:
    loan = await db.get(MortgageLoan, loan_id)
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    return loan


async def _require_property(db: AsyncSession, property_id: str) -> None:
    if await db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found")


@router.post("/loans", response_model=MortgageLoanRead, status_code=status.HTTP_201_CREATED)
async def create_loan(body: MortgageLoanCreate, db: AsyncSession = Depends(get_session)) -> MortgageLoan:
    await _require_property(db, body.property_id)
    loan = MortgageLoan(**body.model_dump())
    db.add(loan)
    await db.commit()
    await db.refresh(loan)
    return loan


@router.get("/loans", response_model=list[MortgageLoanRead])
async def list_loans(
    property_id: str | None = None,
    portfolio_id: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> list[MortgageLoan]:
    if portfolio_id:
        return await LoanRiskService(db).load_loans(portfolio_id)
    stmt = select(MortgageLoan).order_by(MortgageLoan.external_id, MortgageLoan.created_at)
    if property_id:
        stmt = stmt.where(MortgageLoan.property_id == property_id)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/loans/{loan_id}", response_model=MortgageLoanRead)
async def get_loan(loan_id: str, db: AsyncSession = Depends(get_session)) -> MortgageLoan:
    return await _get_loan(db, loan_id)


@router.put("/loans/{loan_id}", response_model=MortgageLoanRead)
async def update_loan(
    loan_id: str, body: MortgageLoanUpdate, db: AsyncSession = Depends(get_session)
) -> MortgageLoan:
    loan = await _get_loan(db, loan_id)
    changes = body.model_dump(exclude_unset=True)
    merged = {**MortgageLoanRead.model_validate(loan).model_dump(), **changes}
    try:
        MortgageLoanCreate.model_validate(merged)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if "property_id" in changes:
        await _require_property(db, changes["property_id"])
    for k, v in changes.items():
        setattr(loan, k, v)
    await db.commit()
    await db.refresh(loan)
    return loan


@router.delete("/loans/{loan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_loan(loan_id: str, db: AsyncSession = Depends(get_session)) -> None:
    await db.delete(await _get_loan(db, loan_id))
    await db.commit()


@router.get("/loans/{loan_id}/schedule", response_model=LoanScheduleRead)
async def loan_schedule(
    loan_id: str,
    as_of_date: date = Query(default_factory=date.today),
    db: AsyncSession = Depends(get_session),
) -> LoanScheduleRead:
    """Contractual schedule built from origination and rolled forward to the as-of date."""
    loan = await _get_loan(db, loan_id)
    params = RiskParameters.from_dict(json.loads((await LoanRiskService(db).default_parameter_set()).params_json))
    index0 = sorted(params.index_curve)[0][1] if params.index_curve else 0
    pos = loan_position(loan, as_of_date, Decimal(str(index0)))
    return LoanScheduleRead(
        loan_id=loan.id,
        as_of_date=as_of_date,
        payments_made=pos.state.payments_made,
        scheduled_balance=pos.scheduled_balance,
        balance=pos.balance,
        balance_difference_pct=pos.balance_difference_pct,
        rate=pos.rate,
        remaining_term_months=pos.state.remaining_term_months,
        remaining_io_months=pos.state.remaining_io_months,
        remaining_amortization_months=pos.state.remaining_amortization_months,
        wal_years=weighted_average_life_years(pos.rows),
        warnings=pos.warnings,
        rows=[LoanScheduleRow(**r.__dict__) for r in pos.rows],
    )


@router.get("/loans/{loan_id}/history")
async def loan_history(loan_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """
    The loan in every completed risk run (oldest first), and the collateral's
    valuation history: model valuation results and tape values as they changed.
    """
    loan = await _get_loan(db, loan_id)
    runs = (await db.execute(
        select(LoanRiskRun).where(LoanRiskRun.status == "completed")
        .order_by(LoanRiskRun.as_of_date, LoanRiskRun.created_at)
    )).scalars().all()
    keys = (
        "balance", "rate", "collateral_source", "collateral_value", "noi_year1", "ltv", "dscr", "debt_yield",
        "naic_cm", "moodys_rating", "pd_cumulative", "pd_one_year", "lgd", "expected_loss",
        "expected_loss_amount", "fair_value", "fair_value_price", "wal_years", "error",
    )
    history = []
    for run in runs:
        results = json.loads(run.results_json or "{}")
        row = next((r for r in results.get("loans", []) if r["loan_id"] == loan_id), None)
        if row is None:
            continue
        collateral = json.loads(run.inputs_json).get("collateral", {}).get(loan.property_id, {}) \
            if run.inputs_json else {}
        history.append({
            "run_id": run.id, "run_name": run.name, "as_of_date": run.as_of_date, "run_created_at": run.created_at,
            "parameter_set_id": run.parameter_set_id, "parameter_set_version": run.parameter_set_version,
            **{k: row.get(k) for k in keys},
            "valuation_id": collateral.get("valuation_id"), "valuation_name": collateral.get("valuation_name"),
        })

    # Collateral value changes recorded in the audit log
    names = dict((await db.execute(
        select(Valuation.id, Valuation.name).where(Valuation.property_id == loan.property_id)
    )).all())
    entries = (await db.execute(
        select(AuditLog).where(
            AuditLog.property_id == loan.property_id,
            AuditLog.entity_type.in_(["valuations", "mortgage_loans"]),
            AuditLog.action != "delete",
        ).order_by(AuditLog.created_at)
    )).scalars().all()
    values = []
    last_value: dict[str, object] = {}  # editing a valuation clears its NPV until it is run again
    for e in entries:
        changes = json.loads(e.changes_json)
        field = "result_npv" if e.entity_type == "valuations" else "tape_value"
        if field not in changes or changes[field][1] is None:
            continue
        before, after = changes[field]
        if before is None:
            before = last_value.get(e.entity_id)
        last_value[e.entity_id] = after
        values.append({
            "changed_at": e.created_at, "source": "model" if field == "result_npv" else "tape",
            "valuation_id": e.entity_id if field == "result_npv" else None,
            "valuation_name": names.get(e.entity_id) if field == "result_npv" else None,
            "loan_id": e.entity_id if field == "tape_value" else None,
            "value": float(after), "previous_value": float(before) if before is not None else None,
        })
    return {"loan_id": loan_id, "property_id": loan.property_id, "runs": history, "collateral_values": values}


# --- Risk parameter sets ----------------------------------------------------------------

def _param_set_read(row: RiskParameterSet) -> RiskParameterSetRead:
    return RiskParameterSetRead(
        id=row.id, name=row.name, version=row.version, is_default=row.is_default, comment=row.comment,
        params=json.loads(row.params_json), created_at=row.created_at, updated_at=row.updated_at,
    )


async def _get_param_set(db: AsyncSession, set_id: str) -> RiskParameterSet:
    row = await db.get(RiskParameterSet, set_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Parameter set not found")
    return row


@router.get("/risk-parameter-sets/reference")
async def risk_reference() -> dict:
    """Engine defaults and the rating tables used for Moody's and NAIC mapping."""
    return {
        "defaults": RiskParameters().to_dict(),
        "moodys_idealized_el_pct": MOODYS_IDEALIZED_EL_PCT,
        "moodys_idealized_pd_pct": MOODYS_IDEALIZED_PD_PCT,
        "naic_cm_factors": NAIC_CM_FACTORS,
    }


@router.get("/risk-parameter-sets", response_model=list[RiskParameterSetRead])
async def list_param_sets(db: AsyncSession = Depends(get_session)) -> list[RiskParameterSetRead]:
    await LoanRiskService(db).default_parameter_set()
    rows = (await db.execute(select(RiskParameterSet).order_by(RiskParameterSet.created_at))).scalars().all()
    return [_param_set_read(r) for r in rows]


@router.post("/risk-parameter-sets", response_model=RiskParameterSetRead, status_code=status.HTTP_201_CREATED)
async def create_param_set(
    body: RiskParameterSetCreate, db: AsyncSession = Depends(get_session)
) -> RiskParameterSetRead:
    if body.is_default:
        await db.execute(update(RiskParameterSet).values(is_default=False))
    row = RiskParameterSet(name=body.name, comment=body.comment, is_default=body.is_default,
                           params_json=json.dumps(body.params), version=1)
    db.add(row)
    await db.flush()
    record_version(db, row)
    await db.commit()
    await db.refresh(row)
    return _param_set_read(row)


@router.get("/risk-parameter-sets/live-rates")
async def live_rate_curves() -> dict:
    """SOFR forward and 10-year Treasury curves implied from today's FRED data (not saved)."""
    try:
        return await fetch_curves()
    except Exception as exc:  # noqa: BLE001 - missing key or FRED unavailable
        raise HTTPException(status_code=502, detail=f"Could not load rates from FRED: {exc}")


@router.get("/risk-parameter-sets/{set_id}", response_model=RiskParameterSetRead)
async def get_param_set(set_id: str, db: AsyncSession = Depends(get_session)) -> RiskParameterSetRead:
    return _param_set_read(await _get_param_set(db, set_id))


@router.put("/risk-parameter-sets/{set_id}", response_model=RiskParameterSetRead)
async def update_param_set(
    set_id: str, body: RiskParameterSetUpdate, db: AsyncSession = Depends(get_session)
) -> RiskParameterSetRead:
    """Edits bump the version; past runs keep a snapshot of the parameters they used."""
    row = await _get_param_set(db, set_id)
    if body.name is not None:
        row.name = body.name
    if body.comment is not None:
        row.comment = body.comment
    if body.params is not None and json.loads(row.params_json) != body.params:
        row.params_json = json.dumps(body.params)
        row.version += 1
        record_version(db, row)
    await db.commit()
    await db.refresh(row)
    return _param_set_read(row)


@router.get("/risk-parameter-sets/{set_id}/versions", response_model=list[RiskParameterSetVersionRead])
async def list_param_set_versions(set_id: str, db: AsyncSession = Depends(get_session)) -> list[dict]:
    """Every saved version of the set, newest first."""
    await _get_param_set(db, set_id)
    rows = (await db.execute(
        select(RiskParameterSetVersion).where(RiskParameterSetVersion.parameter_set_id == set_id)
        .order_by(RiskParameterSetVersion.version.desc())
    )).scalars().all()
    return [{
        "version": r.version, "name": r.name, "comment": r.comment,
        "params": json.loads(r.params_json), "created_at": r.created_at,
    } for r in rows]


@router.post("/risk-parameter-sets/{set_id}/make-default", response_model=RiskParameterSetRead)
async def make_default_param_set(set_id: str, db: AsyncSession = Depends(get_session)) -> RiskParameterSetRead:
    row = await _get_param_set(db, set_id)
    await db.execute(update(RiskParameterSet).values(is_default=False))
    row.is_default = True
    await db.commit()
    await db.refresh(row)
    return _param_set_read(row)


@router.delete("/risk-parameter-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_param_set(set_id: str, db: AsyncSession = Depends(get_session)) -> None:
    row = await _get_param_set(db, set_id)
    if row.is_default:
        raise HTTPException(status_code=400, detail="Make another set the default before deleting this one")
    await db.delete(row)
    await db.commit()


# --- Runs ---------------------------------------------------------------------------

def _run_item(run: LoanRiskRun) -> dict:
    summary: dict = {}
    if run.results_json:
        res = json.loads(run.results_json)
        summary = {
            "loan_count": res.get("loan_count"),
            "total_balance": res["portfolio"]["total_balance"],
            "expected_loss": res["portfolio"]["expected_loss"],
        }
    return {
        "id": run.id, "name": run.name, "as_of_date": run.as_of_date, "portfolio_id": run.portfolio_id,
        "parameter_set_id": run.parameter_set_id, "parameter_set_version": run.parameter_set_version,
        "status": run.status, "progress": run.progress, "error_message": run.error_message,
        "created_at": run.created_at, **summary,
    }


async def _execute_run(run_id: str, session_factory) -> None:
    """Background task with its own DB session (the request's session is closed by then)."""
    gen = session_factory()
    session = await anext(gen)
    try:
        await LoanRiskService(session).execute(run_id)
    finally:
        await gen.aclose()


@router.post("/loan-risk-runs", response_model=LoanRiskRunListItem, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    body: LoanRiskRunCreate,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Queue a Monte Carlo run; poll GET /loan-risk-runs/{id} for status and results."""
    service = LoanRiskService(db)
    pset = await _get_param_set(db, body.parameter_set_id) if body.parameter_set_id \
        else await service.default_parameter_set()
    run = LoanRiskRun(
        name=body.name, as_of_date=body.as_of_date, portfolio_id=body.portfolio_id,
        parameter_set_id=pset.id, parameter_set_version=pset.version,
        params_json=json.dumps(await with_live_rates(json.loads(pset.params_json))),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    background.add_task(_execute_run, run.id, request.app.dependency_overrides.get(get_session, get_session))
    return _run_item(run)


@router.get("/loan-risk-runs", response_model=list[LoanRiskRunListItem])
async def list_runs(db: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await db.execute(select(LoanRiskRun).order_by(LoanRiskRun.created_at.desc()).limit(100))).scalars().all()
    return [_run_item(r) for r in rows]


@router.get("/loan-risk-runs/{run_id}", response_model=LoanRiskRunRead)
async def get_run(run_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    run = await db.get(LoanRiskRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        **_run_item(run),
        "params": json.loads(run.params_json),
        "results": json.loads(run.results_json) if run.results_json else None,
    }


@router.get("/loan-risk-runs/{run_id}/inputs")
async def get_run_inputs(run_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """Loan terms, collateral NOI paths and values exactly as the run used them."""
    run = await db.get(LoanRiskRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run.inputs_json:
        raise HTTPException(status_code=404, detail="This run has no recorded inputs")
    return {"run_id": run.id, "params": json.loads(run.params_json), **json.loads(run.inputs_json)}


@router.get("/audit-log", response_model=list[AuditLogRead])
async def audit_log(
    entity_type: str | None = None,
    entity_id: str | None = None,
    property_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Changes to inputs (properties, leases, valuations, loans, parameter sets, ...), newest first."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id).limit(limit)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if property_id:
        stmt = stmt.where(AuditLog.property_id == property_id)
    return [{
        "id": r.id, "entity_type": r.entity_type, "entity_id": r.entity_id, "property_id": r.property_id,
        "action": r.action, "changes": json.loads(r.changes_json), "source": r.source, "created_at": r.created_at,
    } for r in (await db.execute(stmt)).scalars().all()]


@router.delete("/loan-risk-runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: str, db: AsyncSession = Depends(get_session)) -> None:
    run = await db.get(LoanRiskRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await db.delete(run)
    await db.commit()
