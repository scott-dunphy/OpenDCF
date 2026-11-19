"""Per-lease recovery overrides: a modified gross category's own expense stop ($/SF/yr).

Setup CAM is $75,000 a year on 15,000 SF ($5/SF).
"""
from httpx import AsyncClient

from tests.api.test_market_recovery_structure_api import _total_recoveries, _valuation_and_profile
from tests.api.test_valuations_api import _setup_office_property

V = "/api/v1/valuations"


async def test_lease_override_stop_create_update_and_duplicate(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, _ = await _valuation_and_profile(client, ids)
    lease = next(l for l in (await client.get(f"{V}/{val}/leases")).json() if l["tenant_id"])
    nnn = await _total_recoveries(client, val)

    r = await client.post(f"/api/v1/leases/{lease['id']}/expense-recoveries", json={
        "expense_category": "cam", "recovery_type": "modified_gross", "expense_stop_per_sf": "2"})
    assert r.status_code == 201, r.text
    override = r.json()
    assert float(override["expense_stop_per_sf"]) == 2 and override["floor_per_sf_annual"] is None
    low_stop = await _total_recoveries(client, val)
    assert low_stop < nnn

    r = await client.patch("/api/v1/leases/expense-recoveries/bulk", json={"updates": [{
        "lease_id": lease["id"], "override_id": override["id"],
        "fields": {"expense_category": "cam", "recovery_type": "modified_gross", "expense_stop_per_sf": "4"}}]})
    assert r.status_code == 200 and r.json()["upserted_count"] == 1, r.text
    (stored,) = (await client.get(f"/api/v1/leases/{lease['id']}")).json()["expense_recovery_overrides"]
    assert float(stored["expense_stop_per_sf"]) == 4
    high_stop = await _total_recoveries(client, val)
    assert high_stop < low_stop  # higher stop, less recovered

    copy = (await client.post(f"{V}/{val}/duplicate")).json()["id"]
    copied_lease = next(l for l in (await client.get(f"{V}/{copy}/leases")).json() if l["tenant_id"])
    (copied,) = (await client.get(f"/api/v1/leases/{copied_lease['id']}")).json()["expense_recovery_overrides"]
    assert float(copied["expense_stop_per_sf"]) == 4
    assert await _total_recoveries(client, copy) == high_stop


async def test_negative_lease_override_stop_is_rejected(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, _ = await _valuation_and_profile(client, ids)
    lease = next(l for l in (await client.get(f"{V}/{val}/leases")).json() if l["tenant_id"])
    r = await client.post(f"/api/v1/leases/{lease['id']}/expense-recoveries", json={
        "expense_category": "cam", "recovery_type": "modified_gross", "expense_stop_per_sf": "-1"})
    assert r.status_code == 422


async def test_bulk_update_clears_a_field_sent_as_null_and_keeps_omitted_ones(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, _ = await _valuation_and_profile(client, ids)
    lease = next(l for l in (await client.get(f"{V}/{val}/leases")).json() if l["tenant_id"])
    override = (await client.post(f"/api/v1/leases/{lease['id']}/expense-recoveries", json={
        "expense_category": "cam", "recovery_type": "modified_gross", "expense_stop_per_sf": "2",
        "admin_fee_pct": "0.1", "cap_per_sf_annual": "9"})).json()

    r = await client.patch("/api/v1/leases/expense-recoveries/bulk", json={"updates": [{
        "lease_id": lease["id"], "override_id": override["id"],
        "fields": {"expense_category": "cam", "recovery_type": "modified_gross", "expense_stop_per_sf": None}}]})
    assert r.status_code == 200 and r.json()["upserted_count"] == 1, r.text
    (stored,) = (await client.get(f"/api/v1/leases/{lease['id']}")).json()["expense_recovery_overrides"]
    assert stored["expense_stop_per_sf"] is None
    assert float(stored["admin_fee_pct"]) == 0.1 and float(stored["cap_per_sf_annual"]) == 9


async def test_lease_override_recoverable_pct_weights_recovery_and_is_copied(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, _ = await _valuation_and_profile(client, ids)
    lease = next(l for l in (await client.get(f"{V}/{val}/leases")).json() if l["tenant_id"])
    r = await client.post(f"/api/v1/leases/{lease['id']}/expense-recoveries", json={
        "expense_category": "cam", "recovery_type": "nnn"})
    assert r.status_code == 201 and float(r.json()["recoverable_pct"]) == 1, r.text
    full = await _total_recoveries(client, val)

    r = await client.patch("/api/v1/leases/expense-recoveries/bulk", json={"updates": [{
        "lease_id": lease["id"], "override_id": r.json()["id"],
        "fields": {"expense_category": "cam", "recovery_type": "nnn", "recoverable_pct": "0.5"}}]})
    assert r.status_code == 200 and r.json()["upserted_count"] == 1, r.text
    half = await _total_recoveries(client, val)
    assert half < full

    copy = (await client.post(f"{V}/{val}/duplicate")).json()["id"]
    copied_lease = next(l for l in (await client.get(f"{V}/{copy}/leases")).json() if l["tenant_id"])
    (copied,) = (await client.get(f"/api/v1/leases/{copied_lease['id']}")).json()["expense_recovery_overrides"]
    assert float(copied["recoverable_pct"]) == 0.5
    assert await _total_recoveries(client, copy) == half
    assert (await client.post(f"/api/v1/leases/{lease['id']}/expense-recoveries", json={
        "expense_category": "taxes", "recovery_type": "nnn", "recoverable_pct": "1.5"})).status_code == 422
