"""What-if repricing of the last completed run at another discount rate / exit cap."""
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from src.services.valuation_service import ValuationService
from tests.api.test_valuations_api import _setup_office_property

V = "/api/v1/valuations"
P = "/api/v1/properties"


async def _run_office(client: AsyncClient, **extra) -> dict:
    ids = await _setup_office_property(client)
    val = await client.post(f"{P}/{ids['property_id']}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065", **extra,
    })
    assert val.status_code == 201
    assert (await client.post(f"{V}/{val.json()['id']}/run")).status_code == 200
    return (await client.get(f"{V}/{val.json()['id']}")).json()


async def test_what_if_at_saved_rates_equals_stored_npv(client: AsyncClient):
    val = await _run_office(client)
    resp = await client.get(f"{V}/{val['id']}/reports/what-if")
    assert resp.status_code == 200
    body = resp.json()
    stored = Decimal(val["result_npv"]).quantize(Decimal("0.01"))
    assert Decimal(body["value"]).quantize(Decimal("0.01")) == stored
    assert Decimal(body["saved_value"]).quantize(Decimal("0.01")) == stored
    assert abs(Decimal(body["change_vs_saved"])) < Decimal("0.005")
    assert Decimal(body["discount_rate"]) == Decimal("0.08")
    assert Decimal(body["exit_cap_rate"]) == Decimal("0.065")
    assert Decimal(body["terminal_value"]) == Decimal(val["result_exit_value"]).quantize(Decimal("0.01"))
    assert body["value_per_area"] is not None and body["area_unit"] == "sf"
    assert body["irr"] is None  # no purchase price

    explicit = (await client.get(
        f"{V}/{val['id']}/reports/what-if", params={"discount_rate": "0.08", "exit_cap_rate": "0.065"},
    )).json()
    assert explicit["value"] == body["value"]


async def test_what_if_matches_sensitivity_cell(client: AsyncClient):
    val = await _run_office(client)
    sens = (await client.get(f"{V}/{val['id']}/reports/sensitivity")).json()
    point = (await client.get(f"{V}/{val['id']}/reports/what-if", params={
        "discount_rate": sens["discount_rates"][0], "exit_cap_rate": sens["exit_cap_rates"][4],
    })).json()
    assert Decimal(point["value"]) == Decimal(sens["values"][0][4]).quantize(Decimal("0.01"))


async def test_higher_discount_rate_lowers_value(client: AsyncClient):
    val = await _run_office(client)
    base = (await client.get(f"{V}/{val['id']}/reports/what-if")).json()
    higher = (await client.get(f"{V}/{val['id']}/reports/what-if", params={"discount_rate": "0.10"})).json()
    assert Decimal(higher["value"]) < Decimal(base["value"])
    assert Decimal(higher["change_vs_saved"]) < 0
    assert Decimal(higher["exit_cap_rate"]) == Decimal("0.065")
    wider_cap = (await client.get(f"{V}/{val['id']}/reports/what-if", params={"exit_cap_rate": "0.075"})).json()
    assert Decimal(wider_cap["value"]) < Decimal(base["value"])
    assert Decimal(wider_cap["terminal_value"]) < Decimal(base["terminal_value"])
    # Saved valuation is unchanged
    assert (await client.get(f"{V}/{val['id']}")).json()["result_npv"] == val["result_npv"]


async def test_irr_only_with_purchase_price(client: AsyncClient):
    val = await _run_office(client, purchase_price="4000000")
    body = (await client.get(f"{V}/{val['id']}/reports/what-if")).json()
    assert body["irr"] is not None


async def test_missing_run_returns_400_and_unknown_returns_404(client: AsyncClient):
    ids = await _setup_office_property(client)
    val = await client.post(f"{P}/{ids['property_id']}/valuations", json={
        "name": "Draft", "discount_rate": "0.08", "exit_cap_rate": "0.065",
    })
    resp = await client.get(f"{V}/{val.json()['id']}/reports/what-if")
    assert resp.status_code == 400
    assert "not been run" in resp.json()["detail"]
    assert (await client.get(f"{V}/does-not-exist/reports/what-if")).status_code == 404


