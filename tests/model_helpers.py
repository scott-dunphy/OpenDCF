"""API test helpers: a property and the valuation that owns its model."""
from httpx import AsyncClient

PROPERTY = {
    "name": "Test Property",
    "property_type": "office",
    "total_area": "10000",
    "area_unit": "sf",
    "analysis_start_date": "2025-01-01",
    "analysis_period_months": 120,
    "fiscal_year_end_month": 12,
}
VALUATION = {"name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"}


async def create_model(
    client: AsyncClient, property_fields: dict | None = None, valuation_fields: dict | None = None
) -> tuple[str, str]:
    """Create a property and its first valuation; (property_id, valuation_id).

    Inputs (suites, tenants, expenses...) are then posted to /api/v1/valuations/{valuation_id}/...
    """
    prop = await client.post("/api/v1/properties", json={**PROPERTY, **(property_fields or {})})
    assert prop.status_code == 201, prop.text
    prop_id = prop.json()["id"]
    val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={**VALUATION, **(valuation_fields or {})})
    assert val.status_code == 201, val.text
    return prop_id, val.json()["id"]
