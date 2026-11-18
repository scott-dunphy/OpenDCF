"""Self storage valued from the property's operating model."""
import json
from decimal import Decimal

from httpx import AsyncClient

V = "/api/v1/valuations"
P = "/api/v1/properties"

MODEL = {
    "unit_types": [
        {"name": "10x10 CC", "sf_per_unit": 100, "climate_controlled": True, "count": 300, "occupied_units": 270,
         "in_place_rate": 150, "street_rate": 140},
        {"name": "10x20 drive-up", "sf_per_unit": 200, "access": "drive_up", "count": 200, "occupied_units": 180,
         "in_place_rate": 210, "street_rate": 200},
    ],
    "street_rate_growth_pct": "0.03",
    "churn": {"monthly_move_out_pct": "0.04"},
    "ecri": {"enabled": True, "first_after_months": 6, "interval_months": 12, "increase_pct": "0.08",
             "extra_move_out_pct": "0.05"},
    "concessions": {"first_month_discount_pct": "0.5"},
    "credit_loss_pct": "0.01",
    "ancillary_lines": [{"name": "Tenant protection", "basis": "per_occupied_unit_month", "amount": 12,
                         "participation_pct": "0.6"}],
}


async def _storage_property(client: AsyncClient, model=MODEL) -> dict:
    """A storage property whose model (unit mix and expenses) sits on a setup valuation
    (prop["model_valuation_id"]); valuations created afterwards copy it."""
    prop = (await client.post(P, json={
        "name": "Main Street Storage", "property_type": "self_storage", "total_area": "70000", "area_unit": "sf",
        "analysis_start_date": "2026-01-01",
    })).json()
    setup = await client.post(f"{P}/{prop['id']}/valuations", json={
        "name": "Setup", "discount_rate": "0.08", "exit_cap_rate": "0.065"})
    assert setup.status_code == 201, setup.text
    prop["model_valuation_id"] = vid = setup.json()["id"]
    if model is not None:
        r = await client.put(f"{V}/{vid}", json={"self_storage_assumptions_json": json.dumps(model)})
        assert r.status_code == 200, r.text
    for exp in (
        {"category": "payroll", "base_year_amount": "120000", "growth_rate_pct": "0.03"},
        {"category": "real_estate_taxes", "base_year_amount": "90000", "growth_rate_pct": "0.02"},
        {"category": "management_fee", "base_year_amount": "0", "growth_rate_pct": "0", "is_pct_of_egi": True,
         "pct_of_egi": "0.06"},
    ):
        assert (await client.post(f"{V}/{vid}/expenses", json=exp)).status_code == 201
    return prop


async def _valuation(client: AsyncClient, prop_id: str) -> dict:
    r = await client.post(f"{P}/{prop_id}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065",
    })
    assert r.status_code == 201
    return r.json()


async def test_invalid_model_is_rejected_with_the_reason(client: AsyncClient):
    prop = await _storage_property(client, model=None)
    bad = {**MODEL, "unit_types": [{**MODEL["unit_types"][0], "occupied_units": 400}]}
    r = await client.put(f"{V}/{prop['model_valuation_id']}", json={"self_storage_assumptions_json": json.dumps(bad)})
    assert r.status_code == 422
    assert "exceed the unit count" in r.text
    r = await client.put(f"{V}/{prop['model_valuation_id']}", json={"self_storage_assumptions_json": "{not json"})
    assert r.status_code == 422