async def test_out_of_range_rate_rejected(client: AsyncClient):
    val = await _run_office(client)
    resp = await client.get(f"{V}/{val['id']}/reports/what-if", params={"discount_rate": "0"})
    assert resp.status_code == 422


async def test_marina_returns_400(client: AsyncClient):
    prop = await client.post(P, json={
        "name": "Marina", "property_type": "marina", "total_area": "100", "area_unit": "unit",
        "analysis_start_date": "2026-01-01", "analysis_period_months": 120, "fiscal_year_end_month": 12,
    })
    assert prop.status_code == 201
    assumptions = {
        "slip_classes": [{
            "name": "Wet", "kind": "wet_slip", "length_class": "30-45 ft",
            "utility_service_level": "fifty_amp", "count": 10,
            "annual_contract_share": "0.60", "seasonal_contract_share": "0.20", "transient_share": "0.20",
            "annual_contract_rate": "7600", "seasonal_contract_rate": "4200", "transient_daily_rate": "58",
        }],
        "demand": {"monthly_seasonality": ["1"] * 12, "monthly_weather_shock_pct": ["0"] * 12},
        "operating_cost_lines": [{"name": "dock_labor", "annual_fixed": "0"}],
        "valuation": {"hold_years": "2", "initial_purchase_price": "10000000"},
    }
    val = await client.post(f"{P}/{prop.json()['id']}/valuations", json={
        "name": "Marina", "discount_rate": "0.09", "exit_cap_rate": "0.08",
        "marina_assumptions_json": json.dumps(assumptions),
    })
    assert val.status_code == 201
    assert (await client.post(f"{V}/{val.json()['id']}/run")).status_code == 200
    resp = await client.get(f"{V}/{val.json()['id']}/reports/what-if")
    assert resp.status_code == 400
    assert "marina" in resp.json()["detail"]


IRR_PLACES = Decimal("0.000001")


def _monthly_discounting(monkeypatch):
    """Monthly discounting is an engine setting with no API field; force it for every run."""
    original = ValuationService._to_valuation_params
    monkeypatch.setattr(
        ValuationService, "_to_valuation_params",
        lambda self, v, p: replace(original(self, v, p), discounting_convention="monthly"),
    )


@pytest.mark.parametrize("convention", [
    {"monthly": True},
    {"use_mid_year_convention": True},
    {"use_mid_year_convention": True, "terminal_timing": "mid_year"},
])
async def test_every_sensitivity_cell_equals_a_full_run(client: AsyncClient, monkeypatch, convention):
    """Each cell is the NPV a full run gives at that discount rate / exit cap: no flat shift."""
    convention = dict(convention)
    monthly = convention.pop("monthly", False)
    terms = {"exit_costs_pct": "0.02", "purchase_price": "4000000", "acquisition_costs_pct": "0.015",
             "exit_deduct_forward_capital": True, **convention}
    ids = await _setup_office_property(client)

    async def run(rate: str, cap: str) -> dict:
        created = await client.post(f"{P}/{ids['property_id']}/valuations", json={
            "name": f"{rate}/{cap}", "discount_rate": rate, "exit_cap_rate": cap, **terms,
        })
        assert created.status_code == 201
        assert (await client.post(f"{V}/{created.json()['id']}/run")).status_code == 200
        return (await client.get(f"{V}/{created.json()['id']}")).json()

    if monthly:
        annual = await run("0.08", "0.065")
        _monthly_discounting(monkeypatch)
    base = await run("0.08", "0.065")
    if monthly:
        assert base["result_npv"] != annual["result_npv"]
    sens = (await client.get(f"{V}/{base['id']}/reports/sensitivity", params={
        "steps": 1, "discount_step": "0.01", "exit_cap_step": "0.005",
    })).json()
    assert Decimal(sens["values"][1][1]) == Decimal(base["result_npv"])
    for i, rate in enumerate(sens["discount_rates"]):
        for j, cap in enumerate(sens["exit_cap_rates"]):
            full = await run(rate, cap)
            assert Decimal(sens["values"][i][j]) == Decimal(full["result_npv"]), (rate, cap)
            # The stored IRR is rounded to six places
            assert Decimal(sens["irr_by_exit_cap"][j]).quantize(IRR_PLACES) == Decimal(full["result_irr"]), cap
            point = (await client.get(f"{V}/{base['id']}/reports/what-if", params={
                "discount_rate": rate, "exit_cap_rate": cap,
            })).json()
            assert Decimal(point["value"]) == Decimal(full["result_npv"])
            assert Decimal(point["terminal_value"]) == Decimal(full["result_exit_value"])
            assert Decimal(point["change_vs_saved"]) == Decimal(full["result_npv"]) - Decimal(base["result_npv"])


