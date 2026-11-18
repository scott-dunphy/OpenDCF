from copy import deepcopy

from httpx import AsyncClient


def _payload() -> dict:
    return {
        "as_of_date": "2026-01-01",
        "slip_classes": [
            {
                "name": "Wet 30-45",
                "kind": "wet_slip",
                "length_class": "30-45 ft",
                "utility_service_level": "fifty_amp",
                "count": 180,
                "annual_contract_share": "0.60",
                "seasonal_contract_share": "0.20",
                "transient_share": "0.20",
                "annual_contract_rate": "7600",
                "seasonal_contract_rate": "4200",
                "transient_daily_rate": "58",
            },
            {
                "name": "Dry 25-35",
                "kind": "dry_stack",
                "length_class": "25-35 ft",
                "utility_service_level": "water_only",
                "count": 120,
                "annual_contract_share": "0.45",
                "seasonal_contract_share": "0.20",
                "transient_share": "0.35",
                "annual_contract_rate": "5100",
                "seasonal_contract_rate": "2800",
                "transient_daily_rate": "42",
            },
        ],
        "demand": {
            "monthly_seasonality": [
                "0.70",
                "0.75",
                "0.90",
                "1.00",
                "1.15",
                "1.25",
                "1.30",
                "1.20",
                "1.00",
                "0.90",
                "0.80",
                "0.75",
            ],
            "monthly_weather_shock_pct": ["0"] * 12,
            "seasonal_active_months": [4, 5, 6, 7, 8, 9, 10],
            "waitlist_start_count": "30",
            "waitlist_conversion_pct": "0.55",
            "waitlist_new_demand_per_year": "12",
        },
        "operating_cost_lines": [
            {"name": "dock_labor", "annual_fixed": "620000", "per_occupied_day": "2.2"},
            {"name": "utilities", "annual_fixed": "290000", "per_occupied_day": "0.9"},
        ],
        "cyclical_costs": [
            {
                "name": "dredging",
                "base_amount": "450000",
                "first_year": 3,
                "every_n_years": 4,
                "treat_as_capex": True,
            }
        ],
        "legal_tenure": {
            "tenure_type": "fee_simple",
            "annual_submerged_land_lease": "120000",
            "annual_permit_concession_fees": "85000",
        },
        "capex_lifecycle": [
            {
                "name": "floating_docks",
                "asset_type": "floating_docks",
                "base_amount": "300000",
                "first_year": 4,
                "every_n_years": 5,
            }
        ],
        "valuation": {
            "hold_years": 7,
            "discount_rate": "0.095",
            "exit_cap_rate": "0.0825",
            "use_mid_year_convention": True,
            "terminal_noi_growth_pct": "0.02",
            "dock_replacement_reserve_per_slip_year": "220",
            "initial_purchase_price": "18000000",
        },
        "debt": {
            "loan_amount": "9800000",
            "interest_rate": "0.0675",
            "amortization_months": 300,
            "term_months": 84,
            "io_period_months": 12,
            "minimum_dscr": "1.30",
            "maximum_ltv": "0.65",
            "minimum_debt_yield": "0.09",
        },
    }


class TestMarinaValuationEndpoint:
    async def test_run_marina_valuation(self, client: AsyncClient):
        resp = await client.post("/api/v1/marina-valuations/run", json=_payload())
        assert resp.status_code == 200
        data = resp.json()

        assert "valuation" in data
        assert len(data["valuation"]["annual_cash_flows"]) == 7
        assert float(data["valuation"]["npv_unlevered"]) > 0
        assert float(data["valuation"]["terminal_value_after_tenure_risk"]) > 0
        assert data["scenario_results"] == []
        assert data["sensitivity_points"] == []

    async def test_run_marina_with_scenarios_sensitivity_and_debt_sizing(self, client: AsyncClient):
        payload = _payload()
        payload["scenarios"] = [
            {
                "name": "Storm",
                "occupancy_multiplier": "0.95",
                "weather_shock_additive_pct": "0.15",
            },
            {
                "name": "Upside",
                "occupancy_multiplier": "1.05",
                "rate_multiplier": "1.05",
            },
        ]
        payload["sensitivity"] = {
            "discount_rates": ["0.085", "0.095"],
            "exit_cap_rates": ["0.075", "0.085"],
            "occupancy_multipliers": ["0.95", "1.00"],
        }
        payload["include_debt_sizing"] = True

        resp = await client.post("/api/v1/marina-valuations/run", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["scenario_results"]) == 2
        assert len(data["sensitivity_points"]) == 8
        assert data["debt_sizing"] is not None
        assert float(data["debt_sizing"]["recommended_loan_amount"]) > 0

    async def test_invalid_slip_shares_rejected(self, client: AsyncClient):
        payload = deepcopy(_payload())
        payload["slip_classes"][0]["annual_contract_share"] = "0.70"
        payload["slip_classes"][0]["seasonal_contract_share"] = "0.20"
        payload["slip_classes"][0]["transient_share"] = "0.20"

        resp = await client.post("/api/v1/marina-valuations/run", json=payload)
        assert resp.status_code == 422

    async def test_additional_revenue_lines_are_applied(self, client: AsyncClient):
        base_payload = _payload()
        with_additional = deepcopy(base_payload)
        with_additional["additional_revenue_lines"] = [
            {"name": "Boat Club Memberships", "annual_fixed": "100000", "growth_pct": "0.03"}
        ]

        base_resp = await client.post("/api/v1/marina-valuations/run", json=base_payload)
        add_resp = await client.post("/api/v1/marina-valuations/run", json=with_additional)
        assert base_resp.status_code == 200
        assert add_resp.status_code == 200

        base_y1 = base_resp.json()["valuation"]["annual_cash_flows"][0]
        add_y1 = add_resp.json()["valuation"]["annual_cash_flows"][0]
        assert float(add_y1["additional_revenue"]) > 0
        assert float(add_y1["potential_gross_revenue"]) > float(base_y1["potential_gross_revenue"])
