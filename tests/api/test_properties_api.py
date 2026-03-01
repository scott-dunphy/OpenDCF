"""End-to-end API tests for properties and suites."""
import pytest
import pytest_asyncio
from httpx import AsyncClient


class TestPropertyCRUD:
    async def test_create_property(self, client: AsyncClient):
        resp = await client.post("/api/v1/properties", json={
            "name": "Test Office Building",
            "property_type": "office",
            "total_area": "50000",
            "area_unit": "sf",
            "analysis_start_date": "2025-01-01",
            "analysis_period_months": 120,
            "fiscal_year_end_month": 12,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Office Building"
        assert data["property_type"] == "office"
        assert "id" in data

    async def test_list_properties(self, client: AsyncClient):
        # Create two properties
        for name in ["Property A", "Property B"]:
            await client.post("/api/v1/properties", json={
                "name": name,
                "property_type": "retail",
                "total_area": "10000",
                "area_unit": "sf",
                "analysis_start_date": "2025-01-01",
            })
        resp = await client.get("/api/v1/properties")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_get_property_not_found(self, client: AsyncClient):
        resp = await client.get("/api/v1/properties/nonexistent-id")
        assert resp.status_code == 404

    async def test_update_property(self, client: AsyncClient):
        create = await client.post("/api/v1/properties", json={
            "name": "Old Name",
            "property_type": "industrial",
            "total_area": "100000",
            "area_unit": "sf",
            "analysis_start_date": "2025-01-01",
        })
        prop_id = create.json()["id"]

        update = await client.put(f"/api/v1/properties/{prop_id}", json={"name": "New Name"})
        assert update.status_code == 200
        assert update.json()["name"] == "New Name"

    async def test_delete_property(self, client: AsyncClient):
        create = await client.post("/api/v1/properties", json={
            "name": "To Delete",
            "property_type": "multifamily",
            "total_area": "50",
            "area_unit": "unit",
            "analysis_start_date": "2025-01-01",
        })
        prop_id = create.json()["id"]
        delete = await client.delete(f"/api/v1/properties/{prop_id}")
        assert delete.status_code == 204
        get = await client.get(f"/api/v1/properties/{prop_id}")
        assert get.status_code == 404


class TestSuiteCRUD:
    async def _create_property(self, client: AsyncClient) -> str:
        resp = await client.post("/api/v1/properties", json={
            "name": "Test Property",
            "property_type": "office",
            "total_area": "20000",
            "area_unit": "sf",
            "analysis_start_date": "2025-01-01",
        })
        return resp.json()["id"]

    async def test_create_suite(self, client: AsyncClient):
        prop_id = await self._create_property(client)
        resp = await client.post(f"/api/v1/properties/{prop_id}/suites", json={
            "suite_name": "Suite 100",
            "area": "2500",
            "space_type": "office",
            "floor": 1,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["suite_name"] == "Suite 100"
        assert data["property_id"] == prop_id

    async def test_list_suites(self, client: AsyncClient):
        prop_id = await self._create_property(client)
        for name in ["Suite 100", "Suite 200", "Suite 300"]:
            await client.post(f"/api/v1/properties/{prop_id}/suites", json={
                "suite_name": name,
                "area": "1000",
                "space_type": "office",
            })
        resp = await client.get(f"/api/v1/properties/{prop_id}/suites")
        assert resp.status_code == 200
        assert len(resp.json()) == 3
