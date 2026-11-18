"""API tests for market leasing profiles, expenses, and tenant endpoints."""
import pytest
from httpx import AsyncClient

from tests.model_helpers import create_model


async def _create_property(client: AsyncClient) -> str:
    resp = await client.post("/api/v1/properties", json={
        "name": "Test Office",
        "property_type": "office",
        "total_area": "10000",
        "area_unit": "sf",
        "analysis_start_date": "2025-01-01",
        "analysis_period_months": 120,
        "fiscal_year_end_month": 12,
    })
    return resp.json()["id"]


async def _create_model(client: AsyncClient) -> str:
    """A property and its valuation; the valuation id (it owns tenants, expenses, other income)."""
    _, valuation_id = await create_model(client, {"name": "Test Office"})
    return valuation_id


class TestTenantCRUD:
    async def test_create_tenant(self, client: AsyncClient):
        val_id = await _create_model(client)
        resp = await client.post(f"/api/v1/valuations/{val_id}/tenants", json={"name": "Acme Corp"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Acme Corp"
        assert "id" in data

    async def test_create_tenant_with_details(self, client: AsyncClient):
        val_id = await _create_model(client)
        resp = await client.post(f"/api/v1/valuations/{val_id}/tenants", json={
            "name": "Tech Co",
            "credit_rating": "A",
            "industry": "Technology",
        })
        assert resp.status_code == 201
        assert resp.json()["credit_rating"] == "A"

    async def test_list_tenants(self, client: AsyncClient):
        val_id = await _create_model(client)
        await client.post(f"/api/v1/valuations/{val_id}/tenants", json={"name": "Tenant A"})
        await client.post(f"/api/v1/valuations/{val_id}/tenants", json={"name": "Tenant B"})
        resp = await client.get(f"/api/v1/valuations/{val_id}/tenants")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    async def test_tenants_are_scoped_to_valuation(self, client: AsyncClient):
        val_a = await _create_model(client)
        val_b = await _create_model(client)
        await client.post(f"/api/v1/valuations/{val_a}/tenants", json={"name": "Tenant A"})
        await client.post(f"/api/v1/valuations/{val_b}/tenants", json={"name": "Tenant B"})

        resp_a = await client.get(f"/api/v1/valuations/{val_a}/tenants")
        assert resp_a.status_code == 200
        names_a = {t["name"] for t in resp_a.json()}
        assert "Tenant A" in names_a
        assert "Tenant B" not in names_a

    async def test_get_tenant(self, client: AsyncClient):
        val_id = await _create_model(client)
        create_resp = await client.post(f"/api/v1/valuations/{val_id}/tenants", json={"name": "BigCorp"})
        tenant_id = create_resp.json()["id"]
        resp = await client.get(f"/api/v1/valuations/{val_id}/tenants/{tenant_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "BigCorp"

    async def test_get_tenant_not_found(self, client: AsyncClient):
        val_id = await _create_model(client)
        resp = await client.get(f"/api/v1/valuations/{val_id}/tenants/nonexistent")
        assert resp.status_code == 404

    async def test_update_tenant(self, client: AsyncClient):
        val_id = await _create_model(client)
        create_resp = await client.post(f"/api/v1/valuations/{val_id}/tenants", json={"name": "Old Name"})
        tenant_id = create_resp.json()["id"]
        resp = await client.put(f"/api/v1/valuations/{val_id}/tenants/{tenant_id}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_delete_tenant(self, client: AsyncClient):
        val_id = await _create_model(client)
        create_resp = await client.post(f"/api/v1/valuations/{val_id}/tenants", json={"name": "To Delete"})
        tenant_id = create_resp.json()["id"]
        del_resp = await client.delete(f"/api/v1/valuations/{val_id}/tenants/{tenant_id}")
        assert del_resp.status_code == 204
        get_resp = await client.get(f"/api/v1/valuations/{val_id}/tenants/{tenant_id}")
        assert get_resp.status_code == 404



async def _create_valuation(client: AsyncClient, prop_id: str) -> str:
    """Market leasing profiles belong to a valuation."""
    resp = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})
    assert resp.status_code == 201
    return resp.json()["id"]

class TestMarketProfiles:
    async def test_create_market_profile(self, client: AsyncClient):
        prop_id = await _create_property(client)
        val_id = await _create_valuation(client, prop_id)
        resp = await client.post(f"/api/v1/valuations/{val_id}/market-profiles", json={
            "space_type": "office",
            "market_rent_per_unit": "35.00",
            "rent_growth_rate_pct": "0.03",
            "new_lease_term_months": 60,
            "new_tenant_ti_per_sf": "50.00",
            "new_tenant_lc_pct": "0.06",
            "new_tenant_free_rent_months": 3,
            "downtime_months": 6,
            "renewal_probability": "0.65",
            "renewal_lease_term_months": 60,
            "renewal_ti_per_sf": "20.00",
            "renewal_lc_pct": "0.03",
            "renewal_free_rent_months": 1,
            "renewal_rent_adjustment_pct": "-0.05",
            "general_vacancy_pct": "0.05",
            "credit_loss_pct": "0.01",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["space_type"] == "office"
        assert float(data["market_rent_per_unit"]) == 35.0
        assert float(data["renewal_probability"]) == 0.65

    async def test_duplicate_space_type_rejected(self, client: AsyncClient):
        """The engine keys market assumptions by space type; a second profile would shadow the first."""
        prop_id = await _create_property(client)
        val_id = await _create_valuation(client, prop_id)
        url = f"/api/v1/valuations/{val_id}/market-profiles"
        first = await client.post(url, json={"space_type": "office", "market_rent_per_unit": "30.00"})
        assert first.status_code == 201
        assert (await client.post(url, json={"space_type": "office", "market_rent_per_unit": "45.00"})).status_code == 409
        retail = await client.post(url, json={"space_type": "retail", "market_rent_per_unit": "25.00"})
        assert retail.status_code == 201

    async def test_list_market_profiles(self, client: AsyncClient):
        prop_id = await _create_property(client)
        val_id = await _create_valuation(client, prop_id)
        await client.post(f"/api/v1/valuations/{val_id}/market-profiles", json={
            "space_type": "office",
            "market_rent_per_unit": "35.00",
            "rent_growth_rate_pct": "0.03",
            "new_lease_term_months": 60,
            "new_tenant_ti_per_sf": "50.00",
            "new_tenant_lc_pct": "0.06",
            "new_tenant_free_rent_months": 3,
            "downtime_months": 6,
            "renewal_probability": "0.65",
            "renewal_lease_term_months": 60,
            "renewal_ti_per_sf": "20.00",
            "renewal_lc_pct": "0.03",
            "renewal_free_rent_months": 1,
            "renewal_rent_adjustment_pct": "0.00",
            "general_vacancy_pct": "0.05",
            "credit_loss_pct": "0.01",
        })
        resp = await client.get(f"/api/v1/valuations/{val_id}/market-profiles")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_get_market_profile(self, client: AsyncClient):
        prop_id = await _create_property(client)
        val_id = await _create_valuation(client, prop_id)
        create_resp = await client.post(f"/api/v1/valuations/{val_id}/market-profiles", json={
            "space_type": "retail",
            "market_rent_per_unit": "25.00",
            "rent_growth_rate_pct": "0.02",
            "new_lease_term_months": 60,
            "new_tenant_ti_per_sf": "30.00",
            "new_tenant_lc_pct": "0.06",
            "new_tenant_free_rent_months": 2,
            "downtime_months": 6,
            "renewal_probability": "0.60",
            "renewal_lease_term_months": 60,
            "renewal_ti_per_sf": "15.00",
            "renewal_lc_pct": "0.03",
            "renewal_free_rent_months": 0,
            "renewal_rent_adjustment_pct": "0.00",
            "general_vacancy_pct": "0.05",
            "credit_loss_pct": "0.01",
        })
        profile_id = create_resp.json()["id"]
        resp = await client.get(f"/api/v1/valuations/{val_id}/market-profiles/{profile_id}")
        assert resp.status_code == 200
        assert resp.json()["space_type"] == "retail"

    async def test_market_profile_not_found(self, client: AsyncClient):
        prop_id = await _create_property(client)
        val_id = await _create_valuation(client, prop_id)
        resp = await client.get(f"/api/v1/valuations/{val_id}/market-profiles/nonexistent")
        assert resp.status_code == 404

    async def test_update_market_profile(self, client: AsyncClient):
        prop_id = await _create_property(client)
        val_id = await _create_valuation(client, prop_id)
        create_resp = await client.post(f"/api/v1/valuations/{val_id}/market-profiles", json={
            "space_type": "office",
            "market_rent_per_unit": "35.00",
            "rent_growth_rate_pct": "0.03",
            "new_lease_term_months": 60,
            "new_tenant_ti_per_sf": "50.00",
            "new_tenant_lc_pct": "0.06",
            "new_tenant_free_rent_months": 3,
            "downtime_months": 6,
            "renewal_probability": "0.65",
            "renewal_lease_term_months": 60,
            "renewal_ti_per_sf": "20.00",
            "renewal_lc_pct": "0.03",
            "renewal_free_rent_months": 1,
            "renewal_rent_adjustment_pct": "0.00",
            "general_vacancy_pct": "0.05",
            "credit_loss_pct": "0.01",
        })
        profile_id = create_resp.json()["id"]
        resp = await client.put(f"/api/v1/valuations/{val_id}/market-profiles/{profile_id}", json={
            "market_rent_per_unit": "38.00",
        })
        assert resp.status_code == 200
        assert float(resp.json()["market_rent_per_unit"]) == 38.0
        # Market lease escalation: set, then cleared back to market rent growth with null
        url = f"/api/v1/valuations/{val_id}/market-profiles/{profile_id}"
        resp = await client.put(url, json={"lease_escalation_pct": "0.025", "lc_includes_escalations": False})
        assert float(resp.json()["lease_escalation_pct"]) == 0.025 and resp.json()["lc_includes_escalations"] is False
        resp = await client.put(url, json={"lease_escalation_pct": None, "market_rent_per_unit": "39.00"})
        assert resp.json()["lease_escalation_pct"] is None and resp.json()["lc_includes_escalations"] is False

    async def test_delete_market_profile(self, client: AsyncClient):
        prop_id = await _create_property(client)
        val_id = await _create_valuation(client, prop_id)
        create_resp = await client.post(f"/api/v1/valuations/{val_id}/market-profiles", json={
            "space_type": "office",
            "market_rent_per_unit": "35.00",
            "rent_growth_rate_pct": "0.03",
            "new_lease_term_months": 60,
            "new_tenant_ti_per_sf": "50.00",
            "new_tenant_lc_pct": "0.06",
            "new_tenant_free_rent_months": 3,
            "downtime_months": 6,
            "renewal_probability": "0.65",
            "renewal_lease_term_months": 60,
            "renewal_ti_per_sf": "20.00",
            "renewal_lc_pct": "0.03",
            "renewal_free_rent_months": 1,
            "renewal_rent_adjustment_pct": "0.00",
            "general_vacancy_pct": "0.05",
            "credit_loss_pct": "0.01",
        })
        profile_id = create_resp.json()["id"]
        del_resp = await client.delete(f"/api/v1/valuations/{val_id}/market-profiles/{profile_id}")
        assert del_resp.status_code == 204


class TestExpenses:
    async def test_create_expense(self, client: AsyncClient):
        val_id = await _create_model(client)
        resp = await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
            "category": "real_estate_taxes",
            "base_year_amount": "150000",
            "growth_rate_pct": "0.03",
            "is_recoverable": True,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["category"] == "real_estate_taxes"
        assert float(data["base_year_amount"]) == 150000

    async def test_update_rejects_percent_entered_as_whole_number(self, client: AsyncClient):
        val_id = await _create_model(client)
        exp = await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
            "category": "management_fee", "base_year_amount": "0", "is_pct_of_egi": True, "pct_of_egi": "0.04",
        })
        assert exp.status_code == 201
        resp = await client.put(f"/api/v1/valuations/{val_id}/expenses/{exp.json()['id']}", json={"pct_of_egi": "5"})
        assert resp.status_code == 422

    async def test_create_cam_expense_with_grossup(self, client: AsyncClient):
        val_id = await _create_model(client)
        resp = await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
            "category": "cam",
            "base_year_amount": "75000",
            "growth_rate_pct": "0.03",
            "is_recoverable": True,
            "is_gross_up_eligible": True,
            "gross_up_vacancy_pct": "0.95",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["is_gross_up_eligible"] is True
        assert float(data["gross_up_vacancy_pct"]) == 0.95

    async def test_create_mgmt_fee_expense(self, client: AsyncClient):
        val_id = await _create_model(client)
        resp = await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
            "category": "management_fee",
            "base_year_amount": "0",
            "growth_rate_pct": "0",
            "is_recoverable": False,
            "is_pct_of_egi": True,
            "pct_of_egi": "0.04",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["is_pct_of_egi"] is True
        assert float(data["pct_of_egi"]) == 0.04

    async def test_list_expenses(self, client: AsyncClient):
        val_id = await _create_model(client)
        categories = ["real_estate_taxes", "insurance", "cam"]
        for cat in categories:
            await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
                "category": cat,
                "base_year_amount": "50000",
                "growth_rate_pct": "0.03",
                "is_recoverable": True,
            })
        resp = await client.get(f"/api/v1/valuations/{val_id}/expenses")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    async def test_get_expense(self, client: AsyncClient):
        val_id = await _create_model(client)
        create_resp = await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
            "category": "insurance",
            "base_year_amount": "30000",
            "growth_rate_pct": "0.03",
            "is_recoverable": True,
        })
        exp_id = create_resp.json()["id"]
        resp = await client.get(f"/api/v1/valuations/{val_id}/expenses/{exp_id}")
        assert resp.status_code == 200
        assert resp.json()["category"] == "insurance"

    async def test_update_expense(self, client: AsyncClient):
        val_id = await _create_model(client)
        create_resp = await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
            "category": "utilities",
            "base_year_amount": "20000",
            "growth_rate_pct": "0.02",
            "is_recoverable": True,
        })
        exp_id = create_resp.json()["id"]
        resp = await client.put(f"/api/v1/valuations/{val_id}/expenses/{exp_id}", json={
            "base_year_amount": "25000",
        })
        assert resp.status_code == 200
        assert float(resp.json()["base_year_amount"]) == 25000

    async def test_delete_expense(self, client: AsyncClient):
        val_id = await _create_model(client)
        create_resp = await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
            "category": "real_estate_taxes",
            "base_year_amount": "100000",
            "growth_rate_pct": "0.03",
            "is_recoverable": True,
        })
        exp_id = create_resp.json()["id"]
        del_resp = await client.delete(f"/api/v1/valuations/{val_id}/expenses/{exp_id}")
        assert del_resp.status_code == 204
        get_resp = await client.get(f"/api/v1/valuations/{val_id}/expenses/{exp_id}")
        assert get_resp.status_code == 404

    async def test_expense_not_found(self, client: AsyncClient):
        val_id = await _create_model(client)
        resp = await client.get(f"/api/v1/valuations/{val_id}/expenses/nonexistent")
        assert resp.status_code == 404

    async def test_create_custom_expense_category(self, client: AsyncClient):
        val_id = await _create_model(client)
        resp = await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
            "category": "security_patrol",
            "description": "On-site security vendor",
            "base_year_amount": "42000",
            "growth_rate_pct": "0.025",
            "is_recoverable": True,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["category"] == "security_patrol"
        assert data["description"] == "On-site security vendor"