async def test_runs_from_the_valuation_model_with_storage_detail(client: AsyncClient):
    prop = await _storage_property(client)
    readiness = (await client.get(f"{V}/{prop['model_valuation_id']}/readiness")).json()
    assert readiness["ready"] is True
    assert readiness["items"][0]["detail"] == "2 unit types, 500 units"

    val = await _valuation(client, prop["id"])
    run = await client.post(f"{V}/{val['id']}/run")
    assert run.status_code == 200, run.text
    body = run.json()
    y1 = body["annual_cash_flows"][0]
    assert Decimal(y1["gross_potential_rent"]) > 0
    assert Decimal(y1["net_operating_income"]) > 0
    assert y1["storage_detail"]["by_type"][0]["name"] == "10x10 CC"
    assert Decimal(body["key_metrics"]["npv"]) > 0

    # Persisted: the saved results carry the same detail
    full = (await client.get(f"{V}/{val['id']}/reports/full")).json()
    saved = full["annual_cash_flows"][0]["storage_detail"]
    assert saved["year"] == 1
    assert Decimal(saved["physical_occupancy_units"]) > Decimal("0.8")
    assert Decimal(saved["move_ins"]) > 0

    sensitivity = await client.get(f"{V}/{val['id']}/reports/sensitivity")
    assert sensitivity.status_code == 200
    what_if = (await client.get(f"{V}/{val['id']}/reports/what-if")).json()
    assert abs(Decimal(what_if["change_vs_saved"])) < Decimal("1")
    monthly = (await client.get(f"{V}/{val['id']}/reports/monthly-cash-flows")).json()
    assert len(monthly) == 120
    for report in ("full-export.xlsx", "investment-memo.pdf", "rent-roll", "key-metrics"):
        assert (await client.get(f"{V}/{val['id']}/reports/{report}")).status_code == 200, report


async def test_storage_without_a_model_still_uses_suites(client: AsyncClient):
    prop = await _storage_property(client, model=None)
    readiness = (await client.get(f"{V}/{prop['model_valuation_id']}/readiness")).json()
    assert readiness["ready"] is False
    assert {i["key"]: i["status"] for i in readiness["items"]}["space"] == "missing"


async def test_monte_carlo_is_refused_for_storage_models(client: AsyncClient):
    prop = await _storage_property(client)
    val = await _valuation(client, prop["id"])
    r = await client.post(f"{V}/{val['id']}/monte-carlo", json={"num_paths": 10})
    assert r.status_code == 422
    assert "not available for self storage" in r.json()["detail"]


async def test_what_if_chat_reprices_a_storage_valuation(client: AsyncClient, monkeypatch):
    from src.api import copilot as copilot_api

    prop = await _storage_property(client)
    val = await _valuation(client, prop["id"])
    assert (await client.post(f"{V}/{val['id']}/run")).status_code == 200
    monkeypatch.setattr(copilot_api, "ask_scenario", lambda message, history, context: {
        "scenario": "Exit cap 50 bps higher.",
        "changes": [{"entity_type": "valuation", "entity_id": val["id"], "field": "exit_cap_rate",
                     "operation": "add", "value": "0.005"}],
    })
    body = (await client.post(f"{V}/{val['id']}/what-if-chat", json={"message": "exit cap +50bps?"})).json()
    assert Decimal(body["result"]["value"]) < Decimal(body["base"]["value"])


async def test_portfolio_values_a_storage_property(client: AsyncClient):
    prop = await _storage_property(client)
    await _valuation(client, prop["id"])
    pf = (await client.post("/api/v1/portfolios", json={"name": "Storage", "property_ids": [prop["id"]]})).json()
    run = await client.post(f"/api/v1/portfolios/{pf['id']}/runs", json={})
    assert run.status_code == 201, run.text
    row = run.json()["scenarios"][0]["properties"][0]
    assert row["error"] is None and Decimal(row["value"]) > 0


