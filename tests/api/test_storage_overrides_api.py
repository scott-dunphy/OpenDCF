"""Portfolio overrides and what-if chat on self storage properties valued from a unit mix."""
import json
from decimal import Decimal

from httpx import AsyncClient

from src.api import copilot as copilot_api
from tests.api.test_self_storage_api import MODEL, _storage_property, _valuation

V = "/api/v1/valuations"
P = "/api/v1/properties"


async def _run_portfolio(client: AsyncClient, overrides: list[dict]) -> tuple[dict, dict]:
    prop = await _storage_property(client)
    await _valuation(client, prop["id"])
    pf = (await client.post("/api/v1/portfolios", json={"name": "Storage", "property_ids": [prop["id"]]})).json()
    scen = (await client.post(f"/api/v1/portfolios/{pf['id']}/scenarios",
                              json={"name": "Test", "overrides": overrides})).json()
    run = await client.post(f"/api/v1/portfolios/{pf['id']}/runs", json={"scenario_ids": [scen["id"]]})
    assert run.status_code == 201, run.text
    base, scenario = (s["properties"][0] for s in run.json()["scenarios"])
    return base, scenario


async def test_rent_growth_shift_changes_a_storage_value(client: AsyncClient):
    base, scenario = await _run_portfolio(client, [{"mode": "shift", "values": {"market_rent_growth": "0.02"}}])
    assert base["error"] is None and scenario["error"] is None
    assert Decimal(scenario["value"]) > Decimal(base["value"])
    assert scenario["warnings"] == [] and base["warnings"] == []


async def test_occupancy_shift_past_full_is_capped(client: AsyncClient):
    base, scenario = await _run_portfolio(client, [
        {"mode": "shift", "values": {"stabilized_occupancy_pct": "0.5"}},
    ])
    assert scenario["error"] is None
    assert Decimal(scenario["value"]) > Decimal(base["value"])


async def test_rent_level_reaches_storage_and_general_vacancy_only_warns(client: AsyncClient):
    base, scenario = await _run_portfolio(client, [{"mode": "set", "values": {"market_rent_change_pct": "-0.1"}}])
    assert Decimal(scenario["value"]) < Decimal(base["value"])
    # General vacancy is written for leased buildings: storage occupancy moves only with stabilized occupancy
    base, scenario = await _run_portfolio(client, [{"mode": "set", "values": {"general_vacancy_pct": "0.25"}}])
    assert Decimal(scenario["value"]) == Decimal(base["value"])
    assert scenario["warnings"] == ["Not applied to this self storage unit mix: general_vacancy_pct"]


async def test_lease_only_override_warns_on_storage(client: AsyncClient):
    base, scenario = await _run_portfolio(client, [{"mode": "set", "values": {"renewal_probability": "0.4"}}])
    assert scenario["error"] is None
    assert scenario["warnings"] == ["Not applied to this self storage unit mix: renewal_probability"]
    assert base["warnings"] == []
    assert Decimal(scenario["value"]) == Decimal(base["value"])


async def test_what_if_chat_changes_storage_street_rate_without_saving(client: AsyncClient, monkeypatch):
    prop = await _storage_property(client)
    val = await _valuation(client, prop["id"])
    assert (await client.post(f"{V}/{val['id']}/run")).status_code == 200
    seen = {}

    def fake(message, history, context):
        seen["context"] = context
        return {"scenario": "Street rates 10% higher.", "changes": [
            {"entity_type": "storage_unit_type", "entity_id": u["name"], "field": "street_rate",
             "operation": "multiply", "value": "1.1"}
            for u in context["storage_model"][0]["unit_types"]
        ] + [{"entity_type": "storage_model", "entity_id": val["id"], "field": "churn.monthly_move_out_pct",
              "operation": "add", "value": "0.01"}]}

    monkeypatch.setattr(copilot_api, "ask_scenario", fake)
    r = await client.post(f"{V}/{val['id']}/what-if-chat", json={"message": "street rates +10%?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "lease" not in seen["context"] and "market_leasing_profile" not in seen["context"]
    first = body["changes"][0]
    assert first["label"] == "Unit type 10x10 CC"
    assert Decimal(first["old_value"]) == 140 and Decimal(first["new_value"]) == Decimal("154")
    assert Decimal(body["changes"][-1]["new_value"]) == Decimal("0.05")
    assert Decimal(body["base"]["value"]) != Decimal(body["result"]["value"])

    # Street rates alone raise the value
    monkeypatch.setattr(copilot_api, "ask_scenario", lambda message, history, context: {
        "scenario": "Street rates 10% higher.", "changes": [
            {"entity_type": "storage_unit_type", "entity_id": u["name"], "field": "street_rate",
             "operation": "multiply", "value": "1.1"} for u in MODEL["unit_types"]]})
    body = (await client.post(f"{V}/{val['id']}/what-if-chat", json={"message": "street rates +10%?"})).json()
    assert Decimal(body["result"]["value"]) > Decimal(body["base"]["value"])

    stored = json.loads((await client.get(f"{V}/{val['id']}")).json()["self_storage_assumptions_json"])
    assert stored["unit_types"][0]["street_rate"] == MODEL["unit_types"][0]["street_rate"]
    assert Decimal(stored["churn"]["monthly_move_out_pct"]) == Decimal("0.04")
    assert (await client.get(f"{V}/{val['id']}")).json()["status"] == "completed"


async def test_what_if_chat_rejects_a_market_change_on_storage(client: AsyncClient, monkeypatch):
    prop = await _storage_property(client)
    val = await _valuation(client, prop["id"])
    monkeypatch.setattr(copilot_api, "ask_scenario", lambda message, history, context: {
        "scenario": "Market rent up.",
        "changes": [{"entity_type": "market_leasing_profile", "entity_id": "x", "field": "market_rent_per_unit",
                     "operation": "multiply", "value": "1.1"}],
    })
    r = await client.post(f"{V}/{val['id']}/what-if-chat", json={"message": "market rent +10%?"})
    assert r.status_code == 422
    assert "valued from its unit mix" in r.json()["detail"]


async def test_management_fee_reaches_storage(client: AsyncClient):
    base, scenario = await _run_portfolio(client, [{"mode": "set", "values": {"management_fee_pct": "0.09"}}])  # fixture fee is 6%
    assert scenario["error"] is None and scenario["warnings"] == []
    assert Decimal(scenario["value"]) < Decimal(base["value"])
