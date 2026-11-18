"""What-if chat: the engine prices an AI-described scenario on a temporary copy of the model."""
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import func, select

from src.api import copilot as copilot_api
from src.models.audit import AuditLog
from tests.api.test_what_if_api import _run_office

V = "/api/v1/valuations"
P = "/api/v1/properties"


def _fake_scenario(monkeypatch, build):
    seen = {}

    def fake(message, history, context):
        seen["history"] = history
        return build(context)

    monkeypatch.setattr(copilot_api, "ask_scenario", fake)
    return seen


async def _snapshot(client: AsyncClient, val: dict) -> dict:
    profiles = (await client.get(f"{V}/{val['id']}/market-profiles")).json()
    prop = (await client.get(f"{P}/{val['property_id']}")).json()
    return {
        "valuation": (await client.get(f"{V}/{val['id']}")).json(),
        "profiles": profiles,
        "inputs_updated_at": prop.get("inputs_updated_at"),
    }


async def _audit_rows(test_engine) -> int:
    async with test_engine.connect() as conn:
        return (await conn.execute(select(func.count()).select_from(AuditLog))).scalar_one()


async def test_market_rent_up_raises_value_and_saves_nothing(client: AsyncClient, test_engine, monkeypatch):
    val = await _run_office(client)
    before = await _snapshot(client, val)
    audits = await _audit_rows(test_engine)
    _fake_scenario(monkeypatch, lambda ctx: {
        "scenario": "Market rent 10% higher.",
        "changes": [
            {"entity_type": "market_leasing_profile", "entity_id": p["id"], "field": "market_rent_per_unit",
             "operation": "multiply", "value": 1.1}
            for p in ctx["market_leasing_profile"]
        ],
    })

    resp = await client.post(f"{V}/{val['id']}/what-if-chat", json={"message": "What if market rent is 10% higher?"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scenario"] == "Market rent 10% higher."
    change = body["changes"][0]
    assert Decimal(change["old_value"]) == Decimal("35")
    assert Decimal(change["new_value"]) == Decimal("38.5")
    assert change["label"] == "office market leasing"
    assert Decimal(body["base"]["value"]).quantize(Decimal("0.01")) == Decimal(val["result_npv"]).quantize(Decimal("0.01"))
    assert Decimal(body["result"]["value"]) > Decimal(body["base"]["value"])

    after = await _snapshot(client, val)
    assert after == before
    assert after["valuation"]["status"] == "completed"
    assert await _audit_rows(test_engine) == audits


async def test_lower_renewal_probability_lowers_value(client: AsyncClient, monkeypatch):
    val = await _run_office(client)
    seen = _fake_scenario(monkeypatch, lambda ctx: {
        "scenario": "Renewal probability 30%.",
        "changes": [
            {"entity_type": "market_leasing_profile", "entity_id": p["id"], "field": "renewal_probability",
             "operation": "set", "value": 0.3}
            for p in ctx["market_leasing_profile"]
        ],
    })
    resp = await client.post(f"{V}/{val['id']}/what-if-chat", json={
        "message": "And if renewal probability drops to 30%?", "history": ["What if market rent is 10% higher?"],
    })
    body = resp.json()
    assert Decimal(body["result"]["value"]) < Decimal(body["base"]["value"])
    assert seen["history"] == ["What if market rent is 10% higher?"]
    profile = (await client.get(f"{V}/{val['id']}/market-profiles")).json()[0]
    assert Decimal(profile["renewal_probability"]) == Decimal("0.65")


async def test_unclear_question_returns_clarification_without_running(client: AsyncClient, monkeypatch):
    val = await _run_office(client)
    _fake_scenario(monkeypatch, lambda ctx: {"scenario": "Which tenant do you mean?", "changes": []})
    body = (await client.post(f"{V}/{val['id']}/what-if-chat", json={"message": "What if they leave?"})).json()
    assert body == {"scenario": "Which tenant do you mean?", "changes": [], "base": None, "result": None}


async def test_invalid_change_is_rejected(client: AsyncClient, monkeypatch):
    val = await _run_office(client)
    _fake_scenario(monkeypatch, lambda ctx: {"scenario": "x", "changes": [
        {"entity_type": "valuation", "entity_id": val["id"], "field": "status", "operation": "set", "value": "draft"},
    ]})
    resp = await client.post(f"{V}/{val['id']}/what-if-chat", json={"message": "x"})
    assert resp.status_code == 422
    assert "may not change valuation.status" in resp.json()["detail"]


async def test_unusable_ai_numbers_are_rejected_not_crashed(client: AsyncClient, monkeypatch):
    val = await _run_office(client)
    for op in (
        {"entity_type": "valuation", "entity_id": val["id"], "field": "discount_rate", "operation": "multiply", "value": "10%"},
        {"entity_type": "valuation", "entity_id": val["id"], "field": "discount_rate", "operation": "set", "value": "high"},
    ):
        _fake_scenario(monkeypatch, lambda ctx, op=op: {"scenario": "x", "changes": [op]})
        resp = await client.post(f"{V}/{val['id']}/what-if-chat", json={"message": "x"})
        assert resp.status_code == 422, resp.text
        assert "is not a number" in resp.json()["detail"]


async def test_dates_can_be_set_but_not_adjusted(client: AsyncClient, monkeypatch):
    val = await _run_office(client)
    leases = lambda ctx: ctx["lease"]
    _fake_scenario(monkeypatch, lambda ctx: {"scenario": "x", "changes": [
        {"entity_type": "lease", "entity_id": leases(ctx)[0]["id"], "field": "lease_end_date", "operation": "add", "value": 12},
    ]})
    resp = await client.post(f"{V}/{val['id']}/what-if-chat", json={"message": "x"})
    assert resp.status_code == 422
    assert "can only be set" in resp.json()["detail"]


async def test_storage_change_on_an_office_property_is_rejected(client: AsyncClient, monkeypatch):
    val = await _run_office(client)
    _fake_scenario(monkeypatch, lambda context: {
        "scenario": "Street rates up 10%.",
        "changes": [{"entity_type": "storage_model", "entity_id": val["property_id"],
                     "field": "street_rate_growth_pct", "operation": "set", "value": "0.05"}],
    })
    resp = await client.post(f"{V}/{val['id']}/what-if-chat", json={"message": "street rates?"})
    assert resp.status_code == 422, resp.text
