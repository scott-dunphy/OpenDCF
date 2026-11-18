import asyncio
import json
from dataclasses import replace

import numpy as np
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from src.db.session import get_session
from src.engine.collateral_mc import path_case, property_deviations, recession_years
from src.engine.loan_risk.params import RiskParameters
from src.models.loan import CollateralSimulation, RiskParameterSet
from src.models.property import Property
from src.models.valuation import Valuation
from src.services.collateral_simulation_service import (
    CollateralSimulationService,
    base_assumptions,
    inputs_hash,
    path_assumptions,
    percentile_paths,
    unpack,
)
from src.services.loan_risk_service import LoanRiskService
from src.services.rate_curves import with_live_rates
from src.services.valuation_service import ValuationService

router = APIRouter(prefix="/api/v1", tags=["monte-carlo"])


class MonteCarloCreate(BaseModel):
    num_paths: int = Field(default=5000, ge=10, le=20000)
    parameter_set_id: str | None = Field(default=None, description="Defaults to the default parameter set")


def _item(sim: CollateralSimulation, reused: bool = False) -> dict:
    return {
        "id": sim.id, "property_id": sim.property_id, "valuation_id": sim.valuation_id, "purpose": sim.purpose,
        "analysis_start": sim.analysis_start, "horizon_months": sim.horizon_months, "num_paths": sim.num_paths,
        "seed": sim.seed, "parameter_set_id": sim.parameter_set_id,
        "parameter_set_version": sim.parameter_set_version, "status": sim.status, "progress": float(sim.progress),
        "error_message": sim.error_message, "created_at": sim.created_at, "reused": reused,
    }


async def _valuation(db: AsyncSession, valuation_id: str) -> tuple[Valuation, Property]:
    valuation = await db.get(Valuation, valuation_id)
    if valuation is None:
        raise HTTPException(status_code=404, detail="Valuation not found")
    return valuation, await db.get(Property, valuation.property_id)


async def _execute(sim_id: str, session_factory) -> None:
    """Background task with its own session."""
    gen = session_factory()
    db = await anext(gen)
    try:
        sim = await db.get(CollateralSimulation, sim_id)
        try:
            valuation, prop = await _valuation(db, sim.valuation_id)
            service = CollateralSimulationService(db)
            params = RiskParameters.from_dict(json.loads(sim.params_json))
            case = await service.case_for(valuation, prop)
        except Exception as exc:  # noqa: BLE001 - record it rather than leave the run queued
            await db.rollback()
            sim = await db.get(CollateralSimulation, sim_id)
            sim.status = "failed"
            sim.error_message = str(getattr(exc, "detail", exc))
            await db.commit()
            return
        try:
            await service.run(sim, prop, case, params, include_monthly=False)
        except Exception:  # noqa: BLE001 - recorded on the simulation
            pass
    finally:
        await gen.aclose()


