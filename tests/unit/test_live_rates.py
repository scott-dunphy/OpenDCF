"""Runs snapshot today's FRED curves unless the parameter set turns live rates off."""
import pytest

from src.config import settings
from src.services import rate_curves

LIVE = {"index_curve": [[0, 0.039], [30, 0.041]], "treasury_curve": [[0, 0.0496], [30, 0.05]], "as_of": "2026-10-22"}


@pytest.fixture
def fred(monkeypatch):
    calls = []

    async def fake():
        calls.append(1)
        return LIVE
    monkeypatch.setattr(settings, "fred_api_key", "test")
    monkeypatch.setattr(rate_curves, "fetch_curves", fake)
    monkeypatch.setattr(rate_curves, "_CACHE", {})
    return calls


async def test_live_curves_replace_saved_ones_and_are_cached(fred):
    saved = {"index_curve": [[0, 0.04]], "treasury_curve": [[0, 0.0425]], "num_paths": 10}
    out = await rate_curves.with_live_rates(saved)
    assert out["index_curve"] == LIVE["index_curve"] and out["treasury_curve"] == LIVE["treasury_curve"]
    assert out["index_curve_as_of"] == "2026-10-22" and out["num_paths"] == 10
    await rate_curves.with_live_rates(saved)
    assert len(fred) == 1


async def test_saved_curves_kept_when_off_or_unavailable(fred, monkeypatch):
    saved = {"index_curve": [[0, 0.04]], "use_live_rates": False}
    assert await rate_curves.with_live_rates(saved) == saved

    async def down():
        raise RuntimeError("FRED down")
    monkeypatch.setattr(rate_curves, "fetch_curves", down)
    assert await rate_curves.with_live_rates({"index_curve": [[0, 0.04]]}) == {"index_curve": [[0, 0.04]]}
