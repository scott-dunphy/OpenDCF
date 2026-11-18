"""Valuation updates: explicit nulls clear operating models; property updates: ZIP changes re-derive
the CBSA; rent-roll conversion to a storage unit mix."""
import json
from decimal import Decimal

from httpx import AsyncClient

P = "/api/v1/properties"
V = "/api/v1/valuations"


async def _storage_rent_roll(
    client: AsyncClient, area_unit="unit", suites=(("10x10", "150", "0.03"),)
) -> tuple[str, str]:
    """(property_id, valuation_id) of a unit rent roll held by the property's valuation."""
    prop = (await client.post(P, json={
        "name": "Old Storage", "property_type": "self_storage", "total_area": "150", "area_unit": area_unit,
        "analysis_start_date": "2026-01-01",
    })).json()
    val = (await client.post(f"{P}/{prop['id']}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()
    for name, area, growth in suites:
        assert (await client.post(f"{V}/{val['id']}/suites", json={
            "suite_name": name, "area": area, "space_type": name,
        })).status_code == 201
        assert (await client.post(f"/api/v1/valuations/{val['id']}/market-profiles", json={
            "space_type": name, "market_rent_per_unit": "120", "rent_growth_rate_pct": growth,
            "rent_payment_frequency": "monthly", "new_lease_term_months": 12, "renewal_probability": "0.7",
            "general_vacancy_pct": "0.1",
        })).status_code == 201
    return prop["id"], val["id"]


async def test_explicit_null_clears_the_storage_model_and_convert_works_again(client: AsyncClient):
    pid, vid = await _storage_rent_roll(client)
    r = await client.post(f"{V}/{vid}/self-storage/convert-rent-roll")
    assert r.status_code == 200, r.text
    assert (await client.post(f"{V}/{vid}/self-storage/convert-rent-roll")).status_code == 409

    # Omitting the field leaves it alone
    r = await client.put(f"{V}/{vid}", json={"name": "Renamed"})
    assert r.json()["self_storage_assumptions_json"] is not None

    # Conversion switched the property's area to SF, so going back to the rent roll restores units as well
    r = await client.put(f"{V}/{vid}", json={"self_storage_assumptions_json": None})
    assert r.status_code == 200, r.text
    assert r.json()["self_storage_assumptions_json"] is None
    r = await client.put(f"{P}/{pid}", json={"area_unit": "unit", "total_area": "150"})
    assert r.status_code == 200, r.text
    assert (await client.post(f"{V}/{vid}/self-storage/convert-rent-roll")).status_code == 200


async def test_explicit_null_clears_marina_and_seniors_models(client: AsyncClient):
    _, vid = await _storage_rent_roll(client)
    r = await client.put(f"{V}/{vid}", json={
        "marina_assumptions_json": "{}", "seniors_housing_assumptions_json": "{}",
    })
    assert r.json()["marina_assumptions_json"] == "{}"
    r = await client.put(f"{V}/{vid}", json={
        "marina_assumptions_json": None, "seniors_housing_assumptions_json": None,
    })
    assert r.json()["marina_assumptions_json"] is None and r.json()["seniors_housing_assumptions_json"] is None


async def test_zip_change_outside_any_cbsa_clears_the_old_one(client: AsyncClient):
    pid, _ = await _storage_rent_roll(client)
    p = (await client.put(f"{P}/{pid}", json={"zip_code": "75201", "city": "Dallas", "state": "TX"})).json()
    assert p["cbsa_code"] == "19100"
    # 59010 is not in the ZIP-to-CBSA file; the moved property's city and state match no CBSA either
    p = (await client.put(f"{P}/{pid}", json={"zip_code": "59010", "city": "Pryor", "state": "MT"})).json()
    assert p["cbsa_code"] is None
    # An explicit code in the same request still wins
    p = (await client.put(f"{P}/{pid}", json={"zip_code": "75202", "cbsa_code": "28140"})).json()
    assert p["cbsa_code"] == "28140"


async def test_sf_rent_roll_is_not_converted(client: AsyncClient):
    _, vid = await _storage_rent_roll(client, area_unit="sf", suites=(("10x10", "1000", "0.03"),))
    r = await client.post(f"{V}/{vid}/self-storage/convert-rent-roll")
    assert r.status_code == 422
    assert "square feet" in r.text


async def test_street_rate_growth_is_unit_weighted_across_used_profiles(client: AsyncClient):
    _, vid = await _storage_rent_roll(client, suites=(("10x10", "100", "0.02"), ("10x20", "300", "0.04")))
    r = await client.post(f"{V}/{vid}/self-storage/convert-rent-roll")
    assert r.status_code == 200, r.text
    model = json.loads(r.json()["self_storage_assumptions_json"])
    # (100 * 2% + 300 * 4%) / 400 = 3.5%
    assert Decimal(model["street_rate_growth_pct"]) == Decimal("0.035")