class TestOtherIncome:
    async def test_create_custom_other_income_item(self, client: AsyncClient):
        val_id = await _create_model(client)
        resp = await client.post(f"/api/v1/valuations/{val_id}/other-income", json={
            "category": "cell_tower_lease",
            "description": "Rooftop telecom lease",
            "base_year_amount": "18000",
            "growth_rate_pct": "0.02",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["category"] == "cell_tower_lease"
        assert float(data["base_year_amount"]) == 18000

    async def test_list_other_income_items(self, client: AsyncClient):
        val_id = await _create_model(client)
        for category in ("parking", "laundry"):
            await client.post(f"/api/v1/valuations/{val_id}/other-income", json={
                "category": category,
                "base_year_amount": "10000",
                "growth_rate_pct": "0.03",
            })
        resp = await client.get(f"/api/v1/valuations/{val_id}/other-income")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestGrowthSchedulesApi:
    async def test_schedules_round_trip(self, client: AsyncClient):
        prop_id = await _create_property(client)
        val_id = await _create_valuation(client, prop_id)
        mp = await client.post(f"/api/v1/valuations/{val_id}/market-profiles", json={
            "space_type": "office", "market_rent_per_unit": "35",
            "rent_growth_schedule": ["0.02", "0.03", "-0.01"],
        })
        assert mp.status_code == 201, mp.text
        assert [float(v) for v in mp.json()["rent_growth_schedule"]] == [0.02, 0.03, -0.01]

        ex = await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
            "category": "insurance", "base_year_amount": "1000", "growth_schedule": ["0.05"],
        })
        assert ex.status_code == 201, ex.text
        assert [float(v) for v in ex.json()["growth_schedule"]] == [0.05]

        # Clearing the table with an empty list
        upd = await client.put(f"/api/v1/valuations/{val_id}/expenses/{ex.json()['id']}", json={"growth_schedule": []})
        assert upd.status_code == 200, upd.text
        assert upd.json()["growth_schedule"] == []

        oi = await client.post(f"/api/v1/valuations/{val_id}/other-income", json={
            "category": "parking", "base_year_amount": "500", "growth_schedule": ["0.01", "0.02"],
        })
        assert oi.status_code == 201, oi.text
        assert len(oi.json()["growth_schedule"]) == 2

    async def test_schedule_rejects_out_of_range(self, client: AsyncClient):
        val_id = await _create_model(client)
        resp = await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
            "category": "insurance", "base_year_amount": "1000", "growth_schedule": ["3"],
        })
        assert resp.status_code == 422
