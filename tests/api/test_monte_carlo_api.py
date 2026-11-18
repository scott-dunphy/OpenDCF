"""Collateral Monte Carlo on a valuation (full engine on every path)."""
import pytest
from httpx import AsyncClient

from src.engine.loan_risk.params import DRIVERS
from tests.api.test_valuations_api import _setup_office_property


async def _valuation(client: AsyncClient) -> str:
    ids = await _setup_office_property(client)
    val = await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065", "purchase_price": "8000000",
    })
    assert val.status_code == 201, val.text
    return val.json()["id"]


class TestMonteCarlo:
    async def test_distribution_reuse_and_zero_volatility(self, client: AsyncClient):
        vid = await _valuation(client)
        start = await client.post(f"/api/v1/valuations/{vid}/monte-carlo", json={"num_paths": 30})
        assert start.status_code == 202, start.text
        sim = (await client.get(f"/api/v1/collateral-simulations/{start.json()['id']}")).json()
        assert sim["status"] == "completed", sim["error_message"]
        s = sim["summary"]
        assert s["paths"] == 30
        assert s["value"]["p5"] < s["value"]["p50"] < s["value"]["p95"]
        assert s["irr"] is not None and len(s["noi_by_year"]) == 10
        assert {x["driver"] for x in s["sensitivity"]} <= set(DRIVERS) and s["sensitivity"]

        again = (await client.post(f"/api/v1/valuations/{vid}/monte-carlo", json={"num_paths": 30})).json()
        assert again["reused"] and again["id"] == sim["id"]

        # Editing the property's valuation inputs invalidates the cached simulation; without a
        # purchase price there is no IRR distribution (it would equal the discount rate)
        await client.put(f"/api/v1/valuations/{vid}", json={"exit_cap_rate": "0.07", "purchase_price": None})
        fresh = (await client.post(f"/api/v1/valuations/{vid}/monte-carlo", json={"num_paths": 30})).json()
        assert not fresh["reused"] and fresh["id"] != sim["id"]
        assert (await client.get(f"/api/v1/collateral-simulations/{fresh['id']}")).json()["summary"]["irr"] is None

        pset = (await client.post("/api/v1/risk-parameter-sets", json={
            "name": "No vol", "params": {"driver_volatility": {d: 0.0 for d in DRIVERS}, "recession_severity": 0.0},
        })).json()
        flat = (await client.post(f"/api/v1/valuations/{vid}/monte-carlo",
                                  json={"num_paths": 10, "parameter_set_id": pset["id"]})).json()
        s = (await client.get(f"/api/v1/collateral-simulations/{flat['id']}")).json()["summary"]
        assert abs(s["value"]["p1"] - s["base_value"]) < 0.01 and abs(s["value"]["p99"] - s["base_value"]) < 0.01
        run = (await client.post(f"/api/v1/valuations/{vid}/run")).json()
        assert abs(float(run["key_metrics"]["npv"]) - s["base_value"]) < 0.01

        listed = (await client.get(f"/api/v1/valuations/{vid}/monte-carlo")).json()
        assert len(listed) == 3

    async def test_simulation_list_and_detail(self, client: AsyncClient):
        vid = await _valuation(client)
        sim = (await client.post(f"/api/v1/valuations/{vid}/monte-carlo", json={"num_paths": 20})).json()
        val = (await client.get(f"/api/v1/valuations/{vid}")).json()

        listed = (await client.get("/api/v1/collateral-simulations")).json()
        assert [x["id"] for x in listed] == [sim["id"]]
        row = listed[0]
        assert row["valuation_name"] == "Base" and row["property_name"] and row["status"] == "completed"
        assert row["p5_value"] <= row["mean_value"] <= row["p95_value"] and row["base_value"] > 0
        assert "params" not in row and "summary" not in row

        assert len((await client.get(f"/api/v1/collateral-simulations?property_id={val['property_id']}")).json()) == 1
        assert (await client.get("/api/v1/collateral-simulations?property_id=nope")).json() == []
        assert (await client.get("/api/v1/collateral-simulations?purpose=loan_risk")).json() == []

        detail = (await client.get(f"/api/v1/collateral-simulations/{sim['id']}")).json()
        assert detail["property_name"] == row["property_name"] and detail["parameter_set_name"] == "Base case"
        assert detail["summary"]["value"]["mean"] == row["mean_value"]
        # Base case saved with the run: the valuation's exit cap and each driver's assumption
        base = detail["base_assumptions"]
        assert detail["base_assumptions_source"] == "snapshot" and set(base) == set(DRIVERS)
        assert base["cap_rate"] == "exit 6.50%" and base["downtime"].endswith("months")
        assert base == detail["summary"]["base_assumptions"]

        assert (await client.delete(f"/api/v1/collateral-simulations/{sim['id']}")).status_code == 204
        assert (await client.get("/api/v1/collateral-simulations")).json() == []

    async def test_drill_into_a_path(self, client: AsyncClient):
        vid = await _valuation(client)
        sim = (await client.post(f"/api/v1/valuations/{vid}/monte-carlo", json={"num_paths": 40})).json()
        paths = (await client.get(f"/api/v1/collateral-simulations/{sim['id']}/paths")).json()
        assert [p["percentile"] for p in paths] == [1, 5, 25, 50, 75, 95, 99]
        assert [p["npv"] for p in paths] == sorted(p["npv"] for p in paths)
        summary = (await client.get(f"/api/v1/collateral-simulations/{sim['id']}")).json()["summary"]
        # With 40 paths the 1st and 99th percentile paths are the lowest and highest
        assert paths[0]["npv"] <= summary["value"]["p1"] and paths[-1]["npv"] >= summary["value"]["p99"]

        low = paths[1]
        detail = (await client.get(f"/api/v1/collateral-simulations/{sim['id']}/paths/{low['index']}")).json()
        # Rebuilt from the seed and settings: the same value as the stored path
        assert detail["matches_simulation"] and detail["npv"] == pytest.approx(low["npv"], rel=1e-9)
        cfs = detail["annual_cash_flows"]
        assert len(cfs) == 10 and all("net_operating_income" in cf for cf in cfs)
        # Reversion: Year 11 NOI at the path's exit cap, less exit costs
        rev = detail["reversion"]
        assert rev["exit_cap_year"] == -1 and detail["forward_cash_flow"]["year"] == 11
        assert rev["noi_basis"] == pytest.approx(float(detail["forward_cash_flow"]["net_operating_income"]), rel=1e-9)
        assert rev["gross_value"] == pytest.approx(rev["noi_basis"] / rev["exit_cap_rate"], rel=1e-9)
        assert rev["net_value"] == pytest.approx(rev["gross_value"] - rev["exit_costs"] - rev["transfer_tax"]
                                                 - rev["capital_deduction"], rel=1e-9)
        a = detail["assumptions"]
        assert len(a["years"]) == 10 and a["base_exit_cap_rate"] == pytest.approx(0.065)
        year1 = a["years"][0]
        space = next(iter(year1["space_types"].values()))
        assert {"rent_growth", "base_rent_growth", "vacancy", "renewal", "downtime"} <= set(space)
        assert isinstance(year1["recession"], bool)

        # Editing the valuation after the run: the rebuilt path no longer matches
        await client.put(f"/api/v1/valuations/{vid}", json={"exit_cap_rate": "0.08"})
        stale = (await client.get(f"/api/v1/collateral-simulations/{sim['id']}/paths/{low['index']}")).json()
        assert not stale["matches_simulation"]
        assert (await client.get(f"/api/v1/collateral-simulations/{sim['id']}/paths/999")).status_code == 404


async def test_setup_failure_marks_simulation_failed(client: AsyncClient, monkeypatch):
    """A background run that fails before valuing paths is recorded as failed, not left queued."""
    from src.services.collateral_simulation_service import CollateralSimulationService
    vid = await _valuation(client)
    real, calls = CollateralSimulationService.case_for, []

    async def case_for(self, valuation, prop):
        calls.append(1)
        if len(calls) > 1:              # the background task's call
            raise RuntimeError("lease data changed")
        return await real(self, valuation, prop)

    monkeypatch.setattr(CollateralSimulationService, "case_for", case_for)
    start = await client.post(f"/api/v1/valuations/{vid}/monte-carlo", json={"num_paths": 10})
    sim = (await client.get(f"/api/v1/collateral-simulations/{start.json()['id']}")).json()
    assert sim["status"] == "failed"
    assert "lease data changed" in sim["error_message"]
