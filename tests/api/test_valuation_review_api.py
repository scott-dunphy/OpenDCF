"""Valuation review lifecycle: submit freezes, approve, reopen, verify (docs/valuation-lifecycle-plan.md)."""
from httpx import AsyncClient

from tests.api.test_self_storage_api import _storage_property
from tests.api.test_self_storage_api import _valuation as _storage_valuation
from tests.api.test_valuations_api import _setup_office_property

V = "/api/v1/valuations"
REPORTS = ["full", "rent-roll", "key-metrics", "tenant-detail", "cash-flow-summary", "lease-expirations",
           "sensitivity", "monthly-cash-flows", "what-if?discount_rate=0.09"]


async def _office(client: AsyncClient) -> tuple[dict, str]:
    ids = await _setup_office_property(client)
    val = await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
        "name": "Q4 2026", "discount_rate": "0.08", "exit_cap_rate": "0.065"})
    assert val.status_code == 201, val.text
    return ids, val.json()["id"]


async def _submit(client: AsyncClient, val_id: str) -> dict:
    r = await client.post(f"{V}/{val_id}/submit", json={"name": "Analyst A", "note": "Q4 close"})
    assert r.status_code == 200, r.text
    return r.json()


async def _reports(client: AsyncClient, val_id: str) -> dict[str, bytes]:
    out = {}
    for name in REPORTS:
        r = await client.get(f"{V}/{val_id}/reports/{name}")
        assert r.status_code == 200, (name, r.text)
        out[name] = r.content
    return out


async def test_frozen_reports_do_not_change_when_the_live_model_does(client: AsyncClient):
    ids, val_id = await _office(client)
    body = await _submit(client, val_id)
    assert body["review_status"] == "in_review" and body["snapshot_id"]
    before = await _reports(client, val_id)

    # The frozen valuation's own model is locked
    lease = (await client.get(f"{V}/{val_id}/leases")).json()[0]
    assert (await client.put(f"/api/v1/leases/{lease['id']}", json={"base_rent_per_unit": "45.00"})).status_code == 409
    assert (await client.delete(f"/api/v1/leases/{lease['id']}")).status_code == 409
    assert (await client.post(f"{V}/{val_id}/expenses", json={
        "category": "insurance", "base_year_amount": "50000"})).status_code == 409
    suite = (await client.get(f"{V}/{val_id}/suites")).json()[0]
    assert (await client.put(f"{V}/{val_id}/suites/{suite['id']}", json={"area": "1"})).status_code == 409
    profile = (await client.get(f"{V}/{val_id}/market-profiles")).json()[0]
    assert (await client.put(f"{V}/{val_id}/market-profiles/{profile['id']}",
                             json={"market_rent_per_unit": "20.00"})).status_code == 409
    # Another valuation of the property has its own model and stays editable
    setup = ids["setup_valuation_id"]
    other = (await client.get(f"{V}/{setup}/leases")).json()[0]
    assert (await client.put(f"/api/v1/leases/{other['id']}", json={"base_rent_per_unit": "45.00"})).status_code == 200
    assert (await client.post(f"{V}/{setup}/expenses", json={
        "category": "insurance", "base_year_amount": "50000"})).status_code == 201

    assert await _reports(client, val_id) == before
    check = (await client.post(f"{V}/{val_id}/verify")).json()
    assert check["matches"] is True and check["error"] is None, check
    assert check["stored_npv"] == check["rerun_npv"]