async def test_duplicate_sizes_import_with_unique_names_and_run(client: AsyncClient):
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Storage Units"
    ws.append(["Unit Size", "Units", "Occupied Units", "Street Rate", "In-Place Rent", "Climate Controlled"])
    ws.append(["10x10", 100, 90, 140, 150, "Yes"])
    ws.append(["10x10", 60, 55, 120, 128, "No"])
    buf = io.BytesIO()
    wb.save(buf)
    files = {"file": ("storage.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    preview = await client.post("/api/v1/imports/preview", files=files, data={"analysis_start_date": "2026-01-01"})
    assert preview.status_code == 201, preview.text
    commit = await client.post(f"/api/v1/imports/{preview.json()['id']}/commit", json={})
    assert commit.status_code == 200, commit.text
    prop = (await client.get(f"{P}/{commit.json()['created_property_ids'][0]}")).json()
    imported = (await client.get(f"{P}/{prop['id']}/valuations")).json()
    assert len(imported) == 1
    model = json.loads(imported[0]["self_storage_assumptions_json"])
    assert [u["name"] for u in model["unit_types"]] == ["10x10", "10x10 (non-CC)"]
    assert prop["area_unit"] == "sf" and Decimal(prop["total_area"]) == 16000
    val = await _valuation(client, prop["id"])
    run = await client.post(f"{V}/{val['id']}/run")
    assert run.status_code == 200, run.text
    assert run.json()["annual_cash_flows"][0]["storage_detail"] is not None


async def test_rent_roll_converts_to_a_unit_mix(client: AsyncClient):
    prop = (await client.post(P, json={
        "name": "Old Storage", "property_type": "self_storage", "total_area": "150", "area_unit": "unit",
        "analysis_start_date": "2026-01-01",
    })).json()
    val = (await client.post(f"{P}/{prop['id']}/valuations", json={
        "name": "Old", "discount_rate": "0.08", "exit_cap_rate": "0.065",
    })).json()
    suite = (await client.post(f"{V}/{val['id']}/suites", json={
        "suite_name": "10x10", "area": "150", "space_type": "10x10",
    })).json()
    assert (await client.post(f"{V}/{val['id']}/market-profiles", json={
        "space_type": "10x10", "market_rent_per_unit": "120", "rent_growth_rate_pct": "0.03",
        "rent_payment_frequency": "monthly", "new_lease_term_months": 12, "renewal_probability": "0.7",
        "general_vacancy_pct": "0.1",
    })).status_code == 201
    assert (await client.post(f"/api/v1/suites/{suite['id']}/leases", json={
        "lease_type": "in_place", "lease_start_date": "2025-06-01", "lease_end_date": "2026-05-31",
        "base_rent_per_unit": "130", "rent_payment_frequency": "monthly", "escalation_type": "flat",
        "recovery_type": "none",
    })).status_code == 201

    # Old path, year 1: one in-place lease at $130 on all 150 units through May, less 10% vacancy
    old = (await client.post(f"{V}/{val['id']}/run")).json()["annual_cash_flows"][0]

    r = await client.post(f"{V}/{val['id']}/self-storage/convert-rent-roll")
    assert r.status_code == 200, r.text
    converted = (await client.get(f"{P}/{prop['id']}")).json()
    assert converted["area_unit"] == "sf" and Decimal(converted["total_area"]) == 15000
    model = json.loads(r.json()["self_storage_assumptions_json"])
    unit = model["unit_types"][0]
    assert unit["count"] == 150 and Decimal(unit["occupied_units"]) == Decimal("135")
    assert Decimal(unit["in_place_rate"]) == 130 and Decimal(unit["street_rate"]) == 120
    assert Decimal(model["churn"]["monthly_move_out_pct"]).quantize(Decimal("0.0001")) == Decimal("0.0250")
    assert (await client.post(f"{V}/{val['id']}/self-storage/convert-rent-roll")).status_code == 409

    # Unit mix with churn off: 135 occupied units at $130 all year
    model["churn"] = {"monthly_move_out_pct": "0"}
    assert (await client.put(f"{V}/{val['id']}", json={"self_storage_assumptions_json": json.dumps(model)})).status_code == 200
    new = (await client.post(f"{V}/{val['id']}/run")).json()
    y1 = new["annual_cash_flows"][0]
    assert Decimal(y1["gross_potential_rent"]) == Decimal(135 * 130 * 12)
    # The old path bills the same in-place rent before its lease rolls to market in June
    old_rent = Decimal(old["gross_potential_rent"]) + Decimal(old["general_vacancy_loss"])
    assert old_rent < Decimal(y1["gross_potential_rent"])  # old lease rolls to $120 market mid-year
    full = (await client.get(f"{V}/{val['id']}/reports/full")).json()
    assert full["rent_roll"] == [] and new["rent_roll"] == []
