"""End-to-end API tests for the full valuation workflow."""
import pytest
from httpx import AsyncClient


async def _setup_office_property(client: AsyncClient) -> dict:
    """
    Create a realistic 3-suite office property with in-place leases,
    market assumptions, and expenses. Returns IDs.
    """
    # 1. Property
    prop = await client.post("/api/v1/properties", json={
        "name": "Test Office — 3 Tenant",
        "property_type": "office",
        "total_area": "15000",
        "area_unit": "sf",
        "analysis_start_date": "2025-01-01",
        "analysis_period_months": 120,
        "fiscal_year_end_month": 12,
    })
    assert prop.status_code == 201
    prop_id = prop.json()["id"]

    # 2. Suites
    suite_ids = []
    for name, area in [("Suite 100", "5000"), ("Suite 200", "5000"), ("Suite 300", "5000")]:
        s = await client.post(f"/api/v1/properties/{prop_id}/suites", json={
            "suite_name": name,
            "area": area,
            "space_type": "office",
        })
        assert s.status_code == 201
        suite_ids.append(s.json()["id"])

    # 3. Tenant
    tenant = await client.post("/api/v1/tenants", json={"name": "Acme Corp"})
    tenant_id = tenant.json()["id"]

    # 4. Leases (Suite 100 and Suite 200 have in-place leases)
    lease_data = [
        {
            "suite_id": suite_ids[0],
            "tenant_id": tenant_id,
            "lease_start_date": "2023-01-01",
            "lease_end_date": "2027-12-31",
            "base_rent_per_unit": "30.00",  # $/SF/yr
            "escalation_type": "pct_annual",
            "escalation_pct_annual": "0.03",
            "recovery_type": "nnn",
        },
        {
            "suite_id": suite_ids[1],
            "lease_start_date": "2024-07-01",
            "lease_end_date": "2029-06-30",
            "base_rent_per_unit": "32.00",
            "escalation_type": "flat",
            "recovery_type": "nnn",
        },
    ]
    for suite_idx, data in enumerate(lease_data):
        sid = data.pop("suite_id")
        l = await client.post(f"/api/v1/suites/{sid}/leases", json=data)
        assert l.status_code == 201

    # 5. Market leasing profile
    mkt = await client.post(f"/api/v1/properties/{prop_id}/market-profiles", json={
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
    assert mkt.status_code == 201

    # 6. Operating expenses
    expense_data = [
        {"category": "real_estate_taxes", "base_year_amount": "150000", "growth_rate_pct": "0.03", "is_recoverable": True},
        {"category": "insurance", "base_year_amount": "30000", "growth_rate_pct": "0.03", "is_recoverable": True},
        {"category": "cam", "base_year_amount": "75000", "growth_rate_pct": "0.03", "is_recoverable": True, "is_gross_up_eligible": True, "gross_up_vacancy_pct": "0.95"},
        {"category": "management_fee", "base_year_amount": "0", "growth_rate_pct": "0", "is_recoverable": False, "is_pct_of_egi": True, "pct_of_egi": "0.04"},
    ]
    for exp in expense_data:
        e = await client.post(f"/api/v1/properties/{prop_id}/expenses", json=exp)
        assert e.status_code == 201

    return {
        "property_id": prop_id,
        "suite_ids": suite_ids,
        "tenant_id": tenant_id,
    }


class TestValuationWorkflow:
    async def test_full_valuation_run(self, client: AsyncClient):
        """Full end-to-end: create property → run valuation → check results."""
        ids = await _setup_office_property(client)
        prop_id = ids["property_id"]

        # Create valuation
        val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Base Case",
            "discount_rate": "0.08",
            "exit_cap_rate": "0.065",
            "exit_costs_pct": "0.02",
            "capital_reserves_per_unit": "0.25",
        })
        assert val.status_code == 201
        val_id = val.json()["id"]
        assert val.json()["status"] == "draft"

        # Run the valuation
        run = await client.post(f"/api/v1/valuations/{val_id}/run")
        assert run.status_code == 200
        result = run.json()
        assert result["status"] == "completed"

        # Verify key metrics exist
        metrics = result["key_metrics"]
        assert metrics is not None
        assert float(metrics["npv"]) > 0, "NPV should be positive"
        assert float(metrics["going_in_cap_rate"]) > 0
        assert float(metrics["terminal_value"]) > 0

        # Verify 10 years of cash flows
        annual_cfs = result["annual_cash_flows"]
        assert len(annual_cfs) == 10

        # Verify waterfall logic: EGI < GPI, NOI < EGI
        for cf in annual_cfs:
            gpi = float(cf["gross_potential_income"])
            egi = float(cf["effective_gross_income"])
            noi = float(cf["net_operating_income"])
            assert egi <= gpi, "EGI should be <= GPI"
            assert noi <= egi, "NOI should be <= EGI"

        # Verify rent roll returned
        assert len(result["rent_roll"]) == 3  # 3 suites

    async def test_valuation_run_report_endpoints(self, client: AsyncClient):
        """Test individual report endpoints after a run."""
        ids = await _setup_office_property(client)
        prop_id = ids["property_id"]

        val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Report Test",
            "discount_rate": "0.08",
            "exit_cap_rate": "0.065",
        })
        val_id = val.json()["id"]
        await client.post(f"/api/v1/valuations/{val_id}/run")

        # Cash flow summary
        cf_resp = await client.get(f"/api/v1/valuations/{val_id}/reports/cash-flow-summary")
        assert cf_resp.status_code == 200
        assert len(cf_resp.json()) == 10

        # Rent roll
        rr_resp = await client.get(f"/api/v1/valuations/{val_id}/reports/rent-roll")
        assert rr_resp.status_code == 200
        assert len(rr_resp.json()) == 3

        # Lease expirations
        exp_resp = await client.get(f"/api/v1/valuations/{val_id}/reports/lease-expirations")
        assert exp_resp.status_code == 200
        exps = exp_resp.json()
        assert len(exps) > 0

        # Key metrics
        km_resp = await client.get(f"/api/v1/valuations/{val_id}/reports/key-metrics")
        assert km_resp.status_code == 200
        km = km_resp.json()
        assert "npv" in km
        assert "irr" in km
        assert "going_in_cap_rate" in km

        # Tenant detail
        td_resp = await client.get(f"/api/v1/valuations/{val_id}/reports/tenant-detail")
        assert td_resp.status_code == 200
        assert isinstance(td_resp.json(), list)

        # Full report should retain computed occupancy in cached response
        full_resp = await client.get(f"/api/v1/valuations/{val_id}/reports/full")
        assert full_resp.status_code == 200
        full = full_resp.json()
        assert float(full["key_metrics"]["avg_occupancy_pct"]) > 0

    async def test_health_endpoint(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_enums_endpoint(self, client: AsyncClient):
        resp = await client.get("/api/v1/enums")
        assert resp.status_code == 200
        data = resp.json()
        assert "property_types" in data
        assert "office" in data["property_types"]
        assert "multifamily" in data["property_types"]
        assert "transfer_tax_presets" in data
        codes = [p["code"] for p in data["transfer_tax_presets"]]
        assert "la_city_ula" in codes

    async def test_valuation_transfer_tax_fields_persist(self, client: AsyncClient):
        prop = await client.post("/api/v1/properties", json={
            "name": "Transfer Tax Test Property",
            "property_type": "office",
            "total_area": "10000",
            "area_unit": "sf",
            "analysis_start_date": "2025-01-01",
        })
        assert prop.status_code == 201
        prop_id = prop.json()["id"]

        created = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Transfer Tax Create",
            "discount_rate": "0.08",
            "exit_cap_rate": "0.065",
            "transfer_tax_preset": "la_city_ula",
            "apply_stabilized_gross_up": True,
        })
        assert created.status_code == 201
        val = created.json()
        assert val["transfer_tax_preset"] == "la_city_ula"
        assert val["apply_stabilized_gross_up"] is True

        val_id = val["id"]
        updated = await client.put(f"/api/v1/valuations/{val_id}", json={
            "transfer_tax_preset": "custom_rate",
            "transfer_tax_custom_rate": "0.05",
            "apply_stabilized_gross_up": False,
            "stabilized_occupancy_pct": "0.90",
        })
        assert updated.status_code == 200
        val2 = updated.json()
        assert val2["transfer_tax_preset"] == "custom_rate"
        assert float(val2["transfer_tax_custom_rate"]) == pytest.approx(0.05)
        assert val2["apply_stabilized_gross_up"] is False
        assert float(val2["stabilized_occupancy_pct"]) == pytest.approx(0.90)

        fetched = await client.get(f"/api/v1/valuations/{val_id}")
        assert fetched.status_code == 200
        val3 = fetched.json()
        assert val3["transfer_tax_preset"] == "custom_rate"
        assert float(val3["transfer_tax_custom_rate"]) == pytest.approx(0.05)
        assert val3["apply_stabilized_gross_up"] is False
        assert float(val3["stabilized_occupancy_pct"]) == pytest.approx(0.90)