async def test_frozen_valuation_is_locked(client: AsyncClient):
    ids, val_id = await _office(client)
    await _submit(client, val_id)
    assert (await client.put(f"{V}/{val_id}", json={"discount_rate": "0.09"})).status_code == 409
    assert (await client.put(f"{V}/{val_id}", json={"name": "Q4 2026 final"})).status_code == 200
    assert (await client.post(f"{V}/{val_id}/run")).status_code == 409
    assert (await client.delete(f"{V}/{val_id}")).status_code == 409
    assert (await client.delete(f"/api/v1/properties/{ids['property_id']}")).status_code == 409
    assert (await client.post(f"{V}/{val_id}/what-if-chat", json={"message": "rents -10%?"})).status_code == 409
    assert (await client.post(f"{V}/{val_id}/submit", json={"name": "A"})).status_code == 409
    copy = await client.post(f"{V}/{val_id}/duplicate")
    assert copy.status_code == 201 and copy.json()["review_status"] == "draft" and copy.json()["snapshot_id"] is None
    # The copy has its own editable model
    lease = (await client.get(f"{V}/{copy.json()['id']}/leases")).json()[0]
    assert (await client.put(f"/api/v1/leases/{lease['id']}", json={"base_rent_per_unit": "45.00"})).status_code == 200


async def test_approve_reopen_keeps_history(client: AsyncClient):
    _, val_id = await _office(client)
    assert (await client.post(f"{V}/{val_id}/approve", json={"name": "R"})).status_code == 409  # draft
    await _submit(client, val_id)
    approved = await client.post(f"{V}/{val_id}/approve", json={"name": "Reviewer B", "note": "Agreed"})
    assert approved.status_code == 200 and approved.json()["review_status"] == "approved"
    assert (await client.put(f"{V}/{val_id}", json={"exit_cap_rate": "0.07"})).status_code == 409

    assert (await client.post(f"{V}/{val_id}/reopen", json={"name": "Reviewer B"})).status_code == 422  # no reason
    reopened = await client.post(f"{V}/{val_id}/reopen", json={"name": "Reviewer B", "note": "Cap rate correction"})
    assert reopened.status_code == 200 and reopened.json()["review_status"] == "draft"
    assert (await client.put(f"{V}/{val_id}", json={"exit_cap_rate": "0.07"})).status_code == 200

    await _submit(client, val_id)
    history = (await client.get(f"{V}/{val_id}/snapshots")).json()
    assert [h["status"] for h in history] == ["in_review", "reopened"]
    old = history[1]
    assert (old["submitted_by"], old["approved_by"], old["approve_note"]) == ("Analyst A", "Reviewer B", "Agreed")
    assert (old["reopened_by"], old["reopen_reason"]) == ("Reviewer B", "Cap rate correction")
    assert history[0]["engine_version"]


async def test_storage_valuation_freezes_and_verifies(client: AsyncClient):
    prop = await _storage_property(client)
    val = await _storage_valuation(client, prop["id"])
    await _submit(client, val["id"])
    r = await client.put(f"{V}/{val['id']}", json={"self_storage_assumptions_json": None})
    assert r.status_code == 409
    check = (await client.post(f"{V}/{val['id']}/verify")).json()
    assert check["matches"] is True, check
    full = (await client.get(f"{V}/{val['id']}/reports/full")).json()
    assert float(full["key_metrics"]["npv"]) == float(check["stored_npv"])


def _cells(content: bytes) -> list:
    import io

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content))
    return [[c.value for c in row] for ws in wb.worksheets for row in ws.iter_rows()]


async def test_exports_describe_the_property_as_frozen(client: AsyncClient):
    ids, val_id = await _office(client)
    await _submit(client, val_id)
    exports = ["rent-roll.xlsx", "full-export.xlsx"]
    before = {e: _cells((await client.get(f"{V}/{val_id}/reports/{e}")).content) for e in exports}
    forecast = (await client.get(f"{V}/{val_id}/reports/ncreif-forecast")).content
    pid = ids["property_id"]
    # The property itself is shared by its valuations and can change
    assert (await client.put(f"/api/v1/properties/{pid}", json={
        "total_area": "99999", "analysis_start_date": "2027-01-01"})).status_code == 200
    for e in exports:
        assert _cells((await client.get(f"{V}/{val_id}/reports/{e}")).content) == before[e], e
    assert (await client.get(f"{V}/{val_id}/reports/ncreif-forecast")).content == forecast
    pdf = await client.get(f"{V}/{val_id}/reports/investment-memo.pdf")
    assert pdf.status_code == 200
    frozen = (await client.get(f"{V}/{val_id}/frozen-inputs")).json()
    assert float(frozen["property"]["total_area"]) != 99999 and frozen["market_profiles"] and frozen["expenses"]


