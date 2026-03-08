"""API tests for lease, rent step, free rent period, and expense recovery endpoints."""
import pytest
from httpx import AsyncClient


async def _create_suite(client: AsyncClient) -> tuple[str, str]:
    """Create a property and suite, return (property_id, suite_id)."""
    prop = await client.post("/api/v1/properties", json={
        "name": "Test Property",
        "property_type": "office",
        "total_area": "10000",
        "area_unit": "sf",
        "analysis_start_date": "2025-01-01",
        "analysis_period_months": 120,
        "fiscal_year_end_month": 12,
    })
    prop_id = prop.json()["id"]
    suite = await client.post(f"/api/v1/properties/{prop_id}/suites", json={
        "suite_name": "Suite 100",
        "area": "5000",
        "space_type": "office",
    })
    return prop_id, suite.json()["id"]


async def _create_lease(client: AsyncClient, suite_id: str, **overrides) -> dict:
    data = {
        "lease_start_date": "2025-01-01",
        "lease_end_date": "2029-12-31",
        "base_rent_per_unit": "30.00",
        "escalation_type": "flat",
        "recovery_type": "nnn",
    }
    data.update(overrides)
    resp = await client.post(f"/api/v1/suites/{suite_id}/leases", json=data)
    return resp.json()


class TestLeaseCRUD:
    async def test_create_lease(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        resp = await client.post(f"/api/v1/suites/{suite_id}/leases", json={
            "lease_start_date": "2025-01-01",
            "lease_end_date": "2029-12-31",
            "base_rent_per_unit": "30.00",
            "escalation_type": "flat",
            "recovery_type": "nnn",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["base_rent_per_unit"] == "30.00"
        assert data["recovery_type"] == "nnn"
        assert "id" in data

    async def test_create_lease_with_pct_annual_escalation(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        resp = await client.post(f"/api/v1/suites/{suite_id}/leases", json={
            "lease_start_date": "2025-01-01",
            "lease_end_date": "2029-12-31",
            "base_rent_per_unit": "28.00",
            "escalation_type": "pct_annual",
            "escalation_pct_annual": "0.03",
            "recovery_type": "nnn",
        })
        assert resp.status_code == 201
        assert resp.json()["escalation_pct_annual"] == "0.03"

    async def test_list_leases_for_suite(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        await _create_lease(client, suite_id, lease_end_date="2027-12-31")
        resp = await client.get(f"/api/v1/suites/{suite_id}/leases")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_get_lease_by_id(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id)
        lease_id = lease["id"]
        resp = await client.get(f"/api/v1/leases/{lease_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == lease_id

    async def test_get_lease_not_found(self, client: AsyncClient):
        resp = await client.get("/api/v1/leases/nonexistent-id")
        assert resp.status_code == 404

    async def test_update_lease(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id)
        lease_id = lease["id"]
        resp = await client.put(f"/api/v1/leases/{lease_id}", json={
            "base_rent_per_unit": "35.00",
        })
        assert resp.status_code == 200
        assert resp.json()["base_rent_per_unit"] == "35.00"

    async def test_update_lease_can_clear_nullable_fields(self, client: AsyncClient):
        prop_id, suite_id = await _create_suite(client)
        tenant = await client.post(f"/api/v1/properties/{prop_id}/tenants", json={"name": "Assigned Tenant"})
        assert tenant.status_code == 201

        lease = await _create_lease(
            client,
            suite_id,
            tenant_id=tenant.json()["id"],
            expense_stop_per_sf="12.50",
            recovery_structure_id=None,
        )
        lease_id = lease["id"]
        assert lease["tenant_id"] == tenant.json()["id"]
        assert lease["expense_stop_per_sf"] == "12.50"

        resp = await client.put(f"/api/v1/leases/{lease_id}", json={
            "tenant_id": None,
            "expense_stop_per_sf": None,
        })
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] is None
        assert resp.json()["expense_stop_per_sf"] is None

    async def test_delete_lease(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id)
        lease_id = lease["id"]
        resp = await client.delete(f"/api/v1/leases/{lease_id}")
        assert resp.status_code == 204
        # Verify it's gone
        resp2 = await client.get(f"/api/v1/leases/{lease_id}")
        assert resp2.status_code == 404

    async def test_create_lease_suite_not_found(self, client: AsyncClient):
        resp = await client.post("/api/v1/suites/nonexistent/leases", json={
            "lease_start_date": "2025-01-01",
            "lease_end_date": "2029-12-31",
            "base_rent_per_unit": "30.00",
            "escalation_type": "flat",
            "recovery_type": "nnn",
        })
        assert resp.status_code == 404

    async def test_create_overlapping_lease_rejected(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        await _create_lease(client, suite_id, lease_start_date="2025-01-01", lease_end_date="2027-12-31")
        resp = await client.post(f"/api/v1/suites/{suite_id}/leases", json={
            "lease_start_date": "2027-06-01",
            "lease_end_date": "2029-12-31",
            "base_rent_per_unit": "31.00",
            "escalation_type": "flat",
            "recovery_type": "nnn",
        })
        assert resp.status_code == 409

    async def test_create_lease_with_cross_property_tenant_rejected(self, client: AsyncClient):
        _, suite_a = await _create_suite(client)
        prop_b, _ = await _create_suite(client)
        tenant = await client.post(f"/api/v1/properties/{prop_b}/tenants", json={"name": "Wrong Property Tenant"})
        assert tenant.status_code == 201

        resp = await client.post(f"/api/v1/suites/{suite_a}/leases", json={
            "tenant_id": tenant.json()["id"],
            "lease_start_date": "2025-01-01",
            "lease_end_date": "2029-12-31",
            "base_rent_per_unit": "30.00",
            "escalation_type": "flat",
            "recovery_type": "nnn",
        })
        assert resp.status_code == 400
        assert "different property" in resp.json()["detail"]

    async def test_update_lease_to_overlap_rejected(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        await _create_lease(
            client,
            suite_id,
            lease_start_date="2025-01-01",
            lease_end_date="2026-12-31",
        )
        lease_b = await _create_lease(
            client,
            suite_id,
            lease_start_date="2027-01-01",
            lease_end_date="2028-12-31",
        )
        resp = await client.put(f"/api/v1/leases/{lease_b['id']}", json={
            "lease_start_date": "2026-06-01",
        })
        assert resp.status_code == 409


class TestBulkLeaseUpdates:
    async def test_bulk_update_leases_partial_success(self, client: AsyncClient):
        _, suite_a = await _create_suite(client)
        _, suite_b = await _create_suite(client)
        lease_a = await _create_lease(client, suite_a, base_rent_per_unit="30.00")
        lease_b = await _create_lease(client, suite_b, base_rent_per_unit="31.00")

        resp = await client.patch("/api/v1/leases/bulk", json={
            "atomic": False,
            "updates": [
                {"lease_id": lease_a["id"], "fields": {"base_rent_per_unit": "35.00"}},
                {"lease_id": "missing-lease-id", "fields": {"base_rent_per_unit": "32.00"}},
                {"lease_id": lease_b["id"], "fields": {"base_rent_per_unit": "36.00"}},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated_count"] == 2
        assert len(data["failed"]) == 1
        assert data["failed"][0]["lease_id"] == "missing-lease-id"
        assert data["failed"][0]["status_code"] == 404

        lease_a_after = await client.get(f"/api/v1/leases/{lease_a['id']}")
        lease_b_after = await client.get(f"/api/v1/leases/{lease_b['id']}")
        assert float(lease_a_after.json()["base_rent_per_unit"]) == 35.00
        assert float(lease_b_after.json()["base_rent_per_unit"]) == 36.00

    async def test_bulk_update_leases_atomic_rolls_back_on_error(self, client: AsyncClient):
        _, suite_a = await _create_suite(client)
        _, suite_b = await _create_suite(client)
        lease_a = await _create_lease(client, suite_a, base_rent_per_unit="30.00")
        lease_b = await _create_lease(client, suite_b, base_rent_per_unit="31.00")

        resp = await client.patch("/api/v1/leases/bulk", json={
            "atomic": True,
            "updates": [
                {"lease_id": lease_a["id"], "fields": {"base_rent_per_unit": "40.00"}},
                {"lease_id": "missing-lease-id", "fields": {"base_rent_per_unit": "42.00"}},
                {"lease_id": lease_b["id"], "fields": {"base_rent_per_unit": "44.00"}},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated_count"] == 0
        assert len(data["failed"]) == 1
        assert data["failed"][0]["lease_id"] == "missing-lease-id"
        assert data["failed"][0]["status_code"] == 404

        lease_a_after = await client.get(f"/api/v1/leases/{lease_a['id']}")
        lease_b_after = await client.get(f"/api/v1/leases/{lease_b['id']}")
        assert float(lease_a_after.json()["base_rent_per_unit"]) == 30.00
        assert float(lease_b_after.json()["base_rent_per_unit"]) == 31.00

    async def test_bulk_update_leases_atomic_success(self, client: AsyncClient):
        _, suite_a = await _create_suite(client)
        _, suite_b = await _create_suite(client)
        lease_a = await _create_lease(client, suite_a, base_rent_per_unit="30.00")
        lease_b = await _create_lease(client, suite_b, base_rent_per_unit="31.00")

        resp = await client.patch("/api/v1/leases/bulk", json={
            "atomic": True,
            "updates": [
                {"lease_id": lease_a["id"], "fields": {"base_rent_per_unit": "33.00"}},
                {"lease_id": lease_b["id"], "fields": {"base_rent_per_unit": "34.00"}},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated_count"] == 2
        assert data["failed"] == []

        lease_a_after = await client.get(f"/api/v1/leases/{lease_a['id']}")
        lease_b_after = await client.get(f"/api/v1/leases/{lease_b['id']}")
        assert float(lease_a_after.json()["base_rent_per_unit"]) == 33.00
        assert float(lease_b_after.json()["base_rent_per_unit"]) == 34.00


class TestRentSteps:
    async def test_add_rent_step(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id, escalation_type="fixed_step")
        lease_id = lease["id"]
        resp = await client.post(f"/api/v1/leases/{lease_id}/rent-steps", json={
            "effective_date": "2026-01-01",
            "rent_per_unit": "32.00",
        })
        assert resp.status_code == 201
        assert float(resp.json()["rent_per_unit"]) == 32.00

    async def test_add_multiple_rent_steps(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id, escalation_type="fixed_step")
        lease_id = lease["id"]

        for year, rent in [(2026, "32.00"), (2027, "34.00"), (2028, "36.00")]:
            resp = await client.post(f"/api/v1/leases/{lease_id}/rent-steps", json={
                "effective_date": f"{year}-01-01",
                "rent_per_unit": rent,
            })
            assert resp.status_code == 201

        # Verify they're returned in the lease
        lease_resp = await client.get(f"/api/v1/leases/{lease_id}")
        assert len(lease_resp.json()["rent_steps"]) == 3

    async def test_delete_rent_step(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id, escalation_type="fixed_step")
        lease_id = lease["id"]

        step_resp = await client.post(f"/api/v1/leases/{lease_id}/rent-steps", json={
            "effective_date": "2026-01-01",
            "rent_per_unit": "32.00",
        })
        step_id = step_resp.json()["id"]

        del_resp = await client.delete(f"/api/v1/leases/{lease_id}/rent-steps/{step_id}")
        assert del_resp.status_code == 204

    async def test_delete_rent_step_not_found(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id)
        resp = await client.delete(f"/api/v1/leases/{lease['id']}/rent-steps/nonexistent")
        assert resp.status_code == 404


class TestFreeRentPeriods:
    async def test_add_free_rent_period(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id)
        lease_id = lease["id"]

        resp = await client.post(f"/api/v1/leases/{lease_id}/free-rent-periods", json={
            "start_date": "2025-01-01",
            "end_date": "2025-03-31",
            "applies_to_base_rent": True,
            "applies_to_recoveries": False,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["applies_to_base_rent"] is True
        assert data["applies_to_recoveries"] is False

    async def test_free_rent_period_included_in_lease(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id)
        lease_id = lease["id"]

        await client.post(f"/api/v1/leases/{lease_id}/free-rent-periods", json={
            "start_date": "2025-01-01",
            "end_date": "2025-06-30",
            "applies_to_base_rent": True,
            "applies_to_recoveries": True,
        })

        lease_resp = await client.get(f"/api/v1/leases/{lease_id}")
        assert len(lease_resp.json()["free_rent_periods"]) == 1

    async def test_delete_free_rent_period(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id)
        lease_id = lease["id"]

        frp_resp = await client.post(f"/api/v1/leases/{lease_id}/free-rent-periods", json={
            "start_date": "2025-01-01",
            "end_date": "2025-03-31",
            "applies_to_base_rent": True,
            "applies_to_recoveries": False,
        })
        frp_id = frp_resp.json()["id"]

        del_resp = await client.delete(f"/api/v1/leases/{lease_id}/free-rent-periods/{frp_id}")
        assert del_resp.status_code == 204


class TestExpenseRecoveryOverrides:
    async def test_add_expense_recovery_override(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id)
        lease_id = lease["id"]

        resp = await client.post(f"/api/v1/leases/{lease_id}/expense-recoveries", json={
            "expense_category": "real_estate_taxes",
            "recovery_type": "base_year_stop",
            "base_year_stop_amount": "50000.00",
            "cap_per_sf_annual": "12.00",
            "admin_fee_pct": "0.15",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["recovery_type"] == "base_year_stop"
        assert data["base_year_stop_amount"] == "50000.00"

    async def test_delete_expense_recovery_override(self, client: AsyncClient):
        _, suite_id = await _create_suite(client)
        lease = await _create_lease(client, suite_id)
        lease_id = lease["id"]

        override_resp = await client.post(f"/api/v1/leases/{lease_id}/expense-recoveries", json={
            "expense_category": "cam",
            "recovery_type": "nnn",
        })
        override_id = override_resp.json()["id"]

        del_resp = await client.delete(f"/api/v1/leases/{lease_id}/expense-recoveries/{override_id}")
        assert del_resp.status_code == 204

        # Verify gone
        lease_resp = await client.get(f"/api/v1/leases/{lease_id}")
        overrides = lease_resp.json()["expense_recovery_overrides"]
        assert all(o["id"] != override_id for o in overrides)


class TestBulkExpenseRecoveryOverrides:
    async def test_bulk_upsert_expense_recoveries_partial_success(self, client: AsyncClient):
        _, suite_a = await _create_suite(client)
        _, suite_b = await _create_suite(client)
        lease_a = await _create_lease(client, suite_a)
        lease_b = await _create_lease(client, suite_b)

        existing = await client.post(f"/api/v1/leases/{lease_a['id']}/expense-recoveries", json={
            "expense_category": "cam",
            "recovery_type": "nnn",
            "admin_fee_pct": "0.10",
        })
        assert existing.status_code == 201
        existing_id = existing.json()["id"]

        resp = await client.patch("/api/v1/leases/expense-recoveries/bulk", json={
            "atomic": False,
            "updates": [
                {
                    "lease_id": lease_a["id"],
                    "override_id": existing_id,
                    "fields": {
                        "expense_category": "cam",
                        "recovery_type": "nnn",
                        "admin_fee_pct": "0.20",
                    },
                },
                {
                    "lease_id": lease_b["id"],
                    "fields": {
                        "expense_category": "real_estate_taxes",
                        "recovery_type": "base_year_stop",
                        "base_year_stop_amount": "25000.00",
                    },
                },
                {
                    "lease_id": "missing-lease-id",
                    "fields": {
                        "expense_category": "utilities",
                        "recovery_type": "nnn",
                    },
                },
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["upserted_count"] == 2
        assert len(data["failed"]) == 1
        assert data["failed"][0]["lease_id"] == "missing-lease-id"
        assert data["failed"][0]["status_code"] == 404

        lease_a_after = await client.get(f"/api/v1/leases/{lease_a['id']}")
        lease_b_after = await client.get(f"/api/v1/leases/{lease_b['id']}")
        override_a = next(o for o in lease_a_after.json()["expense_recovery_overrides"] if o["id"] == existing_id)
        assert float(override_a["admin_fee_pct"]) == 0.20
        assert len(lease_b_after.json()["expense_recovery_overrides"]) == 1
        assert lease_b_after.json()["expense_recovery_overrides"][0]["expense_category"] == "real_estate_taxes"

    async def test_bulk_upsert_expense_recoveries_atomic_rolls_back_on_error(self, client: AsyncClient):
        _, suite_a = await _create_suite(client)
        _, suite_b = await _create_suite(client)
        lease_a = await _create_lease(client, suite_a)
        lease_b = await _create_lease(client, suite_b)

        existing = await client.post(f"/api/v1/leases/{lease_a['id']}/expense-recoveries", json={
            "expense_category": "cam",
            "recovery_type": "nnn",
            "admin_fee_pct": "0.10",
        })
        assert existing.status_code == 201
        existing_id = existing.json()["id"]

        resp = await client.patch("/api/v1/leases/expense-recoveries/bulk", json={
            "atomic": True,
            "updates": [
                {
                    "lease_id": lease_a["id"],
                    "override_id": existing_id,
                    "fields": {
                        "expense_category": "cam",
                        "recovery_type": "nnn",
                        "admin_fee_pct": "0.30",
                    },
                },
                {
                    "lease_id": "missing-lease-id",
                    "fields": {
                        "expense_category": "utilities",
                        "recovery_type": "nnn",
                    },
                },
                {
                    "lease_id": lease_b["id"],
                    "fields": {
                        "expense_category": "insurance",
                        "recovery_type": "nnn",
                    },
                },
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["upserted_count"] == 0
        assert len(data["failed"]) == 1
        assert data["failed"][0]["lease_id"] == "missing-lease-id"
        assert data["failed"][0]["status_code"] == 404

        lease_a_after = await client.get(f"/api/v1/leases/{lease_a['id']}")
        lease_b_after = await client.get(f"/api/v1/leases/{lease_b['id']}")
        override_a = next(o for o in lease_a_after.json()["expense_recovery_overrides"] if o["id"] == existing_id)
        assert float(override_a["admin_fee_pct"]) == 0.10
        assert lease_b_after.json()["expense_recovery_overrides"] == []

    async def test_bulk_upsert_expense_recoveries_atomic_success(self, client: AsyncClient):
        _, suite_a = await _create_suite(client)
        _, suite_b = await _create_suite(client)
        lease_a = await _create_lease(client, suite_a)
        lease_b = await _create_lease(client, suite_b)

        existing = await client.post(f"/api/v1/leases/{lease_a['id']}/expense-recoveries", json={
            "expense_category": "cam",
            "recovery_type": "nnn",
            "admin_fee_pct": "0.10",
        })
        assert existing.status_code == 201
        existing_id = existing.json()["id"]

        resp = await client.patch("/api/v1/leases/expense-recoveries/bulk", json={
            "atomic": True,
            "updates": [
                {
                    "lease_id": lease_a["id"],
                    "override_id": existing_id,
                    "fields": {
                        "expense_category": "cam",
                        "recovery_type": "nnn",
                        "admin_fee_pct": "0.22",
                    },
                },
                {
                    "lease_id": lease_b["id"],
                    "fields": {
                        "expense_category": "utilities",
                        "recovery_type": "modified_gross",
                        "cap_per_sf_annual": "3.50",
                    },
                },
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["upserted_count"] == 2
        assert data["failed"] == []

        lease_a_after = await client.get(f"/api/v1/leases/{lease_a['id']}")
        lease_b_after = await client.get(f"/api/v1/leases/{lease_b['id']}")
        override_a = next(o for o in lease_a_after.json()["expense_recovery_overrides"] if o["id"] == existing_id)
        assert float(override_a["admin_fee_pct"]) == 0.22
        assert len(lease_b_after.json()["expense_recovery_overrides"]) == 1
        assert lease_b_after.json()["expense_recovery_overrides"][0]["expense_category"] == "utilities"
