"""
Collateral Monte Carlo runs: build a property's engine inputs, value every
simulated path with the full engine in worker processes, and store the
per-path results. Completed simulations are reused while the inputs hash
(engine inputs, scenario settings, paths, seed, horizon) is unchanged.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, fields, replace
from datetime import date
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.engine.collateral_mc import (
    IDX,
    EngineCase,
    PathResults,
    property_deviations,
    run_paths,
    run_paths_chunk,
)
from src.engine.growth import rate_for_year
from src.engine.loan_risk.params import DRIVERS, RiskParameters
from src.models.loan import CollateralSimulation
from src.models.property import Property
from src.models.valuation import Valuation
from src.services.valuation_service import ValuationService

# Settings that change the simulated collateral paths (loan-only settings do not)
SCENARIO_KEYS = (
    "num_paths", "seed", "driver_volatility", "driver_persistence", "driver_correlation", "global_share",
    "market_share", "cap_rate_type_share", "credit_loss_vacancy_sensitivity", "cap_rate_floor",
    "recession_probability", "recession_persistence", "recession_severity", "recession_shock",
    "rent_level_reversion",
)
INLINE_PATHS = 64          # small runs (tests, previews) skip the process pool
PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)

_pool: ProcessPoolExecutor | None = None


def _engine_fingerprint() -> str:
    """Hash of the engine source, so a code change (e.g. a bug fix) is never served old results."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).resolve().parents[1].joinpath("engine").rglob("*.py")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


ENGINE_FINGERPRINT = _engine_fingerprint()


def _executor() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=settings.mc_workers or os.cpu_count() or 1)
    return _pool


RATE_KEYS = ("index_curve", "treasury_curve", "index_curve_as_of")


def scenario_settings(params: RiskParameters) -> dict:
    d = params.to_dict()
    return {k: d[k] for k in SCENARIO_KEYS}


def inputs_hash(case: EngineCase, params: RiskParameters, include_monthly: bool) -> str:
    payload = (repr(case) + json.dumps(scenario_settings(params), sort_keys=True) + str(include_monthly)
               + ENGINE_FINGERPRINT)
    return hashlib.sha256(payload.encode()).hexdigest()


def pack(res: PathResults, base_monthly: np.ndarray | None) -> bytes:
    buf = io.BytesIO()
    arrays = {"npv": res.npv, "irr": res.irr, "exit_cap": res.exit_cap, "annual_noi": res.annual_noi}
    if res.monthly_noi is not None:
        arrays["monthly_noi"] = res.monthly_noi
    if base_monthly is not None:
        arrays["base_monthly_noi"] = base_monthly
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def unpack(blob: bytes) -> dict[str, np.ndarray]:
    with np.load(io.BytesIO(blob)) as data:
        return {k: data[k] for k in data.files}


def _pct(a: np.ndarray) -> dict[str, float]:
    a = a[~np.isnan(a)]
    if a.size == 0:
        return {}
    return {f"p{p}": float(v) for p, v in zip(PERCENTILES, np.percentile(a, PERCENTILES))}


def summarize(res: PathResults, devs: np.ndarray, base_npv: float, years: int) -> dict:
    """Distribution of value, IRR, NOI and exit cap, and how much each driver moves value."""
    npv = res.npv
    counts, edges = np.histogram(npv, bins=40)
    sensitivity = []
    hold = devs[:, 1:years + 1, :].mean(axis=1)          # average deviation over the hold, per path and driver
    for d in DRIVERS:
        x = hold[:, IDX[d]]
        if x.std() == 0 or npv.std() == 0:
            continue
        corr = float(np.corrcoef(x, npv)[0, 1])
        sensitivity.append({
            "driver": d,
            "correlation": corr,
            # Value change for a one standard deviation move in the driver's average deviation
            "value_per_std": float(corr * npv.std()),
            "std_of_average": float(x.std()),
        })
    sensitivity.sort(key=lambda s: -abs(s["value_per_std"]))
    noi = res.annual_noi
    irr = res.irr[~np.isnan(res.irr)]
    return {
        "paths": int(npv.size),
        "base_value": base_npv,
        "value": {"mean": float(npv.mean()), "std": float(npv.std()), **_pct(npv)},
        "prob_below_base": float((npv < base_npv).mean()),
        "prob_below_90pct_base": float((npv < 0.9 * base_npv).mean()),
        "histogram": {"edges": [float(e) for e in edges], "counts": [int(c) for c in counts]},
        "irr": ({"mean": float(irr.mean()), **_pct(irr)} if irr.size else None),
        "exit_cap": {"mean": float(res.exit_cap.mean()), **_pct(res.exit_cap)},
        "noi_by_year": [
            {"year": y + 1, "mean": float(noi[:, y].mean()),
             **{f"p{p}": float(v) for p, v in zip((5, 25, 50, 75, 95), np.percentile(noi[:, y], (5, 25, 50, 75, 95)))}}
            for y in range(noi.shape[1])
        ],
        "sensitivity": sensitivity,
    }


