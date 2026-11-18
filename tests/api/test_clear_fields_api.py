"""Updates: an explicit null clears an optional field; a null for a required field leaves it as is;
an omitted field is untouched. Edit forms send null when the user blanks a field."""
import pytest
from httpx import AsyncClient

P = "/api/v1/properties"
V = "/api/v1/valuations"


async def _valuation(client: AsyncClient) -> tuple[str, str]:
    r = await client.post(P, json={
        "name": "Clear Test", "property_type": "office", "total_area": "10000", "area_unit": "sf",
        "analysis_start_date": "2026-01-01", "year_built": 1990,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = await client.post(f"{P}/{pid}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})
    assert r.status_code == 201, r.text
    return pid, r.json()["id"]


# (collection, create body, required field and its created value as returned)
RECORDS = [
    ("suites", {"suite_name": "100", "area": "5000", "space_type": "office"}, "suite_name", "100"),
    ("tenants", {"name": "Acme"}, "name", "Acme"),
    ("expenses", {"category": "cam", "base_year_amount": "50000"}, "category", "cam"),
    ("other-income", {"category": "parking", "base_year_amount": "12000"}, "category", "parking"),
    ("capital-projects", {"description": "Roof", "total_amount": "100000", "start_date": "2026-06-01",
                          "duration_months": 3}, "description", "Roof"),
    ("market-profiles", {"space_type": "office", "market_rent_per_unit": "30", "rent_growth_rate_pct": "0.03",
                         "new_lease_term_months": 60, "renewal_probability": "0.7"}, "space_type", "office"),
]


@pytest.mark.parametrize("collection,body,required,value", RECORDS, ids=[r[0] for r in RECORDS])
async def test_null_clears_optional_and_keeps_required(client: AsyncClient, collection, body, required, value):
    _, vid = await _valuation(client)
    r = await client.post(f"{V}/{vid}/{collection}", json={**body, "comment": "source note"})
    assert r.status_code == 201, r.text
    url = f"{V}/{vid}/{collection}/{r.json()['id']}"

    r = await client.put(url, json={"comment": None})
    assert r.status_code == 200, r.text
    assert r.json()["comment"] is None
    assert r.json()[required] == value  # omitted: untouched

    r = await client.put(url, json={required: None})
    assert r.status_code in (200, 422), r.text
    if r.status_code == 200:
        assert r.json()[required] == value  # a required field cannot be blanked


async def test_property_null_clears_year_built(client: AsyncClient):
    pid, _ = await _valuation(client)
    r = await client.put(f"{P}/{pid}", json={"year_built": None, "name": None})
    assert r.status_code in (200, 422), r.text
    r = await client.put(f"{P}/{pid}", json={"year_built": None})
    assert r.status_code == 200, r.text
    assert r.json()["year_built"] is None
    assert r.json()["name"] == "Clear Test"
