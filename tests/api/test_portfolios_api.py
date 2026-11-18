"""API tests for portfolios, assumption profiles, scenarios and portfolio runs."""

from decimal import Decimal

from httpx import AsyncClient

from tests.api.test_valuations_api import _drop_setup_valuation, _setup_office_property


async def _make_property(
    client: AsyncClient, name: str, ptype: str, market: str, with_valuation=True
) -> str:
    ids = await _setup_office_property(client)
    pid = ids["property_id"]
    resp = await client.put(
        f"/api/v1/properties/{pid}",
        json={
            "name": name,
            "property_type": ptype,
            "market": market,
            "ownership_pct": "0.5" if ptype == "industrial" else "1",
        },
    )
    assert resp.status_code == 200, resp.text
    if with_valuation:
        v = await client.post(
            f"/api/v1/properties/{pid}/valuations",
            json={
                "name": "Base",
                "discount_rate": "0.08",
                "exit_cap_rate": "0.065",
            },
        )
        assert v.status_code == 201
    await _drop_setup_valuation(client, ids)  # one valuation (or none) per property, as before
    return pid


class TestPortfolios:
    async def test_portfolio_crud_and_membership(self, client: AsyncClient):
        p1 = await _make_property(client, "Office A", "office", "Dallas")
        p2 = await _make_property(client, "Warehouse B", "industrial", "Dallas")
        resp = await client.post(
            "/api/v1/portfolios", json={"name": "Fund I", "property_ids": [p1]}
        )
        assert resp.status_code == 201
        pf = resp.json()
        assert [p["id"] for p in pf["properties"]] == [p1]
        assert pf["properties"][0]["market"] == "Dallas"

        interest = await client.put(
            f"/api/v1/portfolios/{pf['id']}/properties/{p1}/interest",
            json={"ownership_pct": "0.25", "currency": "USD", "commitment": "5000000"},
        )
        assert interest.status_code == 200, interest.text
        owned = interest.json()["properties"][0]
        assert float(owned["ownership_pct"]) == 0.25
        assert float(owned["commitment"]) == 5_000_000

        resp = await client.post(
            f"/api/v1/portfolios/{pf['id']}/properties", json={"property_ids": [p1, p2]}
        )
        assert len(resp.json()["properties"]) == 2
        resp = await client.delete(f"/api/v1/portfolios/{pf['id']}/properties/{p1}")
        assert [p["id"] for p in resp.json()["properties"]] == [p2]

        bad = await client.post("/api/v1/portfolios", json={"name": "X", "property_ids": ["nope"]})
        assert bad.status_code == 404
        assert len((await client.get("/api/v1/portfolios")).json()) == 1

    async def test_resolved_assumptions_hierarchy(self, client: AsyncClient):
        pid = await _make_property(client, "Warehouse", "industrial", "Dallas")
        pf = (
            await client.post("/api/v1/portfolios", json={"name": "Fund", "property_ids": [pid]})
        ).json()
        for body in [
            {"name": "House", "values": {"exit_cap_rate": "0.07", "discount_rate": "0.085"}},
            {
                "name": "Industrial",
                "property_type": "industrial",
                "values": {"exit_cap_rate": "0.06"},
            },
            {
                "name": "Ind DFW",
                "property_type": "industrial",
                "market": "dallas",
                "portfolio_id": pf["id"],
                "values": {"exit_cap_rate": "0.055"},
            },
        ]:
            r = await client.post("/api/v1/assumption-profiles", json=body)
            assert r.status_code == 201, r.text

        house_only = await client.get(f"/api/v1/properties/{pid}/resolved-assumptions")
        assert float(house_only.json()["values"]["exit_cap_rate"]) == 0.06
        in_fund = await client.get(
            f"/api/v1/properties/{pid}/resolved-assumptions?portfolio_id={pf['id']}"
        )
        body = in_fund.json()
        assert float(body["values"]["exit_cap_rate"]) == 0.055
        assert body["sources"]["exit_cap_rate"] == "profile:Ind DFW"
        assert body["sources"]["discount_rate"] == "profile:House"

        bad = await client.post(
            "/api/v1/assumption-profiles", json={"name": "x", "values": {"bogus": 1}}
        )
        assert bad.status_code == 422
        pct = await client.post(
            "/api/v1/assumption-profiles", json={"name": "x", "values": {"general_vacancy_pct": 5}}
        )
        assert pct.status_code == 422

        listed = await client.get(
            f"/api/v1/assumption-profiles?portfolio_id={pf['id']}&include_house=false"
        )
        assert [p["name"] for p in listed.json()] == ["Ind DFW"]

    async def test_portfolio_run_with_scenarios(self, client: AsyncClient):
        office = await _make_property(client, "Office A", "office", "Dallas")
        whse = await _make_property(client, "Warehouse B", "industrial", "Austin")
        pf = (
            await client.post(
                "/api/v1/portfolios",
                json={
                    "name": "Fund",
                    "property_ids": [office, whse],
                },
            )
        ).json()

        down = (
            await client.post(
                f"/api/v1/portfolios/{pf['id']}/scenarios",
                json={
                    "name": "Downside",
                    "probability_pct": "0.25",
                    "overrides": [
                        {
                            "mode": "shift",
                            "values": {"exit_cap_rate": "0.005", "market_rent_change_pct": "-0.05"},
                        },
                        {
                            "property_type": "industrial",
                            "mode": "set",
                            "values": {"renewal_probability": "0.4"},
                        },
                    ],
                },
            )
        ).json()
        assert down["overrides"][0]["mode"] == "shift"
        assert float(down["probability_pct"]) == 0.25

        run = await client.post(
            f"/api/v1/portfolios/{pf['id']}/runs", json={"scenario_ids": [down["id"]]}
        )
        assert run.status_code == 201, run.text
        body = run.json()
        base, scen = body["scenarios"]
        assert base["scenario_name"] == "Base" and scen["scenario_name"] == "Downside"
        assert all(p["error"] is None for p in base["properties"]), base["properties"]

        by_id = {p["property_id"]: p for p in base["properties"]}
        # 50% owned warehouse contributes half its value
        assert abs(float(by_id[whse]["share_value"]) - 0.5 * float(by_id[whse]["value"])) < 0.01
        total = sum(float(p["share_value"]) for p in base["properties"])
        assert abs(float(base["total_share_value"]) - total) < 0.01
        assert {g["key"] for g in base["by_property_type"]} == {"office", "industrial"}
        assert {g["key"] for g in base["by_market"]} == {"Dallas", "Austin"}
        assert len(base["share_annual_noi"]) == 10
        assert len(base["share_monthly_cash_flow"]) == 120
        assert base["portfolio_xirr_status"] in {"unique", "multiple"}
        assert base["portfolio_xirr"] is not None
        assert 0 < float(base["largest_property_pct"]) <= 1
        assert 0 < float(base["concentration_hhi"]) <= 1
        assert base["portfolio_time_weighted_return"] is not None
        assert len(base["quarterly_time_weighted_returns"]) == 40
        assert base["risk_alerts"]
        expected_weighted = (
            Decimal(base["total_share_value"]) * Decimal("0.75")
            + Decimal(scen["total_share_value"]) * Decimal("0.25")
        )
        assert Decimal(body["probability_weighted_value"]) == expected_weighted
        assert office in scen["property_value_attribution"]

        sensitivity = await client.post(
            f"/api/v1/portfolios/{pf['id']}/runs/{body['id']}/allocation-sensitivity",
            json={
                "scenario_id": None,
                "dispositions": [
                    {
                        "property_id": office,
                        "sale_date": "2028-03-31",
                        "sale_cost_pct": "0.02",
                    }
                ],
            },
        )
        assert sensitivity.status_code == 200, sensitivity.text
        sale = sensitivity.json()
        assert float(sale["net_sale_proceeds"]) > 0
        assert float(sale["remaining_share_value"]) < float(base["total_share_value"])
        assert sale["portfolio_xirr_after"] is not None
        assert sale["by_property_type"]

        # Downside lowers value
        assert float(scen["total_share_value"]) < float(base["total_share_value"])
        assert float(scen["change_vs_base_pct"]) < 0
        assert float(base["change_vs_base_pct"]) == 0

        runs = await client.get(f"/api/v1/portfolios/{pf['id']}/runs")
        assert runs.json()[0]["scenario_names"] == ["Base", "Downside"]
        fetched = await client.get(f"/api/v1/portfolios/{pf['id']}/runs/{body['id']}")
        assert fetched.json()["scenarios"][1]["total_share_value"] == scen["total_share_value"]

        # Stored property data unchanged by the scenario
        office_val = (await client.get(f"/api/v1/properties/{office}/valuations")).json()[0]["id"]
        mkt = await client.get(f"/api/v1/valuations/{office_val}/market-profiles")
        assert float(mkt.json()[0]["market_rent_per_unit"]) == 35.0

    async def test_annual_rollup_is_by_calendar_year(self, client: AsyncClient):
        """A July-June property's analysis years are split across calendar years, not filed under the start year."""
        pid = await _make_property(client, "Office FY", "office", "Dallas")
        await client.put(f"/api/v1/properties/{pid}", json={"fiscal_year_end_month": 6})
        val_id = (await client.get(f"/api/v1/properties/{pid}/valuations")).json()[0]["id"]
        moved = await client.put(f"/api/v1/valuations/{val_id}", json={"analysis_start_date_override": "2025-07-01"})
        assert moved.status_code == 200, moved.text
        pf = (
            await client.post("/api/v1/portfolios", json={"name": "FY", "property_ids": [pid]})
        ).json()
        base = (
            await client.post(f"/api/v1/portfolios/{pf['id']}/runs", json={"scenario_ids": []})
        ).json()["scenarios"][0]
        noi = {int(y): float(v) for y, v in base["share_annual_noi"].items()}
        assert sorted(noi) == list(range(2025, 2036))

        monthly = (
            await client.get(f"/api/v1/valuations/{val_id}/reports/monthly-cash-flows")
        ).json()
        cal_2026 = sum(
            float(m["net_operating_income"])
            for m in monthly
            if m["period_start"].startswith("2026")
        )
        assert abs(noi[2026] - cal_2026) < 0.01

    async def test_property_without_valuation_uses_library_rates_and_warns(self, client: AsyncClient):
        no_val = await _make_property(client, "Office C", "office", "Austin", with_valuation=False)
        pf = (await client.post("/api/v1/portfolios", json={"name": "F", "property_ids": [no_val]})).json()
        # House-wide profile fills discount/exit for the property without a valuation
        await client.post("/api/v1/assumption-profiles", json={
            "name": "Office Austin", "property_type": "office", "market": "Austin",
            "values": {"discount_rate": "0.08", "exit_cap_rate": "0.07"},
        })
        run = await client.post(f"/api/v1/portfolios/{pf['id']}/runs", json={})
        row = run.json()["scenarios"][0]["properties"][0]
        assert row["error"] is None
        assert float(row["resolved_assumptions"]["exit_cap_rate"]) == 0.07
        # Market leasing belongs to valuations, so this property has none
        assert any("no market leasing" in w for w in row["warnings"])

    async def test_property_without_rates_reports_error(self, client: AsyncClient):
        pid = await _make_property(client, "Office", "office", "Nowhere", with_valuation=False)
        pf = (
            await client.post("/api/v1/portfolios", json={"name": "F", "property_ids": [pid]})
        ).json()
        run = await client.post(f"/api/v1/portfolios/{pf['id']}/runs", json={})
        row = run.json()["scenarios"][0]["properties"][0]
        assert row["error"] and "discount rate" in row["error"]

    async def test_unknown_scenario_rejected(self, client: AsyncClient):
        pf = (await client.post("/api/v1/portfolios", json={"name": "F"})).json()
        resp = await client.post(
            f"/api/v1/portfolios/{pf['id']}/runs", json={"scenario_ids": ["x"]}
        )
        assert resp.status_code == 400

    async def test_zero_and_dated_ownership_are_respected(self, client: AsyncClient):
        pid = await _make_property(client, "Dated interest", "office", "Dallas")
        pf = (
            await client.post(
                "/api/v1/portfolios", json={"name": "Interests", "property_ids": [pid]}
            )
        ).json()
        zero = await client.put(
            f"/api/v1/portfolios/{pf['id']}/properties/{pid}/interest",
            json={"ownership_pct": "0", "currency": "USD"},
        )
        assert zero.status_code == 200
        run = (
            await client.post(f"/api/v1/portfolios/{pf['id']}/runs", json={})
        ).json()["scenarios"][0]
        assert Decimal(run["properties"][0]["share_value"]) == 0
        assert all(Decimal(value) == 0 for value in run["share_monthly_cash_flow"].values())

        dated = await client.put(
            f"/api/v1/portfolios/{pf['id']}/properties/{pid}/interest",
            json={
                "ownership_pct": "0.5", "effective_from": "2027-01-01",
                "acquisition_cost": "1000000", "currency": "USD",
            },
        )
        assert dated.status_code == 200
        run = (
            await client.post(f"/api/v1/portfolios/{pf['id']}/runs", json={})
        ).json()["scenarios"][0]
        assert Decimal(run["properties"][0]["share_value"]) == 0
        assert all(
            Decimal(value) == 0
            for key, value in run["share_monthly_cash_flow"].items()
            if key < "2027-01-01"
        )
        assert any(
            Decimal(value) != 0
            for key, value in run["share_monthly_cash_flow"].items()
            if key >= "2027-01-01"
        )
