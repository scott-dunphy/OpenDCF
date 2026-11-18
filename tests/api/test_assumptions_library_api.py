"""Assumptions library API: CBSA on properties, ranged profiles, template round trip."""
import io
from decimal import Decimal

from httpx import AsyncClient
from openpyxl import load_workbook

from tests.api.test_portfolios_api import _make_property

PROFILES = "/api/v1/assumption-profiles"


async def test_property_gets_cbsa_from_zip_and_keeps_a_chosen_one(client: AsyncClient):
    pid = await _make_property(client, "Whse", "industrial", "Dallas", with_valuation=False)
    p = (await client.put(f"/api/v1/properties/{pid}", json={"zip_code": "75201"})).json()
    assert p["cbsa_code"] == "19100" and p["cbsa_title"] == "Dallas-Fort Worth-Arlington, TX"
    p = (await client.put(f"/api/v1/properties/{pid}", json={"cbsa_code": "28140", "quality_score": "4"})).json()
    assert p["cbsa_code"] == "28140" and float(p["quality_score"]) == 4
    p = (await client.put(f"/api/v1/properties/{pid}", json={"cbsa_code": ""})).json()
    assert p["cbsa_code"] is None
    assert (await client.put(f"/api/v1/properties/{pid}", json={"cbsa_code": "99999"})).status_code == 422
    assert (await client.put(f"/api/v1/properties/{pid}", json={"quality_score": "6"})).status_code == 422
    p = (await client.put(f"/api/v1/properties/{pid}", json={"quality_score": None})).json()
    assert p["quality_score"] is None


async def test_new_property_cbsa_from_zip(client: AsyncClient):
    r = await client.post("/api/v1/properties", json={
        "name": "KC", "property_type": "office", "total_area": "1000", "area_unit": "sf",
        "analysis_start_date": "2026-01-01", "zip_code": "66210",
    })
    assert r.status_code == 201 and r.json()["cbsa_code"] == "28140"


async def test_cbsa_endpoints(client: AsyncClient):
    assert (await client.get("/api/v1/cbsas?zip=75201")).json()[0]["code"] == "19100"
    assert (await client.get("/api/v1/cbsas?q=dallas")).json()[0]["code"] == "19100"
    assert (await client.get("/api/v1/cbsas/99999")).status_code == 404