@router.post("/valuations/{valuation_id}/monte-carlo", status_code=status.HTTP_202_ACCEPTED)
async def start_monte_carlo(
    valuation_id: str, body: MonteCarloCreate, request: Request, background: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """
    Value the property on `num_paths` simulated paths with the full engine. A completed
    simulation with identical inputs and settings is returned instead of rerunning.
    """
    valuation, prop = await _valuation(db, valuation_id)
    if valuation.review_status != "draft":
        raise HTTPException(409, "Monte Carlo runs on the live model, which a frozen valuation no longer uses. "
                                 "Duplicate it to simulate.")
    if body.parameter_set_id:
        pset = await db.get(RiskParameterSet, body.parameter_set_id)
        if pset is None:
            raise HTTPException(status_code=404, detail="Parameter set not found")
    else:
        pset = await LoanRiskService(db).default_parameter_set()
    params = RiskParameters.from_dict(await with_live_rates({**json.loads(pset.params_json),
                                                             "num_paths": body.num_paths}))
    service = CollateralSimulationService(db)
    try:
        case = await service.case_for(valuation, prop)
    except Exception as exc:  # noqa: BLE001 - a property that cannot be modeled
        raise HTTPException(status_code=422, detail=f"Property cannot be valued: {exc}")
    existing = await service.find(inputs_hash(case, params, False))
    if existing is not None:
        return _item(existing, reused=True)
    sim = service.new_simulation(prop, valuation, case, params, "valuation", False,
                                 parameter_set_id=pset.id, parameter_set_version=pset.version)
    await db.commit()
    await db.refresh(sim)
    background.add_task(_execute, sim.id, request.app.dependency_overrides.get(get_session, get_session))
    return _item(sim)


@router.get("/valuations/{valuation_id}/monte-carlo")
async def list_monte_carlo(valuation_id: str, db: AsyncSession = Depends(get_session)) -> list[dict]:
    await _valuation(db, valuation_id)
    rows = (await db.execute(
        select(CollateralSimulation).where(CollateralSimulation.valuation_id == valuation_id)
        .order_by(CollateralSimulation.created_at.desc())
    )).scalars().all()
    return [_item(r) for r in rows]


def _headline(summary_json: str | None) -> dict:
    """Key results for the simulation list."""
    if not summary_json:
        return {}
    s = json.loads(summary_json)
    v = s["value"]
    return {"base_value": s["base_value"], "mean_value": v["mean"], "p5_value": v["p5"], "p95_value": v["p95"],
            "prob_below_base": s["prob_below_base"]}


@router.get("/collateral-simulations")
async def list_simulations(
    property_id: str | None = None, purpose: str | None = None, db: AsyncSession = Depends(get_session)
) -> list[dict]:
    """Every collateral simulation, newest first, with property and valuation names and key results."""
    q = (select(CollateralSimulation, Property.name, Valuation.name)
         .options(defer(CollateralSimulation.paths_blob), defer(CollateralSimulation.params_json))
         .join(Property, Property.id == CollateralSimulation.property_id)
         .outerjoin(Valuation, Valuation.id == CollateralSimulation.valuation_id)
         .order_by(CollateralSimulation.created_at.desc()))
    if property_id:
        q = q.where(CollateralSimulation.property_id == property_id)
    if purpose:
        q = q.where(CollateralSimulation.purpose == purpose)
    rows = (await db.execute(q)).all()
    return [{**_item(sim), "property_name": pname, "valuation_name": vname, **_headline(sim.summary_json)}
            for sim, pname, vname in rows]


@router.get("/collateral-simulations/{sim_id}")
async def get_simulation(sim_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    sim = await db.get(CollateralSimulation, sim_id, options=[defer(CollateralSimulation.paths_blob)])
    if sim is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    prop = await db.get(Property, sim.property_id)
    valuation = await db.get(Valuation, sim.valuation_id) if sim.valuation_id else None
    pset = await db.get(RiskParameterSet, sim.parameter_set_id) if sim.parameter_set_id else None
    params = json.loads(sim.params_json)
    summary = json.loads(sim.summary_json) if sim.summary_json else None
    # Simulations from before base assumptions were saved show the valuation's current inputs
    base, base_source = (summary or {}).get("base_assumptions"), "snapshot"
    if base is None and valuation is not None and prop is not None:
        try:
            case = await CollateralSimulationService(db).case_for(valuation, prop)
            base, base_source = base_assumptions(case, RiskParameters.from_dict(params)), "current"
            if "index_curve" not in params:          # rate curves were not saved with older runs
                base.update(sofr="not recorded for this run", treasury_10y="not recorded for this run")
        except Exception:  # noqa: BLE001 - a property that can no longer be modeled
            base = None
    return {
        **_item(sim),
        "property_name": prop.name if prop else None,
        "valuation_name": valuation.name if valuation else None,
        "parameter_set_name": pset.name if pset else None,
        "params": params,
        "summary": summary,
        "base_assumptions": base,
        "base_assumptions_source": base_source if base is not None else None,
    }


async def _completed(db: AsyncSession, sim_id: str) -> CollateralSimulation:
    sim = await db.get(CollateralSimulation, sim_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    if sim.status != "completed" or sim.paths_blob is None:
        raise HTTPException(status_code=409, detail="Simulation has not completed")
    return sim


@router.get("/collateral-simulations/{sim_id}/paths")
async def list_paths(sim_id: str, db: AsyncSession = Depends(get_session)) -> list[dict]:
    """The path at each value percentile, for drilling into its cash flows."""
    sim = await _completed(db, sim_id)
    arrays = unpack(sim.paths_blob)
    rows = percentile_paths(arrays["npv"])
    for r in rows:
        irr = float(arrays["irr"][r["index"]])
        r.update(irr=None if np.isnan(irr) else irr, exit_cap=float(arrays["exit_cap"][r["index"]]))
    return rows


@router.get("/collateral-simulations/{sim_id}/paths/{index}")
async def get_path(sim_id: str, index: int, db: AsyncSession = Depends(get_session)) -> dict:
    """
    One path's cash flows and assumptions. Paths are not stored: the path is rebuilt from the
    simulation's seed and settings and run through the engine again, then checked against the
    value saved for it.
    """
    sim = await _completed(db, sim_id)
    if not 0 <= index < sim.num_paths:
        raise HTTPException(status_code=404, detail="Path not found")
    valuation = await db.get(Valuation, sim.valuation_id) if sim.valuation_id else None
    prop = await db.get(Property, sim.property_id)
    if valuation is None or prop is None:
        raise HTTPException(status_code=409, detail="The valuation behind this simulation no longer exists")
    params = RiskParameters.from_dict(json.loads(sim.params_json))
    service = CollateralSimulationService(db)
    case = await service.case_for(valuation, prop, start=sim.analysis_start, horizon_months=sim.horizon_months,
                                  unlevered=sim.purpose == "loan_risk")
    dev = property_deviations(params, prop.id, prop.property_type, prop.market)[index]
    pc = path_case(case, dev, params)
    result = await asyncio.to_thread(pc.run)
    # The year after the hold, whose NOI is the reversion basis when the exit cap applies to it
    forward = await asyncio.to_thread(replace(pc, analysis_period_months=pc.analysis_period_months + 12).run)
    forward_cf = forward.annual_cash_flows[len(result.annual_cash_flows)] \
        if len(forward.annual_cash_flows) > len(result.annual_cash_flows) else None
    stored = float(unpack(sim.paths_blob)["npv"][index])
    vs = ValuationService(db)
    return {
        "index": index,
        "npv": float(result.npv),
        "stored_npv": stored,
        # False when the property's inputs changed after the simulation ran
        "matches_simulation": abs(float(result.npv) - stored) <= max(1.0, abs(stored) * 1e-6),
        "irr": float(result.irr) if result.irr is not None and case.params.purchase_price else None,
        "terminal_value": float(result.terminal_value),
        "terminal_noi_basis": float(result.terminal_noi_basis),
        "reversion": {
            "noi_basis": float(result.terminal_noi_basis),
            "exit_cap_rate": float(pc.params.exit_cap_rate),
            "exit_cap_year": pc.params.exit_cap_year,
            "gross_value": float(result.terminal_gross_value),
            "exit_costs": float(result.terminal_exit_costs_amount),
            "transfer_tax": float(result.terminal_transfer_tax_amount),
            "capital_deduction": float(result.terminal_capital_deduction_amount),
            "net_value": float(result.terminal_value),
            "pv": float(result.pv_terminal),
        },
        "annual_cash_flows": [vs._serialize_annual_cf(cf) for cf in result.annual_cash_flows],
        "forward_cash_flow": vs._serialize_annual_cf(forward_cf) if forward_cf is not None else None,
        "assumptions": path_assumptions(case, pc, dev, recession_years(params)[index], params),
    }


@router.delete("/collateral-simulations/{sim_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_simulation(sim_id: str, db: AsyncSession = Depends(get_session)) -> None:
    sim = await db.get(CollateralSimulation, sim_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    await db.delete(sim)
    await db.commit()
