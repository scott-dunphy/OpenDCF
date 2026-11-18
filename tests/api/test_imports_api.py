"""API tests for bulk import (XL4ADW template round trip)."""
import json

from httpx import AsyncClient


async def _preview_template(client: AsyncClient) -> dict:
    tpl = await client.get("/api/v1/imports/template.xlsx")
    assert tpl.status_code == 200
    resp = await client.post(
        "/api/v1/imports/preview?filename=template.xlsx",
        content=tpl.content,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestImports:
    async def test_template_round_trip_commit_and_value(self, client: AsyncClient):
        job = await _preview_template(client)
        assert job["status"] == "previewed"
        assert job["errors"] == []
        assert job["assumption_profiles"] == 1
        prop = job["properties"][0]
        assert prop["name"] == "Example Office Center"
        assert prop["leases"] == 1 and prop["market_profiles"] == 1 and prop["has_valuation"]
        assert {s["recognized_as"] for s in job["sheets"]} >= {"property", "lease", "market", "expense"}

        commit = await client.post(f"/api/v1/imports/{job['id']}/commit", json={})
        assert commit.status_code == 200, commit.text
        body = commit.json()
        assert body["status"] == "committed"
        pid = body["created_property_ids"][0]

        # Portfolio named in PropertyAssets is created and holds the property
        pfs = (await client.get("/api/v1/portfolios")).json()
        assert pfs[0]["name"] == "Fund I"
        assert [p["id"] for p in pfs[0]["properties"]] == [pid]
        profiles = (await client.get(f"/api/v1/assumption-profiles?portfolio_id={pfs[0]['id']}")).json()
        # A market name that identifies one census market is stored as its CBSA
        assert profiles[0]["cbsa_code"] == "19100" and profiles[0]["market"] is None

        p = (await client.get(f"/api/v1/properties/{pid}")).json()
        assert p["external_id"] == "P-1001" and p["market"] == "Dallas-Fort Worth" and p["cbsa_code"] == "19100"
        assert float(p["total_area"]) == 50000

        vals = (await client.get(f"/api/v1/properties/{pid}/valuations")).json()
        assert float(vals[0]["purchase_price"]) == 12_500_000
        run = await client.post(f"/api/v1/valuations/{vals[0]['id']}/run")
        assert run.status_code == 200, run.text
        km = run.json()["key_metrics"]
        assert float(km["npv"]) > 0
        assert float(km["returns"]["loan_to_value"]) == 0.6

        again = await client.post(f"/api/v1/imports/{job['id']}/commit", json={})
        assert again.status_code == 400

    async def test_replace_existing_by_external_id(self, client: AsyncClient):
        first = await _preview_template(client)
        await client.post(f"/api/v1/imports/{first['id']}/commit", json={"portfolio_name": "Core"})
        second = await _preview_template(client)
        await client.post(
            f"/api/v1/imports/{second['id']}/commit",
            json={"portfolio_name": "Core", "replace_existing": True},
        )
        props = (await client.get("/api/v1/properties")).json()
        assert len(props) == 1
        core = next(pf for pf in (await client.get("/api/v1/portfolios")).json() if pf["name"] == "Core")
        assert len(core["properties"]) == 1
        listed = await client.get("/api/v1/imports")
        assert len(listed.json()) == 2

    async def test_bad_upload(self, client: AsyncClient):
        resp = await client.post("/api/v1/imports/preview", content=b"not a workbook",
                                 headers={"Content-Type": "application/octet-stream"})
        assert resp.status_code == 400
        resp = await client.post("/api/v1/imports/preview", content=b"")
        assert resp.status_code == 400

    async def test_options_and_missing_portfolio(self, client: AsyncClient):
        tpl = (await client.get("/api/v1/imports/template.xlsx")).content
        opts = json.dumps({"default_property_type": "industrial", "analysis_period_months": 60})
        resp = await client.post(f"/api/v1/imports/preview?options={opts}", content=tpl)
        assert resp.status_code == 201
        commit = await client.post(f"/api/v1/imports/{resp.json()['id']}/commit", json={"portfolio_id": "nope"})
        assert commit.status_code == 404


def _tape_bytes(rows: list[list]) -> bytes:
    from io import BytesIO

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Loan Tape"
    ws.append(["Loan ID", "Property_ExternalID", "Property Name", "Property Type", "Origination Date",
               "Maturity Date", "Original Balance", "Current Balance", "As Of Date", "Coupon",
               "Amortization Months", "Current NOI", "Current Value", "Portfolio"])
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestLoanTapeImport:
    async def test_template_creates_loan_on_workbook_property(self, client: AsyncClient):
        job = await _preview_template(client)
        assert [l["external_id"] for l in job["loans"]] == ["LN-1001"]
        assert job["loans"][0]["property_link"] == "workbook"
        body = (await client.post(f"/api/v1/imports/{job['id']}/commit", json={})).json()
        assert body["created_loan_count"] == 1
        loans = (await client.get(f"/api/v1/loans?property_id={body['created_property_ids'][0]}")).json()
        assert loans[0]["external_id"] == "LN-1001" and float(loans[0]["reported_balance"]) == 7_900_000
        assert loans[0]["portfolio_id"] is not None

    async def test_links_existing_property_or_creates_tape_only_one(self, client: AsyncClient):
        existing = await client.post("/api/v1/properties", json={
            "name": "Existing", "external_id": "P-9", "property_type": "retail", "total_area": "20000",
            "analysis_start_date": "2025-01-01", "area_unit": "sf",
        })
        assert existing.status_code == 201, existing.text
        data = _tape_bytes([
            ["L-1", "P-9", "Existing", "Retail", "2022-01-01", "2032-01-01", 3e6, 2.9e6, "2025-09-30",
             0.05, 360, 300000, 4.5e6, "Book A"],
            ["L-2", "P-NEW", "New Flex", "Flex", "2023-01-01", "2028-01-01", 2e6, 2e6, "2025-09-30",
             0.06, None, None, None, "Book A"],
        ])
        resp = await client.post("/api/v1/imports/preview?filename=tape.xlsx", content=data,
                                 headers={"Content-Type": "application/octet-stream"})
        job = resp.json()
        assert job["status"] == "previewed", job
        links = {l["external_id"]: l for l in job["loans"]}
        assert links["L-1"]["property_link"] == "existing"
        assert links["L-2"]["property_link"] == "new"
        assert any("cannot be simulated" in w for w in links["L-2"]["warnings"])

        body = (await client.post(f"/api/v1/imports/{job['id']}/commit", json={})).json()
        assert body["created_loan_count"] == 2
        assert len(body["created_property_ids"]) == 1           # only the tape-only collateral
        new = (await client.get(f"/api/v1/properties/{body['created_property_ids'][0]}")).json()
        assert new["external_id"] == "P-NEW" and new["property_type"] == "industrial"
        loans = {l["external_id"]: l for l in (await client.get("/api/v1/loans")).json()}
        assert loans["L-1"]["property_id"] == existing.json()["id"]
        assert loans["L-2"]["amortization_months"] is None
