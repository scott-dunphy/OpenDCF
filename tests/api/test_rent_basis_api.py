"""0 SF space (antennas, signage) with rent entered as a total amount."""
from decimal import Decimal

from httpx import AsyncClient

from tests.api.test_valuations_api import _setup_office_property

V = "/api/v1/valuations"


async def test_antenna_lease_on_zero_sf_adds_its_rent(client: AsyncClient):
    ids = await _setup_office_property(client)
    pid = ids["property_id"]
    base = (await client.post(f"/api/v1/properties/{pid}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()
    before = (await client.post(f"{V}/{base['id']}/run")).json()["annual_cash_flows"][0]

    suite = await client.post(f"{V}/{base['id']}/suites", json={
        "suite_name": "Roof antenna", "area": "0", "space_type": "antenna"})
    assert suite.status_code == 201, suite.text
    lease = await client.post(f"/api/v1/suites/{suite.json()['id']}/leases", json={
        "lease_start_date": "2024-01-01", "lease_end_date": "2040-12-31", "base_rent_per_unit": "24000",
        "rent_basis": "total", "recovery_type": "none"})
    assert lease.status_code == 201, lease.text
    assert lease.json()["rent_basis"] == "total"

    after = (await client.post(f"{V}/{base['id']}/run")).json()["annual_cash_flows"][0]
    assert Decimal(after["gross_potential_rent"]) - Decimal(before["gross_potential_rent"]) == Decimal("24000")
    # The workspace (and its 0 SF suite) still loads
    assert (await client.get(f"{V}/{base['id']}/workspace")).status_code == 200
    roll = (await client.get(f"{V}/{base['id']}/reports/rent-roll")).json()
    antenna = next(r for r in roll if r["suite_name"] == "Roof antenna")
    assert Decimal(antenna["annual_rent"]) == Decimal("24000")


async def test_market_profile_total_rent_for_vacant_antenna(client: AsyncClient):
    ids = await _setup_office_property(client)
    pid = ids["property_id"]
    await client.post(f"{V}/{ids['setup_valuation_id']}/suites", json={
        "suite_name": "Roof antenna", "area": "0", "space_type": "antenna"})
    val = (await client.post(f"/api/v1/properties/{pid}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()
    before = Decimal((await client.post(f"{V}/{val['id']}/run")).json()["key_metrics"]["npv"])
    mp = await client.post(f"{V}/{val['id']}/market-profiles", json={
        "space_type": "antenna", "market_rent_per_unit": "20000", "rent_basis": "total",
        "downtime_months": 0, "general_vacancy_pct": "0"})
    assert mp.status_code == 201, mp.text
    after = Decimal((await client.post(f"{V}/{val['id']}/run")).json()["key_metrics"]["npv"])
    assert after > before


async def test_downtime_on_total_basis_space_loses_the_total_rent(client: AsyncClient):
    """Turnover vacancy uses the same rent basis as the lease: a $12,000/yr antenna vacant
    for 12 months of downtime loses $12,000 of market rent each time, not $0."""
    ids = await _setup_office_property(client)
    pid = ids["property_id"]
    suite = (await client.post(f"{V}/{ids['setup_valuation_id']}/suites", json={
        "suite_name": "Roof antenna", "area": "0", "space_type": "antenna"})).json()
    await client.post(f"/api/v1/suites/{suite['id']}/leases", json={
        "lease_start_date": "2020-01-01", "lease_end_date": "2025-12-31", "base_rent_per_unit": "12000",
        "rent_basis": "total", "recovery_type": "none", "upon_expiration": "vacate"})
    val = (await client.post(f"/api/v1/properties/{pid}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()
    await client.post(f"{V}/{val['id']}/market-profiles", json={
        "space_type": "antenna", "market_rent_per_unit": "12000", "rent_basis": "total",
        "downtime_months": 12, "renewal_probability": "0", "rent_growth_rate_pct": "0"})
    [mp] = [m for m in (await client.get(f"{V}/{val['id']}/market-profiles")).json() if m["space_type"] == "antenna"]

    def vacancy(run):
        return sum(Decimal(y["absorption_vacancy"]) for y in run["annual_cash_flows"])

    total = vacancy((await client.post(f"{V}/{val['id']}/run")).json())
    await client.put(f"{V}/{val['id']}/market-profiles/{mp['id']}", json={"rent_basis": "per_area"})
    per_area = vacancy((await client.post(f"{V}/{val['id']}/run")).json())  # $ x 0 SF = no loss
    # Two 12-month downtimes in 10 years: after the 2025 expiry and after the 5-year market lease
    assert total - per_area == Decimal("-24000")