def _pct_text(x: float, digits: int = 2) -> str:
    return f"{x * 100:.{digits}f}%"


def _rate_text(rate, schedule, years: int, digits: int = 2) -> str:
    """Year-1 rate, and the final year's rate when a year-by-year schedule changes it."""
    first = float(rate_for_year(rate, schedule, 1))
    last = float(rate_for_year(rate, schedule, years))
    return _pct_text(first, digits) + (f" → {_pct_text(last, digits)} by yr {years}" if last != first else "")


def _by_space_type(case: EngineCase, text) -> str:
    """One value when every market profile agrees, otherwise one per space type."""
    values = {key: text(m) for key, m in sorted(case.market.items())}
    distinct = set(values.values())
    if len(distinct) == 1:
        return distinct.pop()
    return " · ".join(f"{key} {v}" for key, v in values.items())


def base_assumptions(case: EngineCase, params: RiskParameters) -> dict[str, str]:
    """The property's base-case value for each driver, as the simulation's deviations apply to it."""
    n = case.years
    growing = [e for e in case.expenses if not e.is_pct_of_egi]
    total = sum(float(e.base_amount) for e in growing)
    expense_growth = (sum(float(e.base_amount) * float(rate_for_year(e.growth_rate, e.growth_schedule, 1))
                          for e in growing) / total) if total else None
    as_of = f"FRED {params.index_curve_as_of}" if params.index_curve_as_of else "placeholder curve, not live"
    curve_start = lambda curve: f"{_pct_text(sorted(curve)[0][1])} ({as_of})" if curve else "—"   # noqa: E731
    return {
        "rent_growth": _by_space_type(case, lambda m: _rate_text(m.rent_growth_rate, m.rent_growth_schedule, n)),
        "vacancy": _by_space_type(case, lambda m: _rate_text(m.general_vacancy_pct, m.general_vacancy_schedule, n)
                                  + f", credit loss {_pct_text(float(m.credit_loss_pct))}"),
        "renewal": _by_space_type(case, lambda m: _rate_text(m.renewal_probability, m.renewal_probability_schedule,
                                                             n, 0)),
        "downtime": _by_space_type(case, lambda m: f"{m.downtime_months} months"),
        "concessions": _by_space_type(case, lambda m: f"new ${float(m.new_ti_per_sf):,.2f}/SF TI, "
                                      f"{m.new_free_rent_months} mo free; renewal ${float(m.renewal_ti_per_sf):,.2f}"
                                      f"/SF, {m.renewal_free_rent_months} mo"),
        "inflation": (f"expenses {_pct_text(expense_growth)} (weighted), " if expense_growth is not None else "")
                     + f"CPI {_rate_text(case.cpi_assumption, case.cpi_schedule, n)}",
        "cap_rate": f"exit {_pct_text(float(case.params.exit_cap_rate))}",
        "sofr": curve_start(params.index_curve),
        "treasury_10y": curve_start(params.treasury_curve),
    }


PATH_PERCENTILES = (1, 5, 25, 50, 75, 95, 99)


def percentile_paths(npv: np.ndarray) -> list[dict]:
    """The path at each value percentile (paths ranked by value)."""
    order = np.argsort(npv, kind="stable")
    out = []
    for p in PATH_PERCENTILES:
        i = int(order[int(round(p / 100 * (npv.size - 1)))])
        out.append({"percentile": p, "index": i, "npv": float(npv[i])})
    return out


