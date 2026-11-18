"""
Live rate curves from FRED (St. Louis Fed) for the Monte Carlo parameters.

FRED has spot SOFR and the Treasury constant-maturity par curve but no SOFR
futures, so forward rates are implied from the Treasury curve (par yields
used as zero rates, a close approximation for the purpose):

- SOFR forward at t = 3-month Treasury forward at t + (SOFR today - 3-month bill today)
- 10-year Treasury at t = 10-year forward Treasury rate starting at t
"""
from __future__ import annotations

import logging
import time
from datetime import date

import httpx

from src.config import settings

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
TREASURY_SERIES = {
    1 / 12: "DGS1MO", 0.25: "DGS3MO", 0.5: "DGS6MO", 1: "DGS1", 2: "DGS2", 3: "DGS3", 5: "DGS5", 7: "DGS7",
    10: "DGS10", 20: "DGS20", 30: "DGS30",
}
CURVE_YEARS = (0, 0.5, 1, 2, 3, 4, 5, 7, 10, 15, 20, 30)


async def _latest(client: httpx.AsyncClient, series: str) -> tuple[date, float]:
    res = await client.get(FRED_URL, params={
        "series_id": series, "api_key": settings.fred_api_key, "file_type": "json", "sort_order": "desc",
        "limit": 10,
    })
    res.raise_for_status()
    for obs in res.json()["observations"]:
        if obs["value"] not in (".", ""):           # FRED marks holidays with "."
            return date.fromisoformat(obs["date"]), float(obs["value"]) / 100
    raise ValueError(f"No recent observation for {series}")


def _zero(curve: dict[float, float], t: float) -> float:
    """Linear interpolation of the par curve, flat beyond its ends."""
    pts = sorted(curve.items())
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, y0), (t1, y1) in zip(pts, pts[1:]):
        if t <= t1:
            return y0 + (y1 - y0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def _forward(curve: dict[float, float], start: float, length: float) -> float:
    return (_zero(curve, start + length) * (start + length) - _zero(curve, start) * start) / length


def build_curves(sofr: float, treasury: dict[float, float]) -> dict[str, list[list[float]]]:
    """index_curve (SOFR forwards) and treasury_curve (10-year forward yields) as [[years, rate], ...]."""
    basis = sofr - _forward(treasury, 0, 0.25)
    index = [[t, round(_forward(treasury, t, 0.25) + basis, 5)] for t in CURVE_YEARS]
    ten = [[t, round(_forward(treasury, t, 10), 5)] for t in CURVE_YEARS if t <= 20]
    return {"index_curve": index, "treasury_curve": ten}


async def fetch_curves() -> dict:
    if not settings.fred_api_key:
        raise ValueError("Set FRED_API_KEY in .env to load live rates")
    async with httpx.AsyncClient(timeout=20) as client:
        sofr_date, sofr = await _latest(client, "SOFR")
        treasury, dates = {}, [sofr_date]
        for years, series in TREASURY_SERIES.items():
            d, y = await _latest(client, series)
            treasury[years], dates = y, dates + [d]
    return {
        **build_curves(sofr, treasury),
        "as_of": max(dates).isoformat(),
        "sofr": sofr,
        "treasury_par_curve": [[t, y] for t, y in sorted(treasury.items())],
        "source": "FRED: SOFR and Treasury constant maturities (DGS1MO-DGS30)",
    }


_CACHE: dict = {}
CACHE_SECONDS = 6 * 3600

log = logging.getLogger(__name__)


async def with_live_rates(params: dict) -> dict:
    """
    Parameters with today's SOFR forward and 10-year Treasury curves from FRED, so each run
    snapshots the rates it used. Unchanged when the set turns live rates off, no FRED key is
    configured or FRED cannot be reached (the set's saved curves are used).
    """
    if not params.get("use_live_rates", True) or not settings.fred_api_key:
        return params
    if _CACHE.get("at", 0) < time.time() - CACHE_SECONDS:
        try:
            _CACHE.update(curves=await fetch_curves(), at=time.time())
        except Exception as exc:  # noqa: BLE001 - fall back to the saved curves
            log.warning("FRED rates unavailable, using the parameter set's curves: %s", exc)
            return params
    c = _CACHE["curves"]
    return {**params, "index_curve": c["index_curve"], "treasury_curve": c["treasury_curve"],
            "index_curve_as_of": c["as_of"]}