async def test_ranged_profile_positions_by_quality(client: AsyncClient):
    pid = await _make_property(client, "Whse", "industrial", "Dallas", with_valuation=False)
    await client.put(f"/api/v1/properties/{pid}", json={"zip_code": "75201", "quality_score": "5"})
    body = {
        "name": "Industrial DFW", "property_type": "industrial", "cbsa_code": "19100",
        "as_of": "2026-09-30", "source": "test",
        "values": {"exit_cap_rate": "0.06", "discount_rate": "0.075"},
        "ranges": {"exit_cap_rate": {"low": "0.05", "high": "0.075"}},
    }
    r = await client.post(PROFILES, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["cbsa_title"].startswith("Dallas") and r.json()["ranges"]["exit_cap_rate"]["low"] == "0.05"
    assert (await client.post(PROFILES, json={**body, "name": "Dup"})).status_code == 409

    res = (await client.get(f"/api/v1/properties/{pid}/resolved-assumptions")).json()
    assert Decimal(res["values"]["exit_cap_rate"]) == Decimal("0.05")
    assert Decimal(res["ranges"]["exit_cap_rate"]["base"]) == Decimal("0.06")
    assert res["sources"]["exit_cap_rate"] == "profile:Industrial DFW (quality 5)"


async def test_invalid_ranges_are_rejected(client: AsyncClient):
    base = {"name": "Bad", "values": {"exit_cap_rate": "0.06"}}
    outside = {**base, "ranges": {"exit_cap_rate": {"low": "0.065", "high": "0.07"}}}
    assert (await client.post(PROFILES, json=outside)).status_code == 422
    no_base = {**base, "ranges": {"discount_rate": {"low": "0.07", "high": "0.08"}}}
    assert (await client.post(PROFILES, json=no_base)).status_code == 422
    zero_cap = {**base, "ranges": {"exit_cap_rate": {"low": "0", "high": "0.07"}}}
    assert (await client.post(PROFILES, json=zero_cap)).status_code == 422
    pid = (await client.post(PROFILES, json=base)).json()["id"]
    r = await client.put(f"{PROFILES}/{pid}", json={"ranges": {"exit_cap_rate": {"low": "0.07", "high": "0.08"}}})
    assert r.status_code == 422


async def _import(client: AsyncClient, content: bytes) -> dict:
    job = await client.post("/api/v1/imports/preview?filename=lib.xlsx", content=content,
                            headers={"Content-Type": "application/octet-stream"})
    assert job.status_code == 201, job.text
    commit = await client.post(f"/api/v1/imports/{job.json()['id']}/commit", json={})
    assert commit.status_code == 200, commit.text
    return job.json()


async def test_template_imports_and_reimport_updates(client: AsyncClient):
    tpl = await client.get(f"{PROFILES}/template.xlsx")
    assert tpl.status_code == 200
    wb = load_workbook(io.BytesIO(tpl.content))
    assert wb.sheetnames == ["Assumption Profiles", "Read Me", "Fields", "CBSAs"]

    job = await _import(client, tpl.content)
    assert job["assumption_profiles"] == 2 and job["warnings"] == []
    profiles = {p["name"]: p for p in (await client.get(PROFILES)).json()}
    dfw = profiles["Industrial - Dallas"]
    assert dfw["cbsa_code"] == "19100" and dfw["as_of"] == "2026-09-30"
    assert float(dfw["values"]["exit_cap_rate"]) == 0.0575
    assert float(dfw["ranges"]["exit_cap_rate"]["high"]) == 0.065

    # Export the library, change a base value, re-import: the same profile is updated
    out = load_workbook(io.BytesIO((await client.get(f"{PROFILES}/template.xlsx?include_existing=true")).content))
    ws = out["Assumption Profiles"]
    headers = [c.value for c in ws[1]]
    row = next(r for r in ws.iter_rows(min_row=2) if r[0].value == "Industrial - Dallas")
    row[headers.index("exit_cap_rate_base")].value = 0.06
    buf = io.BytesIO()
    out.save(buf)
    await _import(client, buf.getvalue())
    after = [p for p in (await client.get(PROFILES)).json() if p["name"] == "Industrial - Dallas"]
    assert len(after) == 1 and float(after[0]["values"]["exit_cap_rate"]) == 0.06
    assert after[0]["as_of"] == "2026-09-30" and after[0]["cbsa_code"] == "19100"
    assert float(after[0]["ranges"]["exit_cap_rate"]["low"]) == 0.0525


async def test_portfolio_run_uses_quality_positioned_values(client: AsyncClient):
    pid = await _make_property(client, "Office A", "office", "Dallas")
    await client.put(f"/api/v1/properties/{pid}", json={"zip_code": "75201", "quality_score": "4"})
    pf = (await client.post("/api/v1/portfolios", json={"name": "F", "property_ids": [pid]})).json()
    base = (await client.post(f"/api/v1/portfolios/{pf['id']}/runs", json={})).json()
    value_before = Decimal(base["scenarios"][0]["properties"][0]["value"])
    assert (await client.post(PROFILES, json={
        "name": "Office DFW", "property_type": "office", "cbsa_code": "19100",
        "values": {"exit_cap_rate": "0.08", "downtime_months": "6"},
        "ranges": {"exit_cap_rate": {"low": "0.06", "high": "0.10"}, "downtime_months": {"low": "3", "high": "9"}},
    })).status_code == 201
    res = (await client.get(f"/api/v1/properties/{pid}/resolved-assumptions")).json()
    assert Decimal(res["values"]["exit_cap_rate"]) == Decimal("0.07")
    assert Decimal(res["values"]["downtime_months"]) == Decimal("5")
    run = await client.post(f"/api/v1/portfolios/{pf['id']}/runs", json={})
    assert run.status_code == 201, run.text
    row = run.json()["scenarios"][0]["properties"][0]
    assert row["error"] is None and Decimal(row["value"]) != value_before


async def _house_defaults(client: AsyncClient):
    r = await client.post(PROFILES, json={"name": "House defaults", "values": {
        "management_fee_pct": "0.03", "capital_reserves_per_sf": "0.30", "capital_reserves_per_unit_count": "275"}})
    assert r.status_code == 201, r.text


async def test_house_defaults_copied_into_first_valuation(client: AsyncClient):
    await _house_defaults(client)
    prop = (await client.post("/api/v1/properties", json={
        "name": "New Office", "property_type": "office", "total_area": "10000", "area_unit": "sf",
        "analysis_start_date": "2026-01-01"})).json()
    val = (await client.post(f"/api/v1/properties/{prop['id']}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()
    assert float(val["capital_reserves_per_unit"]) == 0.30
    expenses = (await client.get(f"/api/v1/valuations/{val['id']}/expenses")).json()
    fee = [e for e in expenses if e["category"] == "management_fee"]
    assert len(fee) == 1 and float(fee[0]["pct_of_egi"]) == 0.03 and fee[0]["is_pct_of_egi"]
    assert "House defaults" in fee[0]["comment"]
    # Anything the user enters wins
    val2 = (await client.post(f"/api/v1/properties/{prop['id']}/valuations", json={
        "name": "Mine", "discount_rate": "0.08", "exit_cap_rate": "0.065", "capital_reserves_per_unit": "0.5"})).json()
    assert float(val2["capital_reserves_per_unit"]) == 0.5

    apts = (await client.post("/api/v1/properties", json={
        "name": "Apts", "property_type": "multifamily", "total_area": "100", "area_unit": "unit",
        "analysis_start_date": "2026-01-01"})).json()
    v3 = (await client.post(f"/api/v1/properties/{apts['id']}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()
    assert float(v3["capital_reserves_per_unit"]) == 275


async def test_no_library_keeps_the_old_defaults(client: AsyncClient):
    prop = (await client.post("/api/v1/properties", json={
        "name": "Plain", "property_type": "office", "total_area": "10000", "area_unit": "sf",
        "analysis_start_date": "2026-01-01"})).json()
    val = (await client.post(f"/api/v1/properties/{prop['id']}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()
    assert (await client.get(f"/api/v1/valuations/{val['id']}/expenses")).json() == []
    assert float(val["capital_reserves_per_unit"]) == 0.25


async def test_settings_directions_round_trip_and_apply(client: AsyncClient):
    s = (await client.get("/api/v1/assumption-settings")).json()["directions"]
    assert s["exit_cap_rate"] == "lower" and s["market_rent_growth"] == "higher" and s["cpi_rate"] == "none"
    assert (await client.put("/api/v1/assumption-settings", json={"directions": {"bogus": "higher"}})).status_code == 422
    r = await client.put("/api/v1/assumption-settings", json={"directions": {"new_ti_per_sf": "higher"}})
    assert r.json()["directions"]["new_ti_per_sf"] == "higher"

    pid = await _make_property(client, "Office", "office", "Dallas", with_valuation=False)
    await client.put(f"/api/v1/properties/{pid}", json={"quality_score": "5"})
    await client.post(PROFILES, json={"name": "Office", "property_type": "office", "values": {"new_ti_per_sf": "40"},
                                      "ranges": {"new_ti_per_sf": {"low": "20", "high": "60"}}})
    res = (await client.get(f"/api/v1/properties/{pid}/resolved-assumptions")).json()
    assert Decimal(res["values"]["new_ti_per_sf"]) == 60
    wb = load_workbook(io.BytesIO((await client.get(f"{PROFILES}/template.xlsx")).content))
    fields = {r[0].value: r[2].value for r in wb["Fields"].iter_rows(min_row=2)}
    assert fields["new_ti_per_sf"] == "higher" and fields["management_fee_pct"] == "lower"


async def test_template_imports_house_defaults(client: AsyncClient):
    from openpyxl import Workbook

    tpl = load_workbook(io.BytesIO((await client.get(f"{PROFILES}/template.xlsx")).content))
    ws = tpl["Assumption Profiles"]
    headers = [c.value for c in ws[1]]
    ws.delete_rows(2, ws.max_row)
    row = [None] * len(headers)
    row[headers.index("name")] = "House defaults"
    row[headers.index("management_fee_pct_base")] = 0.03
    row[headers.index("capital_reserves_per_sf_base")] = 0.3
    row[headers.index("capital_reserves_per_unit_count_base")] = 275
    ws.append(row)
    buf = io.BytesIO()
    tpl.save(buf)
    await _import(client, buf.getvalue())
    house = next(p for p in (await client.get(PROFILES)).json() if p["name"] == "House defaults")
    assert house["property_type"] is None and house["cbsa_code"] is None
    assert float(house["values"]["management_fee_pct"]) == 0.03
    assert float(house["values"]["capital_reserves_per_sf"]) == 0.3
    assert float(house["values"]["capital_reserves_per_unit_count"]) == 275


async def test_own_fee_line_replaces_the_library_fee(client: AsyncClient):
    await _house_defaults(client)
    prop = (await client.post("/api/v1/properties", json={
        "name": "Fee Office", "property_type": "office", "total_area": "10000", "area_unit": "sf",
        "analysis_start_date": "2026-01-01"})).json()
    val = (await client.post(f"/api/v1/properties/{prop['id']}/valuations", json={
        "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065"})).json()
    url = f"/api/v1/valuations/{val['id']}/expenses"
    r = await client.post(url, json={"category": "management_fee", "base_year_amount": "0",
                                     "is_pct_of_egi": True, "pct_of_egi": "0.04", "is_recoverable": False})
    assert r.status_code == 201, r.text
    fees = [e for e in (await client.get(url)).json() if e["category"] == "management_fee"]
    assert [float(e["pct_of_egi"]) for e in fees] == [0.04]


async def test_house_fee_lowers_portfolio_value_of_a_property_without_a_fee_line(client: AsyncClient):
    pid = await _make_property(client, "Office", "office", "Dallas")
    pf = (await client.post("/api/v1/portfolios", json={"name": "P", "property_ids": [pid]})).json()
    scen = (await client.post(f"/api/v1/portfolios/{pf['id']}/scenarios", json={
        "name": "Fee", "overrides": [{"mode": "set", "values": {"management_fee_pct": "0.05"}}]})).json()
    run = await client.post(f"/api/v1/portfolios/{pf['id']}/runs", json={"scenario_ids": [scen["id"]]})
    assert run.status_code == 201, run.text
    base, fee = (s["properties"][0] for s in run.json()["scenarios"])
    assert fee["error"] is None and Decimal(fee["value"]) < Decimal(base["value"])


async def test_basis_reserves_position_with_the_reserves_direction(client: AsyncClient):
    pid = await _make_property(client, "Office", "office", "Dallas", with_valuation=False)
    await client.put(f"/api/v1/properties/{pid}", json={"quality_score": "5"})
    await client.post(PROFILES, json={"name": "House defaults", "values": {"capital_reserves_per_sf": "0.30"},
                                      "ranges": {"capital_reserves_per_sf": {"low": "0.10", "high": "0.50"}}})
    res = (await client.get(f"/api/v1/properties/{pid}/resolved-assumptions")).json()
    assert Decimal(res["values"]["capital_reserves_per_unit"]) == Decimal("0.10")
    settings = (await client.get("/api/v1/assumption-settings")).json()["directions"]
    assert "capital_reserves_per_sf" not in settings
    assert (await client.put("/api/v1/assumption-settings",
                             json={"directions": {"capital_reserves_per_sf": "higher"}})).status_code == 422
    await client.put("/api/v1/assumption-settings", json={"directions": {"capital_reserves_per_unit": "higher"}})
    res = (await client.get(f"/api/v1/properties/{pid}/resolved-assumptions")).json()
    assert Decimal(res["values"]["capital_reserves_per_unit"]) == Decimal("0.50")
