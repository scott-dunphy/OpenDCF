"""The valuation and property workspace endpoints and the recovery-audit opt-out on the full report."""
from httpx import AsyncClient

from tests.api.test_valuations_api import _setup_office_property

V = "/api/v1/valuations"
SECTIONS = {
    "suites": "/suites",
    "leases": "/leases",
    "expenses": "/expenses",
    "other_income": "/other-income",
    "capital_projects": "/capital-projects",
    "recovery_structures": "/recovery-structures",
    "recovery_pools": "/recovery-pools",
    "readiness": "/readiness",
}


async def _run_valuation(client: AsyncClient, prop_id: str) -> str:
    val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
        "name": "Base Case", "discount_rate": "0.08", "exit_cap_rate": "0.065",
    })
    val_id = val.json()["id"]
    assert (await client.post(f"{V}/{val_id}/run")).status_code == 200
    return val_id


async def test_workspace_matches_individual_endpoints(client: AsyncClient):
    ids = await _setup_office_property(client)
    prop_id = ids["property_id"]
    val_id = await _run_valuation(client, prop_id)
    # Fill the sections the fixture leaves empty so every comparison has content
    for path, body in [
        ("other-income", {"category": "cell_tower_lease", "base_year_amount": "18000", "growth_rate_pct": "0.02"}),
        ("capital-projects", {"description": "Roof", "total_amount": "50000", "start_date": "2025-07-01", "duration_months": 6}),
        ("recovery-structures", {"name": "Standard NNN"}),
        ("recovery-pools", {"name": "CAM", "expense_categories": ["cam"]}),
    ]:
        assert (await client.post(f"{V}/{val_id}/{path}", json=body)).status_code == 201

    resp = await client.get(f"{V}/{val_id}/workspace")
    assert resp.status_code == 200
    workspace = resp.json()
    assert set(workspace) == set(SECTIONS) | {"property", "valuation"}
    assert workspace["property"] == (await client.get(f"/api/v1/properties/{prop_id}")).json()
    assert workspace["valuation"] == (await client.get(f"{V}/{val_id}")).json()
    for key, path in SECTIONS.items():
        single = await client.get(f"{V}/{val_id}{path}")
        assert single.status_code == 200
        assert workspace[key] == single.json(), key
        assert workspace[key], key
    assert len(workspace["leases"]) > 0 and workspace["leases"][0]["tenant"] is not None

    # The property workspace lists the property and its valuations
    prop_ws = (await client.get(f"/api/v1/properties/{prop_id}/workspace")).json()
    assert set(prop_ws) == {"property", "valuations"}
    assert prop_ws["valuations"] == (await client.get(f"/api/v1/properties/{prop_id}/valuations")).json()
    # The fixture's market-setup valuation is a draft; the one run here completed
    assert any(v["status"] == "completed" for v in prop_ws["valuations"])


async def test_workspace_missing_property_404(client: AsyncClient):
    resp = await client.get("/api/v1/properties/does-not-exist/workspace")
    assert resp.status_code == 404
    assert (await client.get(f"{V}/does-not-exist/workspace")).status_code == 404


async def test_full_report_can_skip_recovery_audit(client: AsyncClient):
    ids = await _setup_office_property(client)
    val_id = await _run_valuation(client, ids["property_id"])

    full = (await client.get(f"/api/v1/valuations/{val_id}/reports/full")).json()
    audit = (await client.get(f"/api/v1/valuations/{val_id}/reports/recovery-audit")).json()
    assert len(audit) > 0
    assert full["recovery_audit"] == audit

    lean = (await client.get(
        f"/api/v1/valuations/{val_id}/reports/full?include_recovery_audit=false"
    )).json()
    assert lean["recovery_audit"] == []
    assert {k: v for k, v in lean.items() if k != "recovery_audit"} == {
        k: v for k, v in full.items() if k != "recovery_audit"
    }
