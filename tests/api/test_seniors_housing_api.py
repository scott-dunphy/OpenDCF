from copy import deepcopy

from httpx import AsyncClient


def _payload() -> dict:
    return {
        "as_of_date": "2026-01-01",
        "community_name": "Sunrise Senior Living",
        "unit_types": [
            {
                "name": "AL Studio",
                "acuity": "assisted_living",
                "unit_type": "studio",
                "count": 40,
                "avg_sf": "350",
                "monthly_base_fee": "5400",
                "second_person_fee_monthly": "1200",
                "second_person_pct": "0.10",
                "community_fee": "5400",
                "avg_length_of_stay_months": "22",
                "stabilized_occupancy": "0.88",
                "annual_turnover_rate": "0.45",
                "care_level_tiers": [
                    {"name": "Level 1", "monthly_surcharge": "500", "pct_of_residents": "0.30"},
                    {"name": "Level 2", "monthly_surcharge": "1200", "pct_of_residents": "0.45"},
                    {"name": "Level 3", "monthly_surcharge": "2200", "pct_of_residents": "0.25"},
                ],
            },
            {
                "name": "MC Private",
                "acuity": "memory_care",
                "unit_type": "private",
                "count": 24,
                "avg_sf": "300",
                "monthly_base_fee": "6800",
                "community_fee": "6800",
                "avg_length_of_stay_months": "20",
                "stabilized_occupancy": "0.85",
                "annual_turnover_rate": "0.40",
            },
            {
                "name": "IL 1-BR",
                "acuity": "independent_living",
                "unit_type": "one_br",
                "count": 30,
                "avg_sf": "700",
                "monthly_base_fee": "3200",
                "second_person_fee_monthly": "800",
                "second_person_pct": "0.25",
                "stabilized_occupancy": "0.92",
                "annual_turnover_rate": "0.25",
            },
        ],
        "ancillary_revenue": [
            {"name": "Respite Care", "annual_fixed": "60000"},
            {"name": "Salon", "per_occupied_unit_month": "25"},
        ],
        "expenses": [
            {
                "name": "Nursing & Caregiving",
                "category": "labor",
                "annual_fixed": "800000",
                "per_occupied_unit_month": "1800",
                "applies_to_acuity": ["assisted_living", "memory_care"],
            },
            {"name": "Dietary Staff", "category": "labor", "annual_fixed": "320000"},
            {
                "name": "Food Costs",
                "category": "food",
                "per_occupied_unit_month": "350",
            },
            {
                "name": "Management Fee",
                "category": "management_fee",
                "pct_of_revenue": "0.05",
            },
            {"name": "Insurance", "category": "insurance", "annual_fixed": "200000"},
            {"name": "Marketing", "category": "marketing", "annual_fixed": "180000"},
            {"name": "Utilities", "category": "utilities", "annual_fixed": "210000"},
            {"name": "Property Taxes", "category": "property_tax", "annual_fixed": "280000"},
        ],
        "capex": [
            {"name": "Capital Reserves", "annual_per_unit": "400"},
        ],
        "valuation": {
            "hold_years": 10,
            "discount_rate": "0.09",
            "exit_cap_rate": "0.075",
            "fee_growth_rate": "0.04",
            "expense_growth_rate": "0.035",
            "initial_purchase_price": "22000000",
        },
    }