async def test_live_model_tools_refuse_frozen_valuations(client: AsyncClient):
    _, val_id = await _office(client)
    await _submit(client, val_id)
    # The deal package exports the frozen model (test_valuation_packages_api)
    assert (await client.get(f"{V}/{val_id}/package")).status_code == 200
    assert (await client.post(f"{V}/{val_id}/monte-carlo", json={"num_paths": 10})).status_code == 409
    # The copilot permission is a setting, not a model input: allowed while frozen
    perm = await client.put(f"{V}/{val_id}/copilot-permission", json={"mode": "always_allow"})
    assert perm.status_code == 200, perm.text
    assert (await client.post(f"{V}/{val_id}/copilot", json={"message": "hi"})).status_code == 409


async def test_reopened_valuation_with_history_cannot_be_deleted(client: AsyncClient):
    ids, val_id = await _office(client)
    await _submit(client, val_id)
    await client.post(f"{V}/{val_id}/reopen", json={"name": "R", "note": "redo"})
    assert (await client.delete(f"{V}/{val_id}")).status_code == 409
    assert (await client.delete(f"/api/v1/properties/{ids['property_id']}")).status_code == 409
    assert len((await client.get(f"{V}/{val_id}/snapshots")).json()) == 1


async def test_marina_and_seniors_freeze_and_verify(client: AsyncClient):
    import json

    marina = (await client.post("/api/v1/properties", json={
        "name": "Marina", "property_type": "marina", "total_area": "100", "area_unit": "unit",
        "analysis_start_date": "2026-01-01", "analysis_period_months": 120, "fiscal_year_end_month": 12})).json()
    m_model = {
        "slip_classes": [{
            "name": "Wet", "kind": "wet_slip", "length_class": "30-45 ft", "utility_service_level": "fifty_amp",
            "count": 10, "annual_contract_share": "0.60", "seasonal_contract_share": "0.20",
            "transient_share": "0.20", "annual_contract_rate": "7600", "seasonal_contract_rate": "4200",
            "transient_daily_rate": "58"}],
        "demand": {"monthly_seasonality": ["1"] * 12, "monthly_weather_shock_pct": ["0"] * 12},
        "operating_cost_lines": [{"name": "dock_labor", "annual_fixed": "0"}],
        "valuation": {"hold_years": "2", "initial_purchase_price": "10000000"},
    }
    seniors = (await client.post("/api/v1/properties", json={
        "name": "Seniors", "property_type": "seniors_housing", "total_area": "100", "area_unit": "unit",
        "analysis_start_date": "2026-01-01", "analysis_period_months": 120, "fiscal_year_end_month": 12})).json()
    s_model = {
        "community_name": "Seniors",
        "unit_types": [{"name": "AL Studio", "acuity": "assisted_living", "unit_type": "studio", "count": 10,
                        "avg_sf": "300", "monthly_base_fee": "5000"}],
        "expenses": [{"name": "Payroll", "category": "labor", "annual_fixed": "100000"}],
        "valuation": {"hold_years": 4, "initial_purchase_price": "20000000"},
    }
    for prop, key, model in ((marina, "marina_assumptions_json", m_model),
                             (seniors, "seniors_housing_assumptions_json", s_model)):
        val = (await client.post(f"/api/v1/properties/{prop['id']}/valuations", json={
            "name": "Base", "discount_rate": "0.09", "exit_cap_rate": "0.08", key: json.dumps(model)})).json()
        await _submit(client, val["id"])
        check = (await client.post(f"{V}/{val['id']}/verify")).json()
        assert check["matches"] is True and check["stored_npv"] is not None, (prop["property_type"], check)