def path_assumptions(case: EngineCase, pc: EngineCase, dev: np.ndarray, recession: np.ndarray,
                     params: RiskParameters) -> dict:
    """What one path assumed, year by year, next to the base case (pc = path_case(case, dev))."""
    n = case.years
    growing = [e for e in pc.expenses if not e.is_pct_of_egi]
    total = sum(float(e.base_amount) for e in growing)

    def expense_growth(c: EngineCase, y: int) -> float | None:
        items = [e for e in c.expenses if not e.is_pct_of_egi]
        return (sum(float(e.base_amount) * float(rate_for_year(e.growth_rate, e.growth_schedule, y)) for e in items)
                / total) if total else None

    sofr = _curve_at(params.index_curve, n)
    ust = _curve_at(params.treasury_curve, n)
    years = []
    for y in range(1, n + 1):
        row = {"year": y, "recession": bool(recession[y - 1]), "space_types": {},
               "expense_growth": expense_growth(pc, y), "base_expense_growth": expense_growth(case, y),
               "cpi": float(rate_for_year(pc.cpi_assumption, pc.cpi_schedule, y)),
               "base_cpi": float(rate_for_year(case.cpi_assumption, case.cpi_schedule, y)),
               # Rates at the start of the year, as the loan simulation applies them
               "sofr": max(0.0, sofr[y - 1] + float(dev[y - 1, IDX["sofr"]])), "base_sofr": sofr[y - 1],
               "treasury_10y": max(0.0, ust[y - 1] + float(dev[y - 1, IDX["treasury_10y"]])),
               "base_treasury_10y": ust[y - 1]}
        for key, m in pc.market.items():
            b = case.market[key]
            row["space_types"][key] = {
                "rent_growth": float(rate_for_year(m.rent_growth_rate, m.rent_growth_schedule, y)),
                "base_rent_growth": float(rate_for_year(b.rent_growth_rate, b.rent_growth_schedule, y)),
                "vacancy": float(rate_for_year(m.general_vacancy_pct, m.general_vacancy_schedule, y)),
                "base_vacancy": float(rate_for_year(b.general_vacancy_pct, b.general_vacancy_schedule, y)),
                "credit_loss": float(rate_for_year(m.credit_loss_pct, m.credit_loss_schedule, y)),
                "renewal": float(rate_for_year(m.renewal_probability, m.renewal_probability_schedule, y)),
                "base_renewal": float(rate_for_year(b.renewal_probability, b.renewal_probability_schedule, y)),
                "downtime": int(rate_for_year(m.downtime_months, m.downtime_schedule, y)),
                "base_downtime": int(rate_for_year(b.downtime_months, b.downtime_schedule, y)),
            }
        years.append(row)
    return {
        "years": years,
        "concessions": {key: {"new_ti_per_sf": float(m.new_ti_per_sf), "new_free_rent_months": m.new_free_rent_months,
                              "renewal_ti_per_sf": float(m.renewal_ti_per_sf),
                              "renewal_free_rent_months": m.renewal_free_rent_months,
                              "base_new_ti_per_sf": float(case.market[key].new_ti_per_sf),
                              "base_new_free_rent_months": case.market[key].new_free_rent_months}
                        for key, m in pc.market.items()},
        "exit_cap_rate": float(pc.params.exit_cap_rate),
        "base_exit_cap_rate": float(case.params.exit_cap_rate),
    }


def _curve_at(points: list[list[float]], years: int) -> list[float]:
    """Curve rate at the start of each analysis year."""
    pts = sorted(points)
    return [float(np.interp(y, [p[0] for p in pts], [p[1] for p in pts])) for y in range(years)]


@dataclass
class SimulationOutcome:
    simulation: CollateralSimulation
    arrays: dict[str, np.ndarray]


class CollateralSimulationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def case_for(
        self, valuation: Valuation, prop: Property, start: date | None = None, horizon_months: int | None = None,
        unlevered: bool = False,
    ) -> EngineCase:
        """Engine inputs for a valuation, optionally restarted at `start` over `horizon_months`, without financing."""
        inputs = await ValuationService(self.db).build_engine_inputs(valuation, prop)
        if getattr(inputs, "storage_model", None) is not None:
            raise ValueError("Monte Carlo is not available for self storage operating models yet")
        case = EngineCase(**{f.name: getattr(inputs, f.name) for f in fields(EngineCase)})
        if start is not None:
            case = replace(case, analysis_start=start)
        if horizon_months is not None:
            case = replace(case, analysis_period_months=horizon_months)
        if unlevered:
            case = replace(case, params=replace(case.params, loan_amount=None, interest_rate=None, additional_loans=(), purchase_price=None))
        return case

    async def find(self, digest: str) -> CollateralSimulation | None:
        return (await self.db.execute(
            select(CollateralSimulation).where(
                CollateralSimulation.inputs_hash == digest, CollateralSimulation.status == "completed"
            ).order_by(CollateralSimulation.created_at.desc()).limit(1)
        )).scalar_one_or_none()

    def new_simulation(
        self, prop: Property, valuation: Valuation, case: EngineCase, params: RiskParameters, purpose: str,
        include_monthly: bool, parameter_set_id: str | None = None, parameter_set_version: int | None = None,
    ) -> CollateralSimulation:
        sim = CollateralSimulation(
            property_id=prop.id, valuation_id=valuation.id, purpose=purpose, analysis_start=case.analysis_start,
            horizon_months=case.analysis_period_months, num_paths=params.num_paths, seed=params.seed,
            parameter_set_id=parameter_set_id, parameter_set_version=parameter_set_version,
            # Scenario settings, plus the rate curves in effect (shown with the results; not part of the
            # cache key because they do not change property values)
            params_json=json.dumps({**scenario_settings(params), **{k: getattr(params, k) for k in RATE_KEYS}}),
            inputs_hash=inputs_hash(case, params, include_monthly), status="queued",
        )
        self.db.add(sim)
        return sim

    async def run(
        self, sim: CollateralSimulation, prop: Property, case: EngineCase, params: RiskParameters,
        include_monthly: bool, on_progress=None,
    ) -> dict[str, np.ndarray]:
        """Value every path and store the results on `sim`."""
        sim.status = "running"
        await self.db.commit()
        try:
            devs = property_deviations(params, prop.id, prop.property_type, prop.market)
            base = await asyncio.to_thread(case.run, include_monthly)
            base_monthly = (np.array([float(cf.net_operating_income) for cf in base.monthly_cash_flows],
                                     dtype=np.float64) if include_monthly else None)
            res = await self._run_paths(case, devs, params, include_monthly, sim, on_progress)
            sim.summary_json = json.dumps({**summarize(res, devs, float(base.npv), case.years),
                                           "base_assumptions": base_assumptions(case, params)})
            sim.paths_blob = pack(res, base_monthly)
            sim.status = "completed"
            sim.progress = 1
            await self.db.commit()
            return unpack(sim.paths_blob)
        except Exception as exc:  # noqa: BLE001 - recorded on the simulation
            sim.status = "failed"
            sim.error_message = str(exc)
            await self.db.commit()
            raise

    async def _run_paths(self, case, devs, params, include_monthly, sim, on_progress) -> PathResults:
        n = devs.shape[0]
        if n <= INLINE_PATHS:
            return await asyncio.to_thread(run_paths, case, devs, params, include_monthly)
        pool = _executor()
        workers = pool._max_workers
        size = max(5, n // (workers * 4))
        chunks = [(i, devs[i:i + size]) for i in range(0, n, size)]
        loop = asyncio.get_running_loop()
        futures = [
            loop.run_in_executor(pool, run_paths_chunk, case, chunk, params.to_dict(), include_monthly)
            for _, chunk in chunks
        ]
        done = 0
        for next_done in asyncio.as_completed(futures):
            done += len((await next_done).npv)
            sim.progress = round(done / n, 4)
            await self.db.commit()
            if on_progress:
                await on_progress(done / n)
        ordered = [f.result() for f in futures]   # submission order = path order
        return PathResults(
            npv=np.concatenate([r.npv for r in ordered]),
            irr=np.concatenate([r.irr for r in ordered]),
            exit_cap=np.concatenate([r.exit_cap for r in ordered]),
            annual_noi=np.concatenate([r.annual_noi for r in ordered]),
            monthly_noi=np.concatenate([r.monthly_noi for r in ordered]) if include_monthly else None,
        )

    async def get_or_run(
        self, prop: Property, valuation: Valuation, case: EngineCase, params: RiskParameters, purpose: str,
        include_monthly: bool, on_progress=None, **set_info,
    ) -> SimulationOutcome:
        existing = await self.find(inputs_hash(case, params, include_monthly))
        if existing is not None:
            return SimulationOutcome(existing, unpack(existing.paths_blob))
        sim = self.new_simulation(prop, valuation, case, params, purpose, include_monthly, **set_info)
        await self.db.commit()
        arrays = await self.run(sim, prop, case, params, include_monthly, on_progress)
        return SimulationOutcome(sim, arrays)