async def test_monthly_what_if_at_saved_rates_is_unchanged(client: AsyncClient, monkeypatch):
    _monthly_discounting(monkeypatch)
    val = await _run_office(client, purchase_price="4000000")
    body = (await client.get(f"{V}/{val['id']}/reports/what-if")).json()
    assert Decimal(body["value"]) == Decimal(val["result_npv"])
    assert Decimal(body["change_vs_saved"]) == 0
    assert Decimal(body["terminal_value"]) == Decimal(val["result_exit_value"])
    assert Decimal(body["irr"]).quantize(IRR_PLACES) == Decimal(val["result_irr"])


@pytest.mark.parametrize("override, model_hold, expected", [
    (18, None, 2), (12, None, 1), (24, Decimal(5), 2), (None, Decimal(5), 5), (None, None, 3),
])
def test_hold_years_rounds_partial_years_up(override, model_hold, expected):
    valuation = SimpleNamespace(analysis_period_months_override=override)
    property_ = SimpleNamespace(analysis_period_months=30)
    assert ValuationService(None)._hold_years(valuation, property_, model_hold) == expected


async def test_repricing_refuses_after_inputs_change(client: AsyncClient):
    val = await _run_office(client)
    # A cosmetic edit keeps results current; a modeling input (property size) makes them stale
    await client.put(f"{P}/{val['property_id']}", json={"name": "Renamed"})
    assert (await client.get(f"{V}/{val['id']}/reports/what-if")).status_code == 200
    await client.put(f"{P}/{val['property_id']}", json={"total_area": "60000"})
    resp = await client.get(f"{V}/{val['id']}/reports/what-if")
    assert resp.status_code == 400 and "re-run" in resp.json()["detail"]
    assert (await client.get(f"{V}/{val['id']}/reports/sensitivity")).status_code == 400
    assert (await client.post(f"{V}/{val['id']}/run")).status_code == 200
    assert (await client.get(f"{V}/{val['id']}/reports/what-if")).status_code == 200


async def test_repricing_runs_the_engine_once_per_run(client: AsyncClient, monkeypatch):
    val = await _run_office(client)
    calls = []
    original = ValuationService.build_engine_inputs

    async def counting(self, *a, **kw):
        calls.append(1)
        return await original(self, *a, **kw)

    monkeypatch.setattr(ValuationService, "build_engine_inputs", counting)
    for rate in ("0.075", "0.08", "0.085"):
        assert (await client.get(f"{V}/{val['id']}/reports/what-if", params={"discount_rate": rate})).status_code == 200
    assert (await client.get(f"{V}/{val['id']}/reports/sensitivity")).status_code == 200
    assert len(calls) == 1


async def test_cached_run_gives_the_same_answer_twice(client: AsyncClient):
    val = await _run_office(client)
    params = {"discount_rate": "0.09", "exit_cap_rate": "0.07"}
    first = (await client.get(f"{V}/{val['id']}/reports/what-if", params=params)).json()
    await client.get(f"{V}/{val['id']}/reports/sensitivity")
    second = (await client.get(f"{V}/{val['id']}/reports/what-if", params=params)).json()
    assert first == second
