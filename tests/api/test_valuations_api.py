"""End-to-end API tests for the full valuation workflow."""
import json
from decimal import Decimal

import pytest
from httpx import AsyncClient

from src.engine.dcf import discount_cash_flows
from src.engine.seniors_housing import (
    DebtInput as SHDebtInput,
    _build_debt_service as sh_build_debt_service,
)
from src.schemas.cashflow import AnnualCashFlowSummary


async def _setup_office_property(client: AsyncClient) -> dict:
    """
    Create a realistic 3-suite office property with in-place leases,
    market assumptions, and expenses, all on a "Market setup" valuation (setup_valuation_id).
    A valuation the test creates afterwards copies that whole model; its suites and tenant have
    new ids (suite_ids / tenant_id are the setup valuation's). Returns IDs.
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
    # The model belongs to a valuation; valuations created later copy the newest one's whole model
    setup = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
        "name": "Market setup", "discount_rate": "0.08", "exit_cap_rate": "0.065"})
    assert setup.status_code == 201
    model_id = setup.json()["id"]

    # 2. Suites
    suite_ids = []
    for name, area in [("Suite 100", "5000"), ("Suite 200", "5000"), ("Suite 300", "5000")]:
        s = await client.post(f"/api/v1/valuations/{model_id}/suites", json={
            "suite_name": name,
            "area": area,
            "space_type": "office",
        })
        assert s.status_code == 201
        suite_ids.append(s.json()["id"])

    # 3. Tenant
    tenant = await client.post(f"/api/v1/valuations/{model_id}/tenants", json={"name": "Acme Corp"})
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
    mkt = await client.post(f"/api/v1/valuations/{model_id}/market-profiles", json={
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
        e = await client.post(f"/api/v1/valuations/{model_id}/expenses", json=exp)
        assert e.status_code == 201

    return {
        "property_id": prop_id,
        "suite_ids": suite_ids,
        "tenant_id": tenant_id,
        "setup_valuation_id": setup.json()["id"],
    }


async def _drop_setup_valuation(client: AsyncClient, ids: dict) -> None:
    """Delete the helper's setup valuation once a test's own valuation has copied its model,
    for tests that rely on the property having exactly one valuation."""
    assert (await client.delete(f"/api/v1/valuations/{ids['setup_valuation_id']}")).status_code == 204


class TestValuationWorkflow:
    async def test_editing_inputs_clears_stale_results(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        val = await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
            "name": "Base Case", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })
        val_id = val.json()["id"]
        assert (await client.post(f"/api/v1/valuations/{val_id}/run")).status_code == 200

        renamed = (await client.put(f"/api/v1/valuations/{val_id}", json={"name": "Renamed"})).json()
        assert renamed["status"] == "completed" and renamed["result_npv"] is not None
        same = (await client.put(f"/api/v1/valuations/{val_id}", json={"discount_rate": "0.080000"})).json()
        assert same["status"] == "completed"

        edited = (await client.put(f"/api/v1/valuations/{val_id}", json={"discount_rate": "0.09"})).json()
        assert edited["status"] == "draft"
        assert edited["result_npv"] is None and edited["result_irr"] is None
        sens = await client.get(f"/api/v1/valuations/{val_id}/reports/sensitivity")
        assert sens.status_code != 200

    async def test_update_rejects_null_required_field_and_out_of_range_rate(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        val = await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
            "name": "Base Case", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })
        url = f"/api/v1/valuations/{val.json()['id']}"
        assert (await client.put(url, json={"discount_rate": None})).status_code == 422
        assert (await client.put(url, json={"interest_rate": "6.5"})).status_code == 422
        assert (await client.put(url, json={"loan_amount": None})).status_code == 200  # nullable: clears the loan

    async def test_investment_memo_handles_non_latin_names(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        await client.put(f"/api/v1/properties/{ids['property_id']}", json={"name": "Tower — East “A” 東京"})
        val = await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
            "name": "Base – Case", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })
        val_id = val.json()["id"]
        assert (await client.post(f"/api/v1/valuations/{val_id}/run")).status_code == 200
        pdf = await client.get(f"/api/v1/valuations/{val_id}/reports/investment-memo.pdf")
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF")

    async def test_failed_run_is_recorded(self, client: AsyncClient):
        prop = await client.post("/api/v1/properties", json={
            "name": "No Assumptions", "property_type": "seniors_housing", "total_area": "80", "area_unit": "unit",
            "analysis_start_date": "2026-01-01",
        })
        val = await client.post(f"/api/v1/properties/{prop.json()['id']}/valuations", json={
            "name": "Missing JSON", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })
        run = await client.post(f"/api/v1/valuations/{val.json()['id']}/run")
        assert run.status_code == 400
        saved = (await client.get(f"/api/v1/valuations/{val.json()['id']}")).json()
        assert saved["status"] == "failed"
        assert "unit mix" in saved["error_message"]

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

        # Rent roll Excel export
        rr_xlsx_resp = await client.get(f"/api/v1/valuations/{val_id}/reports/rent-roll.xlsx")
        assert rr_xlsx_resp.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in rr_xlsx_resp.headers.get("content-type", "")
        assert rr_xlsx_resp.content[:2] == b"PK"

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
        assert float(full["key_metrics"]["weighted_avg_lease_term_years"]) > 0

    async def test_marina_property_saved_valuation_runs_with_marina_engine(self, client: AsyncClient):
        prop = await client.post("/api/v1/properties", json={
            "name": "Harbor Point Marina",
            "property_type": "marina",
            "total_area": "300",
            "area_unit": "unit",
            "analysis_start_date": "2026-01-01",
            "analysis_period_months": 120,
            "fiscal_year_end_month": 12,
        })
        assert prop.status_code == 201
        prop_id = prop.json()["id"]

        val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Base Marina",
            "discount_rate": "0.095",
            "exit_cap_rate": "0.0825",
            "use_mid_year_convention": True,
            "loan_amount": "9800000",
            "interest_rate": "0.0675",
            "amortization_months": 300,
            "loan_term_months": 84,
            "io_period_months": 12,
        })
        assert val.status_code == 201
        val_id = val.json()["id"]

        run = await client.post(f"/api/v1/valuations/{val_id}/run")
        assert run.status_code == 200
        result = run.json()
        assert result["status"] == "completed"
        assert len(result["annual_cash_flows"]) == 10
        y1 = result["annual_cash_flows"][0]
        assert float(y1["gross_potential_income"]) > 0
        assert float(y1["net_operating_income"]) > 0

        assert (await client.get(f"/api/v1/valuations/{val_id}")).json()["engine_outdated"] is False

        # Marina path does not use lease-based records.
        assert result["rent_roll"] == []
        assert result["lease_expiration_schedule"] == []

        full = await client.get(f"/api/v1/valuations/{val_id}/reports/full")
        assert full.status_code == 200
        full_data = full.json()
        assert full_data["status"] == "completed"
        assert len(full_data["annual_cash_flows"]) == 10
        assert full_data["key_metrics"] is not None
        assert float(full_data["key_metrics"]["terminal_value"]) > 0

    async def test_seniors_saved_valuation_uses_ramp_leverage_and_balloon(self, client: AsyncClient):
        prop = await client.post("/api/v1/properties", json={
            "name": "Summit Seniors",
            "property_type": "seniors_housing",
            "total_area": "120",
            "area_unit": "unit",
            "analysis_start_date": "2026-01-01",
            "analysis_period_months": 120,
            "fiscal_year_end_month": 12,
        })
        assert prop.status_code == 201
        prop_id = prop.json()["id"]

        assumptions = {
            "community_name": "Summit Seniors",
            "unit_types": [
                {
                    "name": "AL Studio",
                    "acuity": "assisted_living",
                    "unit_type": "studio",
                    "count": 50,
                    "avg_sf": "350",
                    "monthly_base_fee": "5200",
                    "stabilized_occupancy": "0.90",
                    "annual_turnover_rate": "0.35",
                    "care_level_tiers": [
                        {"name": "Level 1", "monthly_surcharge": "500", "pct_of_residents": "0.50"}
                    ],
                }
            ],
            "expenses": [{"name": "Payroll", "category": "labor", "annual_fixed": "750000"}],
            "capex": [{"name": "Reserves", "annual_per_unit": "300"}],
            "occupancy_ramp": {
                "start_occupancy": "0.20",
                "monthly_absorption_units": "4",
                "stabilization_month": 24,
            },
            "valuation": {
                "hold_years": 4,
                "terminal_noi_growth_pct": "0.02",
                "fee_growth_rate": "0.00",
                "expense_growth_rate": "0.00",
                "initial_purchase_price": "20000000",
                "levered_discount_rate": "0.20",
            },
        }

        with_high_levered_dr = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Seniors With Levered DR",
            "discount_rate": "0.09",
            "exit_cap_rate": "0.075",
            "use_mid_year_convention": True,
            "loan_amount": "12000000",
            "interest_rate": "0.065",
            "amortization_months": 360,
            "loan_term_months": 24,
            "io_period_months": 0,
            "seniors_housing_assumptions_json": json.dumps(assumptions),
        })
        assert with_high_levered_dr.status_code == 201
        high_dr_id = with_high_levered_dr.json()["id"]

        assumptions_default_dr = json.loads(json.dumps(assumptions))
        assumptions_default_dr["valuation"].pop("levered_discount_rate", None)
        with_default_levered_dr = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Seniors Default Levered DR",
            "discount_rate": "0.09",
            "exit_cap_rate": "0.075",
            "use_mid_year_convention": True,
            "loan_amount": "12000000",
            "interest_rate": "0.065",
            "amortization_months": 360,
            "loan_term_months": 24,
            "io_period_months": 0,
            "seniors_housing_assumptions_json": json.dumps(assumptions_default_dr),
        })
        assert with_default_levered_dr.status_code == 201
        default_dr_id = with_default_levered_dr.json()["id"]

        high_dr_run = await client.post(f"/api/v1/valuations/{high_dr_id}/run")
        default_dr_run = await client.post(f"/api/v1/valuations/{default_dr_id}/run")
        assert high_dr_run.status_code == 200
        assert default_dr_run.status_code == 200
        assert (await client.get(f"/api/v1/valuations/{default_dr_id}")).json()["engine_outdated"] is False

        high_data = high_dr_run.json()
        default_data = default_dr_run.json()
        high_y1 = high_data["annual_cash_flows"][0]
        high_y4 = high_data["annual_cash_flows"][3]
        high_y2 = high_data["annual_cash_flows"][1]

        # Occupancy ramp should increase effective revenue over time when growth is set to zero.
        assert float(high_y4["gross_potential_income"]) > float(high_y1["gross_potential_income"])
        # Year-2 maturity balloon should be present in saved valuation response.
        assert float(high_y2["balloon_payment"]) < 0
        # Levered discount rate should impact reported NPV for levered runs.
        assert float(high_data["key_metrics"]["npv"]) < float(default_data["key_metrics"]["npv"])

    async def test_seniors_saved_equity_multiple_subtracts_exit_balance(self, client: AsyncClient):
        prop = await client.post("/api/v1/properties", json={
            "name": "Seniors Equity Multiple",
            "property_type": "seniors_housing",
            "total_area": "100",
            "area_unit": "unit",
            "analysis_start_date": "2026-01-01",
            "analysis_period_months": 120,
            "fiscal_year_end_month": 12,
        })
        assert prop.status_code == 201
        prop_id = prop.json()["id"]

        assumptions = {
            "community_name": "Seniors Equity Multiple",
            "unit_types": [
                {
                    "name": "AL Studio",
                    "acuity": "assisted_living",
                    "unit_type": "studio",
                    "count": 10,
                    "avg_sf": "300",
                    "monthly_base_fee": "5000",
                }
            ],
            "expenses": [{"name": "Payroll", "category": "labor", "annual_fixed": "100000"}],
            "valuation": {
                "hold_years": 4,
                "initial_purchase_price": "20000000",
            },
        }

        created = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Seniors Levered EM",
            "discount_rate": "0.09",
            "exit_cap_rate": "0.08",
            "loan_amount": "12000000",
            "interest_rate": "0.065",
            "amortization_months": 360,
            "loan_term_months": 120,
            "io_period_months": 0,
            "seniors_housing_assumptions_json": json.dumps(assumptions),
        })
        assert created.status_code == 201
        val_id = created.json()["id"]

        run = await client.post(f"/api/v1/valuations/{val_id}/run")
        assert run.status_code == 200
        data = run.json()

        debt = SHDebtInput(
            loan_amount=Decimal("12000000"),
            interest_rate=Decimal("0.065"),
            amortization_months=360,
            term_months=120,
            io_period_months=0,
        )
        _, _, balances = sh_build_debt_service(debt, 4)
        exit_balance = balances[-1]
        levered_sum = sum(Decimal(row["levered_cash_flow"]) for row in data["annual_cash_flows"])
        terminal_value = Decimal(data["key_metrics"]["terminal_value"])
        expected = (
            (levered_sum + terminal_value - exit_balance)
            / (Decimal("20000000") - Decimal("12000000"))
        )
        actual = Decimal(data["key_metrics"]["equity_multiple"])
        assert abs(actual - expected) < Decimal("0.000001")

    async def test_saved_seniors_zero_interest_debt_is_applied(self, client: AsyncClient):
        prop = await client.post("/api/v1/properties", json={
            "name": "Seniors Zero Interest",
            "property_type": "seniors_housing",
            "total_area": "80",
            "area_unit": "unit",
            "analysis_start_date": "2026-01-01",
            "analysis_period_months": 120,
            "fiscal_year_end_month": 12,
        })
        assert prop.status_code == 201
        prop_id = prop.json()["id"]

        assumptions = {
            "community_name": "Seniors Zero Interest",
            "unit_types": [
                {
                    "name": "AL Studio",
                    "acuity": "assisted_living",
                    "unit_type": "studio",
                    "count": 8,
                    "avg_sf": "300",
                    "monthly_base_fee": "4500",
                }
            ],
            "expenses": [{"name": "Payroll", "category": "labor", "annual_fixed": "50000"}],
            "valuation": {"hold_years": 2, "initial_purchase_price": "10000000"},
        }

        created = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Seniors Zero Interest Val",
            "discount_rate": "0.09",
            "exit_cap_rate": "0.08",
            "loan_amount": "5000000",
            "interest_rate": "0.0",
            "amortization_months": 120,
            "loan_term_months": 24,
            "io_period_months": 0,
            "seniors_housing_assumptions_json": json.dumps(assumptions),
        })
        assert created.status_code == 201
        val_id = created.json()["id"]

        run = await client.post(f"/api/v1/valuations/{val_id}/run")
        assert run.status_code == 200
        y1 = run.json()["annual_cash_flows"][0]
        assert float(y1["debt_service"]) < 0

    async def test_saved_seniors_respects_zero_exit_costs_pct(self, client: AsyncClient):
        prop = await client.post("/api/v1/properties", json={
            "name": "Seniors Zero Exit Costs",
            "property_type": "seniors_housing",
            "total_area": "80",
            "area_unit": "unit",
            "analysis_start_date": "2026-01-01",
            "analysis_period_months": 120,
            "fiscal_year_end_month": 12,
        })
        assert prop.status_code == 201
        prop_id = prop.json()["id"]

        assumptions = {
            "community_name": "Seniors Zero Exit Costs",
            "unit_types": [
                {
                    "name": "AL Studio",
                    "acuity": "assisted_living",
                    "unit_type": "studio",
                    "count": 8,
                    "avg_sf": "300",
                    "monthly_base_fee": "4500",
                }
            ],
            "expenses": [{"name": "Payroll", "category": "labor", "annual_fixed": "50000"}],
            "valuation": {"hold_years": 2, "initial_purchase_price": "10000000"},
        }

        zero_exit = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Seniors Zero Exit Costs",
            "discount_rate": "0.09",
            "exit_cap_rate": "0.08",
            "exit_costs_pct": "0.0",
            "seniors_housing_assumptions_json": json.dumps(assumptions),
        })
        two_pct_exit = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Seniors Two Percent Exit Costs",
            "discount_rate": "0.09",
            "exit_cap_rate": "0.08",
            "exit_costs_pct": "0.02",
            "seniors_housing_assumptions_json": json.dumps(assumptions),
        })
        assert zero_exit.status_code == 201
        assert two_pct_exit.status_code == 201

        zero_run = await client.post(f"/api/v1/valuations/{zero_exit.json()['id']}/run")
        two_run = await client.post(f"/api/v1/valuations/{two_pct_exit.json()['id']}/run")
        assert zero_run.status_code == 200
        assert two_run.status_code == 200

        zero_terminal = Decimal(zero_run.json()["key_metrics"]["terminal_value"])
        two_terminal = Decimal(two_run.json()["key_metrics"]["terminal_value"])
        assert zero_terminal > two_terminal

    async def test_stub_analysis_period_rejected(self, client: AsyncClient):
        """Analysis periods are whole years; a partial final year is not allowed."""
        body = {
            "name": "Stub Period", "property_type": "office", "total_area": "10000", "area_unit": "sf",
            "analysis_start_date": "2026-01-01", "analysis_period_months": 126,
        }
        assert (await client.post("/api/v1/properties", json=body)).status_code == 422
        prop = await client.post("/api/v1/properties", json={**body, "analysis_period_months": 120})
        assert prop.status_code == 201
        upd = await client.put(f"/api/v1/properties/{prop.json()['id']}", json={"analysis_period_months": 13})
        assert upd.status_code == 422

    async def test_mid_month_analysis_start_moves_to_next_month(self, client: AsyncClient):
        """Monthly periods run 1st to month end; a mid-month start would skip days every month."""
        body = {"name": "Mid Month", "property_type": "office", "total_area": "10000", "area_unit": "sf"}
        prop = await client.post("/api/v1/properties", json={**body, "analysis_start_date": "2026-12-15"})
        assert prop.json()["analysis_start_date"] == "2027-01-01"
        assert (await client.post("/api/v1/properties", json=body)).json()["analysis_start_date"].endswith("-01")
        pid = prop.json()["id"]
        upd = await client.put(f"/api/v1/properties/{pid}", json={"analysis_start_date": "2026-02-10"})
        assert upd.json()["analysis_start_date"] == "2026-03-01"
        val = {"name": "V", "discount_rate": "0.08", "exit_cap_rate": "0.065", "analysis_start_date_override": "2026-03-01"}
        created = await client.post(f"/api/v1/properties/{pid}/valuations", json=val)
        assert created.json()["analysis_start_date_override"] == "2026-03-01"
        val["analysis_start_date_override"] = "2026-03-02"
        created = await client.post(f"/api/v1/properties/{pid}/valuations", json=val)
        assert created.json()["analysis_start_date_override"] == "2026-04-01"

    async def test_saved_marina_zero_interest_and_numeric_string_assumptions(self, client: AsyncClient):
        prop = await client.post("/api/v1/properties", json={
            "name": "Marina Zero Interest",
            "property_type": "marina",
            "total_area": "100",
            "area_unit": "unit",
            "analysis_start_date": "2026-01-01",
            "analysis_period_months": 120,
            "fiscal_year_end_month": 12,
        })
        assert prop.status_code == 201
        prop_id = prop.json()["id"]

        assumptions = {
            "slip_classes": [
                {
                    "name": "Wet",
                    "kind": "wet_slip",
                    "length_class": "30-45 ft",
                    "utility_service_level": "fifty_amp",
                    "count": 10,
                    "annual_contract_share": "0.60",
                    "seasonal_contract_share": "0.20",
                    "transient_share": "0.20",
                    "annual_contract_rate": "7600",
                    "seasonal_contract_rate": "4200",
                    "transient_daily_rate": "58",
                }
            ],
            "demand": {
                "monthly_seasonality": ["1"] * 12,
                "monthly_weather_shock_pct": ["0"] * 12,
            },
            "operating_cost_lines": [{"name": "dock_labor", "annual_fixed": "0"}],
            "cyclical_costs": [
                {"name": "storm", "base_amount": "1000", "first_year": "1", "every_n_years": "1"}
            ],
            "valuation": {"hold_years": "2", "initial_purchase_price": "10000000"},
        }

        base_created = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Marina Default Interest",
            "discount_rate": "0.09",
            "exit_cap_rate": "0.08",
            "loan_amount": "5000000",
            "amortization_months": 120,
            "loan_term_months": 24,
            "io_period_months": 0,
            "marina_assumptions_json": json.dumps(assumptions),
        })
        zero_created = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Marina Zero Interest",
            "discount_rate": "0.09",
            "exit_cap_rate": "0.08",
            "loan_amount": "5000000",
            "interest_rate": "0.0",
            "amortization_months": 120,
            "loan_term_months": 24,
            "io_period_months": 0,
            "marina_assumptions_json": json.dumps(assumptions),
        })
        assert base_created.status_code == 201
        assert zero_created.status_code == 201

        base_run = await client.post(f"/api/v1/valuations/{base_created.json()['id']}/run")
        zero_run = await client.post(f"/api/v1/valuations/{zero_created.json()['id']}/run")
        assert base_run.status_code == 200
        assert zero_run.status_code == 200
        # The generic exit-cap grid does not apply to marina valuations
        sens = await client.get(f"/api/v1/valuations/{base_created.json()['id']}/reports/sensitivity")
        assert sens.status_code == 400

        base_ds = abs(float(base_run.json()["annual_cash_flows"][0]["debt_service"]))
        zero_ds = abs(float(zero_run.json()["annual_cash_flows"][0]["debt_service"]))
        assert zero_ds < base_ds

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
        assert "marina" in data["property_types"]
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

    async def test_valuation_analysis_start_date_override(self, client: AsyncClient):
        prop = await client.post("/api/v1/properties", json={
            "name": "Start Date Override Property",
            "property_type": "office",
            "total_area": "10000",
            "area_unit": "sf",
            "analysis_start_date": "2025-01-01",
            "analysis_period_months": 24,
        })
        assert prop.status_code == 201
        prop_id = prop.json()["id"]
        # The rent roll belongs to a valuation; the override case below copies it
        setup = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Setup", "discount_rate": "0.08", "exit_cap_rate": "0.065"})
        assert setup.status_code == 201

        suite = await client.post(f"/api/v1/valuations/{setup.json()['id']}/suites", json={
            "suite_name": "Suite 100",
            "area": "10000",
            "space_type": "office",
        })
        assert suite.status_code == 201
        suite_id = suite.json()["id"]

        lease = await client.post(f"/api/v1/suites/{suite_id}/leases", json={
            "lease_start_date": "2025-01-01",
            "lease_end_date": "2025-12-31",
            "base_rent_per_unit": "30.00",
            "escalation_type": "flat",
            "recovery_type": "nnn",
        })
        assert lease.status_code == 201

        created = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Start Override Case",
            "discount_rate": "0.08",
            "exit_cap_rate": "0.065",
            "analysis_start_date_override": "2026-01-01",
        })
        assert created.status_code == 201
        val = created.json()
        assert val["analysis_start_date_override"] == "2026-01-01"
        val_id = val["id"]
        mkt = await client.post(f"/api/v1/valuations/{val_id}/market-profiles", json={
            "space_type": "office",
            "market_rent_per_unit": "35.00",
        })
        assert mkt.status_code == 201

        run_override = await client.post(f"/api/v1/valuations/{val_id}/run")
        assert run_override.status_code == 200
        data_override = run_override.json()
        assert data_override["rent_roll"][0]["lease_type"] == "vacant"
        assert data_override["key_metrics"]["weighted_avg_lease_term_years"] is None

        updated = await client.put(f"/api/v1/valuations/{val_id}", json={
            "analysis_start_date_override": None,
        })
        assert updated.status_code == 200
        assert updated.json()["analysis_start_date_override"] is None

        run_default = await client.post(f"/api/v1/valuations/{val_id}/run")
        assert run_default.status_code == 200
        data_default = run_default.json()
        assert data_default["rent_roll"][0]["lease_type"] == "in_place"
        assert float(data_default["key_metrics"]["weighted_avg_lease_term_years"]) > 0

    async def test_cached_full_report_preserves_pv_metrics(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        prop_id = ids["property_id"]

        val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "PV Cache Test",
            "discount_rate": "0.08",
            "exit_cap_rate": "0.065",
            "use_mid_year_convention": True,
        })
        assert val.status_code == 201
        val_id = val.json()["id"]

        run = await client.post(f"/api/v1/valuations/{val_id}/run")
        assert run.status_code == 200
        run_data = run.json()

        full_resp = await client.get(f"/api/v1/valuations/{val_id}/reports/full")
        assert full_resp.status_code == 200
        full = full_resp.json()

        run_metrics = run_data["key_metrics"]
        full_metrics = full["key_metrics"]
        full_pv_cfs = Decimal(full_metrics["pv_of_cash_flows"])
        full_pv_tv = Decimal(full_metrics["pv_of_terminal_value"])
        run_pv_cfs = Decimal(run_metrics["pv_of_cash_flows"])
        run_pv_tv = Decimal(run_metrics["pv_of_terminal_value"])
        assert full_pv_cfs > 0
        assert full_pv_tv > 0
        assert abs(full_pv_cfs - run_pv_cfs) < Decimal("0.01")
        assert abs(full_pv_tv - run_pv_tv) < Decimal("0.01")

        annual_cfs = [AnnualCashFlowSummary(**row) for row in full["annual_cash_flows"]]
        expected_pv_cfs, expected_pv_tv, _ = discount_cash_flows(
            annual_cfs=annual_cfs,
            terminal_value=Decimal(full_metrics["terminal_value"]),
            discount_rate=Decimal("0.08"),
            use_mid_year=True,
        )
        assert abs(full_pv_cfs - expected_pv_cfs) < Decimal("0.01")
        assert abs(full_pv_tv - expected_pv_tv) < Decimal("0.01")


class TestPurchasePriceReturns:
    async def test_purchase_price_levered_returns_and_sensitivity(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        prop_id = ids["property_id"]

        val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Acquisition Case",
            "discount_rate": "0.08",
            "exit_cap_rate": "0.065",
            "exit_costs_pct": "0.02",
            "purchase_price": "4000000",
            "acquisition_costs_pct": "0.015",
            "direct_cap_rate": "0.06",
            "exit_deduct_forward_capital": True,
            "loan_amount": "2400000",
            "interest_rate": "0.055",
            "amortization_months": 360,
            "loan_term_months": 120,
            "io_period_months": 24,
            "loan_fees_pct": "0.01",
        })
        assert val.status_code == 201
        val_id = val.json()["id"]
        assert float(val.json()["purchase_price"]) == 4_000_000

        run = await client.post(f"/api/v1/valuations/{val_id}/run")
        assert run.status_code == 200
        km = run.json()["key_metrics"]
        ret = km["returns"]
        assert ret is not None
        assert float(ret["total_investment"]) == 4_060_000
        assert float(ret["loan_to_value"]) == 0.6
        assert ret["levered_irr"] is not None
        assert ret["year1_dscr"] is not None
        # IRR is now measured at the purchase price, not the DCF value
        assert km["irr"] == ret["unlevered_irr"]
        assert abs(float(km["going_in_cap_rate"]) - float(km["year1_noi"]) / 4_000_000) < 1e-9
        assert abs(float(km["direct_cap_value"]) - float(km["year1_noi"]) / 0.06) < 1
        assert float(km["terminal_capital_deduction_amount"]) >= 0

        # Cached results keep returns
        cached = await client.get(f"/api/v1/valuations/{val_id}/reports/key-metrics")
        assert cached.status_code == 200
        assert cached.json()["returns"]["levered_irr"] == ret["levered_irr"]
        assert cached.json()["direct_cap_value"] is not None

        read = await client.get(f"/api/v1/valuations/{val_id}")
        assert read.json()["result_levered_irr"] is not None

        sens = await client.get(f"/api/v1/valuations/{val_id}/reports/sensitivity")
        assert sens.status_code == 200
        body = sens.json()
        assert len(body["discount_rates"]) == 5
        assert len(body["exit_cap_rates"]) == 5
        assert abs(float(body["values"][2][2]) - float(km["npv"])) < 1
        assert all(v is not None for v in body["irr_by_exit_cap"])

    async def test_sensitivity_requires_run(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        val = await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
            "name": "Draft", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })
        resp = await client.get(f"/api/v1/valuations/{val.json()['id']}/reports/sensitivity")
        assert resp.status_code == 400


class TestGrowthScheduleValuation:
    async def test_expense_schedule_changes_results(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        prop_id = ids["property_id"]
        body = {"name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"}
        base = await client.post(f"/api/v1/properties/{prop_id}/valuations", json=body)
        base_run = (await client.post(f"/api/v1/valuations/{base.json()['id']}/run")).json()

        sched = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            **body, "name": "Schedule", "cpi_rate": "0.02", "cpi_schedule": ["0.02", "0.04"],
        })
        assert sched.status_code == 201, sched.text
        # Market leasing is per valuation: only this one gets the growth schedule
        sched_id = sched.json()["id"]
        mp = (await client.get(f"/api/v1/valuations/{sched_id}/market-profiles")).json()[0]
        upd = await client.put(f"/api/v1/valuations/{sched_id}/market-profiles/{mp['id']}", json={
            "rent_growth_schedule": ["0.00", "0.10"],
        })
        assert upd.status_code == 200, upd.text
        assert [float(v) for v in sched.json()["cpi_schedule"]] == [0.02, 0.04]
        sched_run = (await client.post(f"/api/v1/valuations/{sched.json()['id']}/run")).json()
        assert sched_run["status"] == "completed"
        assert float(sched_run["key_metrics"]["npv"]) > float(base_run["key_metrics"]["npv"])


class TestVacancyOptionsApi:
    async def test_credit_exclusion_and_reduce_toggle(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        prop_id = ids["property_id"]
        body = {"name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"}
        base = await client.post(f"/api/v1/properties/{prop_id}/valuations", json=body)
        base_cf = (await client.post(f"/api/v1/valuations/{base.json()['id']}/run")).json()["annual_cash_flows"][0]

        # The newest valuation's model is what the next one copies: flag the lease there
        leases = (await client.get(f"/api/v1/valuations/{base.json()['id']}/leases")).json()
        upd = await client.put(f"/api/v1/leases/{leases[0]['id']}", json={"exclude_from_general_vacancy": True})
        assert upd.status_code == 200, upd.text
        assert upd.json()["exclude_from_general_vacancy"] is True

        val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            **body, "name": "Options", "reduce_general_vacancy_by_downtime": True,
        })
        assert val.json()["reduce_general_vacancy_by_downtime"] is True
        cf = (await client.post(f"/api/v1/valuations/{val.json()['id']}/run")).json()["annual_cash_flows"][0]
        assert float(cf["general_vacancy_loss"]) > float(base_cf["general_vacancy_loss"])
        assert float(cf["credit_loss"]) > float(base_cf["credit_loss"])


class TestExpenseBasisApi:
    async def test_per_area_expense_matches_total(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        prop_id = ids["property_id"]
        body = {"name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"}
        base = await client.post(f"/api/v1/properties/{prop_id}/valuations", json=body)
        base_cf = (await client.post(f"/api/v1/valuations/{base.json()['id']}/run")).json()["annual_cash_flows"][0]

        # 15,000 SF x $2.00 = $30,000, same as adding a $30,000 total expense
        exp = await client.post(f"/api/v1/valuations/{base.json()['id']}/expenses", json={
            "category": "utilities", "base_year_amount": "2.00", "amount_basis": "per_area",
            "growth_rate_pct": "0.03", "is_recoverable": False,
        })
        assert exp.status_code == 201, exp.text
        assert exp.json()["amount_basis"] == "per_area"
        run = await client.post(f"/api/v1/valuations/{base.json()['id']}/run")
        cf = run.json()["annual_cash_flows"][0]
        assert abs(float(base_cf["operating_expenses"]) - float(cf["operating_expenses"]) - 30000) < 2000
        assert float(cf["expense_detail"]["utilities"]) == -30000.0


class TestUponExpirationApi:
    async def test_lease_options_and_mla_chain(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        prop_id = ids["property_id"]
        leases = (await client.get(f"/api/v1/suites/{ids['suite_ids'][0]}/leases")).json()
        upd = await client.put(f"/api/v1/leases/{leases[0]['id']}", json={
            "upon_expiration": "option", "option_rent_per_unit": "28", "option_term_months": 36,
            "committed_ti_amount": "50000",
        })
        assert upd.status_code == 200, upd.text
        assert upd.json()["upon_expiration"] == "option"
        bad = await client.put(f"/api/v1/leases/{leases[0]['id']}", json={"upon_expiration": "sell"})
        assert bad.status_code == 422

        val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Options", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })
        mp_url = f"/api/v1/valuations/{val.json()['id']}/market-profiles"
        mlas = (await client.get(mp_url)).json()
        second = await client.post(mp_url, json={
            "space_type": "office_gen2", "market_rent_per_unit": "40",
        })
        chain = await client.put(f"{mp_url}/{mlas[0]['id']}", json={
            "next_profile_id": second.json()["id"],
        })
        assert chain.status_code == 200, chain.text
        assert chain.json()["next_profile_id"] == second.json()["id"]
        wrong = await client.put(f"{mp_url}/{mlas[0]['id']}", json={
            "next_profile_id": "not-a-profile",
        })
        assert wrong.status_code == 422
        cleared = await client.put(f"{mp_url}/{mlas[0]['id']}", json={
            "next_profile_id": "",
        })
        assert cleared.json()["next_profile_id"] is None
        run = await client.post(f"/api/v1/valuations/{val.json()['id']}/run")
        assert run.json()["status"] == "completed"
        assert float(run.json()["annual_cash_flows"][0]["tenant_improvements"]) <= -50000


class TestLeaseUpApi:
    async def test_vacant_suite_lease_up(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        prop_id = ids["property_id"]
        body = {"name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"}
        val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json=body)
        vid = val.json()["id"]
        vacant = next(x["id"] for x in (await client.get(f"/api/v1/valuations/{vid}/suites")).json()
                      if x["suite_name"] == "Suite 300")  # no lease
        base_cf = (await client.post(f"/api/v1/valuations/{val.json()['id']}/run")).json()["annual_cash_flows"][0]

        upd = await client.put(f"/api/v1/valuations/{vid}/suites/{vacant}", json={"lease_up_months": 12})
        assert upd.status_code == 200, upd.text
        assert upd.json()["lease_up_months"] == 12
        cf = (await client.post(f"/api/v1/valuations/{val.json()['id']}/run")).json()["annual_cash_flows"][0]
        # A full year of lease-up: Suite 300 contributes no rent in Year 1
        assert float(cf["gross_potential_rent"]) < float(base_cf["gross_potential_rent"])

        cleared = await client.put(f"/api/v1/valuations/{vid}/suites/{vacant}", json={"lease_up_months": None})
        assert cleared.json()["lease_up_months"] is None


class TestMonthlyCashFlows:
    async def test_monthly_report_reconciles_to_annual(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        val = await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
            "name": "Monthly", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })
        val_id = val.json()["id"]
        run = await client.post(f"/api/v1/valuations/{val_id}/run")
        annual = run.json()["annual_cash_flows"]

        res = await client.get(f"/api/v1/valuations/{val_id}/reports/monthly-cash-flows")
        assert res.status_code == 200
        months = res.json()
        assert len(months) == 12 * len(annual)
        for key in ("gross_potential_rent", "expense_recoveries", "operating_expenses", "net_operating_income"):
            year1 = sum(float(m[key]) for m in months if m["year"] == 1)
            assert abs(year1 - float(annual[0][key])) < 1.0, key

    async def test_monthly_report_missing_valuation(self, client: AsyncClient):
        res = await client.get("/api/v1/valuations/nope/reports/monthly-cash-flows")
        assert res.status_code == 404


class TestValuationBasisControls:
    async def test_create_rejects_mixed_nominal_and_real_basis(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        response = await client.post(
            f"/api/v1/properties/{ids['property_id']}/valuations",
            json={
                "name": "Mixed Basis",
                "discount_rate": "0.08",
                "exit_cap_rate": "0.065",
                "cash_flow_basis": "nominal",
                "discount_rate_basis": "real",
            },
        )
        assert response.status_code == 422

    async def test_update_rejects_partial_basis_mismatch(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        created = await client.post(
            f"/api/v1/properties/{ids['property_id']}/valuations",
            json={"name": "Basis", "discount_rate": "0.08", "exit_cap_rate": "0.065"},
        )
        response = await client.put(
            f"/api/v1/valuations/{created.json()['id']}",
            json={"discount_rate_basis": "real"},
        )
        assert response.status_code == 422

    async def test_basis_metadata_round_trips(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        response = await client.post(
            f"/api/v1/properties/{ids['property_id']}/valuations",
            json={
                "name": "Investment Case",
                "discount_rate": "0.08",
                "exit_cap_rate": "0.065",
                "basis_of_value": "investment_value",
                "intended_use": "Acquisition underwriting",
                "risk_treatment": "scenario_weighted",
                "cash_flow_basis": "real",
                "discount_rate_basis": "real",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["basis_of_value"] == "investment_value"
        assert body["intended_use"] == "Acquisition underwriting"
        assert body["cash_flow_basis"] == body["discount_rate_basis"] == "real"


class TestYearByYearMarketAndAmountSchedulesApi:
    async def _model(self, client: AsyncClient) -> tuple[str, str]:
        ids = await _setup_office_property(client)
        val = await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
            "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})
        val_id = val.json()["id"]
        mp = (await client.get(f"/api/v1/valuations/{val_id}/market-profiles")).json()[0]
        return val_id, mp["id"]

    async def test_vacancy_schedule_and_dollar_escalation_reach_the_run(self, client: AsyncClient):
        val_id, mp_id = await self._model(client)
        base = (await client.post(f"/api/v1/valuations/{val_id}/run")).json()["annual_cash_flows"]
        upd = await client.put(f"/api/v1/valuations/{val_id}/market-profiles/{mp_id}", json={
            "general_vacancy_schedule": ["0.05", "0.20"], "downtime_schedule": [6, 12],
            "lease_escalation_per_unit": "5.00",
        })
        assert upd.status_code == 200, upd.text
        body = upd.json()
        assert [float(v) for v in body["general_vacancy_schedule"]] == [0.05, 0.20]
        assert body["downtime_schedule"] == [6, 12]
        run = (await client.post(f"/api/v1/valuations/{val_id}/run")).json()["annual_cash_flows"]
        assert float(run[0]["general_vacancy_loss"]) == pytest.approx(float(base[0]["general_vacancy_loss"]))
        assert float(run[1]["general_vacancy_loss"]) < float(base[1]["general_vacancy_loss"])  # losses are negative
        # $5/SF a year on market leases beats the default escalation (market growth, ~3% of ~$37/SF)
        assert float(run[8]["gross_potential_rent"]) > float(base[8]["gross_potential_rent"]) + 10000

        # Both escalations at once is rejected; null clears the $ bump and empty clears a schedule
        both = await client.put(f"/api/v1/valuations/{val_id}/market-profiles/{mp_id}", json={
            "lease_escalation_pct": "0.03"})
        assert both.status_code == 422
        cleared = await client.put(f"/api/v1/valuations/{val_id}/market-profiles/{mp_id}", json={
            "lease_escalation_per_unit": None, "general_vacancy_schedule": []})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["lease_escalation_per_unit"] is None
        assert cleared.json()["general_vacancy_schedule"] == []

    async def test_leasing_commission_by_lease_year(self, client: AsyncClient):
        val_id, mp_id = await self._model(client)
        base = (await client.post(f"/api/v1/valuations/{val_id}/run")).json()["annual_cash_flows"]
        upd = await client.put(f"/api/v1/valuations/{val_id}/market-profiles/{mp_id}", json={
            "new_tenant_lc_pct_by_lease_year": ["0.10"], "renewal_lc_pct_by_lease_year": ["0.10"]})
        assert upd.status_code == 200, upd.text
        assert [float(v) for v in upd.json()["new_tenant_lc_pct_by_lease_year"]] == [0.10]
        run = (await client.post(f"/api/v1/valuations/{val_id}/run")).json()["annual_cash_flows"]
        total = lambda cfs: sum(float(c["leasing_commissions"]) for c in cfs)  # noqa: E731
        assert abs(total(run)) > abs(total(base)) > 0
        bad = await client.put(f"/api/v1/valuations/{val_id}/market-profiles/{mp_id}", json={
            "new_tenant_lc_pct_by_lease_year": ["1.5"]})
        assert bad.status_code == 422

    async def test_renewal_rent_rule(self, client: AsyncClient):
        val_id, mp_id = await self._model(client)
        mp = (await client.get(f"/api/v1/valuations/{val_id}/market-profiles")).json()[0]
        assert mp["renewal_rent_rule"] == "market"
        upd = await client.put(f"/api/v1/valuations/{val_id}/market-profiles/{mp_id}", json={
            "renewal_rent_rule": "greater_of_prior"})
        assert upd.status_code == 200 and upd.json()["renewal_rent_rule"] == "greater_of_prior"
        assert (await client.post(f"/api/v1/valuations/{val_id}/run")).status_code == 200
        bad = await client.put(f"/api/v1/valuations/{val_id}/market-profiles/{mp_id}", json={
            "renewal_rent_rule": "prior"})
        assert bad.status_code == 422

    async def test_expense_and_other_income_amount_schedules(self, client: AsyncClient):
        val_id, _ = await self._model(client)
        exp = await client.post(f"/api/v1/valuations/{val_id}/expenses", json={
            "category": "repairs_maintenance", "base_year_amount": "1", "amount_basis": "per_area",
            "growth_rate_pct": "0.10", "is_recoverable": False, "amount_schedule": ["1.00", "2.00"],
        })
        assert exp.status_code == 201, exp.text
        oi = await client.post(f"/api/v1/valuations/{val_id}/other-income", json={
            "category": "parking", "base_year_amount": "1000", "growth_rate_pct": "0",
            "amount_schedule": ["1000", "5000"],
        })
        assert oi.status_code == 201, oi.text
        assert [float(v) for v in oi.json()["amount_schedule"]] == [1000, 5000]
        cfs = (await client.post(f"/api/v1/valuations/{val_id}/run")).json()["annual_cash_flows"]
        rm = [float(cf["expense_detail"]["repairs_maintenance"]) for cf in cfs[:3]]
        # $/SF schedule times 15,000 SF; Year 3 grows from Year 2 at 10%
        assert rm == pytest.approx([-15000, -30000, -33000])
        assert [float(cf["other_income"]) for cf in cfs[:3]] == pytest.approx([1000, 5000, 5000])

    async def test_lease_rejects_unknown_rent_frequency(self, client: AsyncClient):
        val_id, _ = await self._model(client)
        suite = await client.post(f"/api/v1/valuations/{val_id}/suites", json={
            "suite_name": "Suite 900", "area": "1000", "space_type": "office"})
        resp = await client.post(f"/api/v1/suites/{suite.json()['id']}/leases", json={
            "lease_start_date": "2025-01-01", "lease_end_date": "2029-12-31", "base_rent_per_unit": "30",
            "rent_payment_frequency": "quarterly",
        })
        assert resp.status_code == 422


class TestAdditionalLoansApi:
    async def test_second_loan_adds_to_debt_service_and_survives_snapshot(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        val = await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
            "name": "Levered", "discount_rate": "0.08", "exit_cap_rate": "0.065", "purchase_price": "8000000",
            "loan_amount": "4000000", "interest_rate": "0.06", "amortization_months": 360,
        })
        assert val.status_code == 201, val.text
        val_id = val.json()["id"]
        one = (await client.post(f"/api/v1/valuations/{val_id}/run")).json()

        upd = await client.put(f"/api/v1/valuations/{val_id}", json={"additional_loans": [{
            "label": "Mezz", "loan_amount": "1000000", "interest_rate": "0.10", "io_period_months": 120,
            "loan_fees_pct": "0.01",
        }]})
        assert upd.status_code == 200, upd.text
        loans = upd.json()["additional_loans"]
        assert loans[0]["label"] == "Mezz" and float(loans[0]["loan_amount"]) == 1_000_000
        two = (await client.post(f"/api/v1/valuations/{val_id}/run")).json()
        y1_one, y1_two = one["annual_cash_flows"][0], two["annual_cash_flows"][0]
        # Interest only at 10% on $1M: $100,000 more debt service in Year 1 (service is negative)
        assert float(y1_two["debt_service"]) == pytest.approx(float(y1_one["debt_service"]) - 100_000, abs=0.01)
        assert float(two["key_metrics"]["returns"]["loan_amount"]) == 5_000_000
        assert float(two["key_metrics"]["returns"]["loan_fees"]) == 10_000

        # Submitting for review freezes the inputs, loans included, and re-runs them
        sub = await client.post(f"/api/v1/valuations/{val_id}/submit", json={"name": "Analyst"})
        assert sub.status_code in (200, 201), sub.text
        assert (await client.post(f"/api/v1/valuations/{val_id}/verify")).json()["matches"] is True

        # Copy and package export carry the loans
        copy = await client.post(f"/api/v1/valuations/{val_id}/duplicate")
        assert copy.status_code in (200, 201), copy.text
        assert copy.json()["additional_loans"][0]["label"] == "Mezz"
        package = await client.get(f"/api/v1/valuations/{copy.json()['id']}/package")
        assert package.status_code == 200, package.text
        assert "Mezz" in package.text

    async def test_clearing_and_validation(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        val_id = (await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
            "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065",
            "additional_loans": [{"loan_amount": "500000", "interest_rate": "0.08"}],
        })).json()["id"]
        bad = await client.put(f"/api/v1/valuations/{val_id}", json={
            "additional_loans": [{"loan_amount": "0", "interest_rate": "0.08"}]})
        assert bad.status_code == 422
        cleared = await client.put(f"/api/v1/valuations/{val_id}", json={"additional_loans": []})
        assert cleared.status_code == 200 and cleared.json()["additional_loans"] == []
