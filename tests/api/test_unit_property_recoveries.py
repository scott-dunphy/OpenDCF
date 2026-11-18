"""Unit-based properties (multifamily, self storage) bill no expense recoveries."""
from httpx import AsyncClient


async def test_multifamily_leases_do_not_recover_expenses(client: AsyncClient):
    # A resident lease left at the default NNN would recover opex until it expires, then stop
    prop = await client.post("/api/v1/properties", json={
        "name": "Apartments", "property_type": "multifamily", "total_area": "10", "area_unit": "unit",
        "analysis_start_date": "2025-01-01", "analysis_period_months": 24, "fiscal_year_end_month": 12,
    })
    val = await client.post(f"/api/v1/properties/{prop.json()['id']}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.06"})
    val_id = val.json()["id"]
    suite = await client.post(f"/api/v1/valuations/{val_id}/suites", json={
        "suite_name": "1BR", "area": "10", "space_type": "1br"})
    lease = await client.post(f"/api/v1/suites/{suite.json()['id']}/leases", json={
        "lease_start_date": "2024-07-01", "lease_end_date": "2025-06-30", "base_rent_per_unit": "1500",
        "rent_payment_frequency": "monthly", "escalation_type": "flat", "recovery_type": "nnn"})
    assert lease.status_code == 201
    await client.post(f"/api/v1/valuations/{val_id}/market-profiles", json={
        "space_type": "1br", "market_rent_per_unit": "1500", "renewal_probability": "0.5"})
    await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
        "category": "repairs_maintenance", "base_year_amount": "12000", "growth_rate_pct": "0", "is_recoverable": True})

    run = await client.post(f"/api/v1/valuations/{val_id}/run")
    assert run.status_code == 200, run.text
    assert [float(cf["expense_recoveries"]) for cf in run.json()["annual_cash_flows"]] == [0, 0]