class TestSeniorsHousingValuationEndpoint:
    async def test_run_valuation(self, client: AsyncClient):
        resp = await client.post("/api/v1/seniors-housing-valuations/run", json=_payload())
        assert resp.status_code == 200
        data = resp.json()

        assert "valuation" in data
        cf = data["valuation"]["annual_cash_flows"]
        assert len(cf) == 10
        assert float(data["valuation"]["npv_unlevered"]) > 0
        assert float(data["valuation"]["terminal_value_net"]) > 0

        # Unit type detail should be present
        y1 = cf[0]
        assert len(y1["unit_type_detail"]) == 3
        assert y1["unit_type_detail"][0]["total_revenue"] != "0"

        # Expense detail
        assert len(y1["expense_detail"]) > 0

    async def test_run_with_scenarios_and_sensitivity(self, client: AsyncClient):
        payload = _payload()
        payload["scenarios"] = [
            {"name": "Downside", "occupancy_multiplier": "0.90"},
            {"name": "Upside", "rate_multiplier": "1.05"},
        ]
        payload["sensitivity"] = {
            "discount_rates": ["0.08", "0.10"],
            "exit_cap_rates": ["0.07", "0.08"],
            "occupancy_multipliers": ["0.95", "1.00"],
        }

        resp = await client.post("/api/v1/seniors-housing-valuations/run", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["scenario_results"]) == 2
        assert len(data["sensitivity_points"]) == 8

    async def test_run_with_snf_payer_mix(self, client: AsyncClient):
        payload = _payload()
        payload["unit_types"].append({
            "name": "SNF Private",
            "acuity": "skilled_nursing",
            "unit_type": "private",
            "count": 30,
            "avg_sf": "250",
            "monthly_base_fee": "0",
            "stabilized_occupancy": "0.85",
        })
        payload["snf_payer_mix"] = [
            {"payer": "medicare", "pct_of_days": "0.15", "daily_rate": "550"},
            {"payer": "medicaid", "pct_of_days": "0.55", "daily_rate": "250"},
            {"payer": "private_pay", "pct_of_days": "0.20", "daily_rate": "350"},
            {"payer": "insurance", "pct_of_days": "0.10", "daily_rate": "400"},
        ]

        resp = await client.post("/api/v1/seniors-housing-valuations/run", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        y1 = data["valuation"]["annual_cash_flows"][0]
        assert float(y1["snf_payer_revenue"]) > 0

    async def test_run_with_occupancy_ramp(self, client: AsyncClient):
        payload = _payload()
        payload["occupancy_ramp"] = {
            "start_occupancy": "0.20",
            "monthly_absorption_units": "4",
            "stabilization_month": 30,
        }

        resp = await client.post("/api/v1/seniors-housing-valuations/run", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        y1_occ = float(data["valuation"]["annual_cash_flows"][0]["avg_occupancy_pct"])
        y5_occ = float(data["valuation"]["annual_cash_flows"][4]["avg_occupancy_pct"])
        assert y5_occ > y1_occ

    async def test_run_with_debt(self, client: AsyncClient):
        payload = _payload()
        payload["debt"] = {
            "loan_amount": "15000000",
            "interest_rate": "0.065",
            "amortization_months": 360,
            "term_months": 120,
        }

        resp = await client.post("/api/v1/seniors-housing-valuations/run", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        y1 = data["valuation"]["annual_cash_flows"][0]
        assert float(y1["debt_service"]) > 0
        assert float(y1["levered_cash_flow"]) < float(y1["cash_flow_before_debt"])

    async def test_invalid_acuity_rejected(self, client: AsyncClient):
        payload = deepcopy(_payload())
        payload["unit_types"][0]["acuity"] = "invalid_acuity"
        resp = await client.post("/api/v1/seniors-housing-valuations/run", json=payload)
        assert resp.status_code == 422

    async def test_empty_unit_types_rejected(self, client: AsyncClient):
        payload = _payload()
        payload["unit_types"] = []
        resp = await client.post("/api/v1/seniors-housing-valuations/run", json=payload)
        assert resp.status_code == 422

    async def test_invalid_snf_payer_mix_sum_rejected(self, client: AsyncClient):
        payload = _payload()
        payload["snf_payer_mix"] = [
            {"payer": "medicare", "pct_of_days": "0.70", "daily_rate": "550"},
            {"payer": "medicaid", "pct_of_days": "0.50", "daily_rate": "250"},
        ]
        resp = await client.post("/api/v1/seniors-housing-valuations/run", json=payload)
        assert resp.status_code == 422

    async def test_invalid_care_level_tier_sum_rejected(self, client: AsyncClient):
        payload = _payload()
        payload["unit_types"][0]["care_level_tiers"] = [
            {"name": "Level 1", "monthly_surcharge": "500", "pct_of_residents": "0.80"},
            {"name": "Level 2", "monthly_surcharge": "900", "pct_of_residents": "0.40"},
        ]
        resp = await client.post("/api/v1/seniors-housing-valuations/run", json=payload)
        assert resp.status_code == 422
