from datetime import date

from httpx import AsyncClient


async def _property(client: AsyncClient) -> dict:
    response = await client.post("/api/v1/properties", json={
        "name": "Subject Industrial",
        "property_type": "industrial",
        "total_area": "100000",
        "area_unit": "sf",
        "year_built": 2010,
        "market": "Dallas",
        "city": "Dallas",
        "state": "TX",
        "analysis_start_date": "2026-01-01",
        "analysis_period_months": 120,
        "fiscal_year_end_month": 12,
        "amenities": {"clear_height": 32, "dock_doors": 20, "rail": False},
    })
    assert response.status_code == 201, response.text
    return response.json()


async def _sale(client: AsyncClient, i: int, verified: bool = True) -> dict:
    area = 70000 + i * 5000
    clear_height = 24 + i
    price_per_sf = 105 + 1.8 * clear_height + i * 0.7
    response = await client.post("/api/v1/comparable-sales", json={
        "external_id": f"sale-{i}",
        "property_name": f"Industrial Comp {i}",
        "sale_date": date(2024 + i // 8, 1 + i % 8, 15).isoformat(),
        "sale_price": str(round(area * price_per_sf, 2)),
        "property_type": "industrial",
        "area": str(area),
        "area_unit": "sf",
        "city": "Dallas" if i < 9 else "Fort Worth",
        "state": "TX",
        "market": "Dallas" if i < 9 else "Fort Worth",
        "year_built": 1998 + i,
        "occupancy_pct": str(0.82 + i * 0.01),
        "normalized_noi": str(round(area * (7.0 + i * 0.15), 2)),
        "amenities": {"clear_height": clear_height, "dock_doors": 8 + i, "rail": i % 4 == 0},
        "source": "Verified deed and broker package",
        "verification_status": "verified" if verified else "unverified",
    })
    assert response.status_code == 201, response.text
    return response.json()


class TestComparableSales:
    async def test_manual_adjustment_and_weighting(self, client: AsyncClient):
        prop = await _property(client)
        first = await _sale(client, 1)
        second = await _sale(client, 2)
        for sale, weight, adjustment in ((first, "2", "0.05"), (second, "1", "-0.03")):
            selected = await client.put(
                f"/api/v1/properties/{prop['id']}/comparable-sales/{sale['id']}",
                json={
                    "weight": weight,
                    "adjustments": {"market_time": adjustment},
                    "rationale": "Adjusted to the subject effective date",
                },
            )
            assert selected.status_code == 200, selected.text

        analysis = await client.get(
            f"/api/v1/properties/{prop['id']}/comparable-analysis/manual"
        )
        assert analysis.status_code == 200
        body = analysis.json()
        assert len(body["rows"]) == 2
        assert float(body["weighted_price_per_area"]) > 0
        assert abs(float(body["indicated_value"]) - float(body["weighted_price_per_area"]) * 100000) < 1
        assert any("Fewer than three" in warning for warning in body["warnings"])

    async def test_statistical_price_per_sf_with_amenities(self, client: AsyncClient):
        prop = await _property(client)
        for i in range(12):
            await _sale(client, i)
        response = await client.post(
            f"/api/v1/properties/{prop['id']}/comparable-analysis/statistical",
            json={"occupancy_pct": "0.94", "normalized_noi": "780000"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["observation_count"] == 12
        assert float(body["estimated_price_per_area"]) > 100
        assert float(body["prediction_low"]) < float(body["indicated_value"]) < float(body["prediction_high"])
        assert body["model_mape"] < 0.20
        assert any(key.startswith("amenity:") for key in body["coefficients"])

    async def test_statistical_model_refuses_thin_data(self, client: AsyncClient):
        prop = await _property(client)
        await _sale(client, 1)
        response = await client.post(
            f"/api/v1/properties/{prop['id']}/comparable-analysis/statistical",
            json={},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "insufficient_data"

    async def test_reconciliation(self, client: AsyncClient):
        prop = await _property(client)
        for i in range(3):
            sale = await _sale(client, i)
            await client.put(
                f"/api/v1/properties/{prop['id']}/comparable-sales/{sale['id']}",
                json={"weight": "1", "adjustments": {}},
            )
        response = await client.post(
            f"/api/v1/properties/{prop['id']}/comparable-analysis/reconcile",
            json={
                "statistical_price_per_area": "170",
                "weights": {"sales_comparison": "0.6", "statistical": "0.4"},
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body["indications"]) == {"sales_comparison", "statistical"}
        assert float(body["reconciled_value"]) > 0
