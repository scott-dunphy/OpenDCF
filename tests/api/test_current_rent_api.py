"""Tenant rows carry the contract rent in force today, for the cash flow tooltip."""
from datetime import date
from decimal import Decimal

from httpx import AsyncClient

from src.engine.growth import rent_at_date
from tests.api.test_valuations_api import _setup_office_property

V = "/api/v1/valuations"


async def test_tenant_rows_show_rent_today(client: AsyncClient):
    ids = await _setup_office_property(client)
    pid, setup = ids["property_id"], ids["setup_valuation_id"]
    antenna = (await client.post(f"{V}/{setup}/suites", json={
        "suite_name": "Roof antenna", "area": "0", "space_type": "antenna"})).json()
    await client.post(f"/api/v1/suites/{antenna['id']}/leases", json={
        "lease_start_date": "2024-01-01", "lease_end_date": "2040-12-31", "base_rent_per_unit": "24000",
        "rent_basis": "total", "recovery_type": "none"})
    shop = (await client.post(f"{V}/{setup}/suites", json={
        "suite_name": "Shop", "area": "2000", "space_type": "office"})).json()
    await client.post(f"/api/v1/suites/{shop['id']}/leases", json={
        "lease_start_date": "2024-01-01", "lease_end_date": "2040-12-31", "base_rent_per_unit": "30",
        "escalation_type": "pct_annual", "escalation_pct_annual": "0.03", "recovery_type": "none"})
    old = (await client.post(f"{V}/{setup}/suites", json={
        "suite_name": "Ended", "area": "1000", "space_type": "office"})).json()
    await client.post(f"/api/v1/suites/{old['id']}/leases", json={
        "lease_start_date": "2015-01-01", "lease_end_date": "2019-12-31", "base_rent_per_unit": "20",
        "recovery_type": "none"})
    val = (await client.post(f"/api/v1/properties/{pid}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()
    assert (await client.post(f"{V}/{val['id']}/run")).status_code == 200

    rows = {r["suite_name"]: r for r in (await client.get(f"{V}/{val['id']}/reports/tenant-detail")).json()}
    assert Decimal(rows["Roof antenna"]["current_rent_annual"]) == Decimal("24000")
    assert rows["Roof antenna"]["current_rent_basis"] == "total"
    expected = rent_at_date(Decimal("30"), Decimal("0.03"), date(2024, 1, 1), date.today())
    assert Decimal(rows["Shop"]["current_rent_rate"]) == expected
    assert Decimal(rows["Shop"]["current_rent_annual"]) == expected * 2000
    if "Ended" in rows:
        assert rows["Ended"]["current_rent_annual"] is None
