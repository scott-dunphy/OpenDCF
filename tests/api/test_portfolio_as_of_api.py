"""Portfolio runs as of a date use approved valuations (docs/valuation-lifecycle-plan.md)."""
from decimal import Decimal

from httpx import AsyncClient

from tests.api.test_valuations_api import _drop_setup_valuation, _setup_office_property

V = "/api/v1/valuations"


async def _approved(client: AsyncClient, pid: str, start: str, exit_cap: str, name: str) -> dict:
    val = (await client.post(f"/api/v1/properties/{pid}/valuations", json={
        "name": name, "discount_rate": "0.08", "exit_cap_rate": exit_cap,
        "analysis_start_date_override": start})).json()
    assert (await client.post(f"{V}/{val['id']}/submit", json={"name": "A"})).status_code == 200
    r = await client.post(f"{V}/{val['id']}/approve", json={"name": "R"})
    assert r.status_code == 200, r.text
    return r.json()


async def _setup(client: AsyncClient):
    a_ids = await _setup_office_property(client)
    a = a_ids["property_id"]
    b = (await _setup_office_property(client))["property_id"]
    q3 = await _approved(client, a, "2026-10-01", "0.065", "Q3 2026")
    await _drop_setup_valuation(client, a_ids)  # only reviewed valuations on property a
    q4 = await _approved(client, a, "2027-01-01", "0.07", "Q4 2026")
    pf = (await client.post("/api/v1/portfolios", json={"name": "Fund", "property_ids": [a, b]})).json()
    return a, b, q3, q4, pf


async def _run(client: AsyncClient, pf: dict, as_of: str | None, scenario_ids=()):
    r = await client.post(f"/api/v1/portfolios/{pf['id']}/runs",
                          json={"as_of": as_of, "scenario_ids": list(scenario_ids)})
    assert r.status_code == 201, r.text
    return r.json()


def _row(run: dict, pid: str, case: int = 0) -> dict:
    return next(p for p in run["scenarios"][case]["properties"] if p["property_id"] == pid)


async def test_as_of_picks_the_latest_approved_valuation_on_or_before_the_date(client: AsyncClient):
    a, b, q3, q4, pf = await _setup(client)
    run = await _run(client, pf, "2026-09-30")
    assert run["as_of"] == "2026-09-30"
    row = _row(run, a)
    assert row["valuation_id"] == q3["id"] and row["value_date"] == "2026-09-30"
    assert Decimal(row["value"]) == Decimal(q3["result_npv"])
    assert _row(run, b)["error"] == "No approved valuation as of 2026-09-30"
    assert run["scenarios"][0]["excluded_count"] == 1

    later = await _run(client, pf, "2027-03-31")
    assert _row(later, a)["valuation_id"] == q4["id"]
    early = await _run(client, pf, "2026-06-30")
    assert early["scenarios"][0]["excluded_count"] == 2

    dates = (await client.get(f"/api/v1/portfolios/{pf['id']}/approved-dates")).json()
    assert [(d["value_date"], d["properties"], d["of"]) for d in dates] == [("2026-12-31", 1, 2), ("2026-09-30", 1, 2)]
    listed = (await client.get(f"/api/v1/portfolios/{pf['id']}/runs")).json()
    assert {r["as_of"] for r in listed} == {"2026-09-30", "2027-03-31", "2026-06-30"}


async def test_as_of_ignores_live_edits_and_library_but_applies_scenarios(client: AsyncClient):
    a, _, q3, q4, pf = await _setup(client)
    # Next quarter's work happens on a draft copy; the approved valuations' models are locked
    draft = (await client.post(f"{V}/{q4['id']}/duplicate")).json()
    lease = (await client.get(f"{V}/{draft['id']}/leases")).json()[0]
    edited = await client.put(f"/api/v1/leases/{lease['id']}", json={"base_rent_per_unit": "60.00"})
    assert edited.status_code == 200, edited.text
    await client.post("/api/v1/assumption-profiles", json={"name": "House", "values": {"management_fee_pct": "0.05"}})
    scen = (await client.post(f"/api/v1/portfolios/{pf['id']}/scenarios", json={
        "name": "Cap +25bp", "overrides": [{"mode": "shift", "values": {"exit_cap_rate": "0.0025"}}]})).json()
    run = await _run(client, pf, "2026-09-30", [scen["id"]])
    base, shifted = _row(run, a, 0), _row(run, a, 1)
    assert Decimal(base["value"]) == Decimal(q3["result_npv"]) and base["warnings"] == []
    assert Decimal(shifted["value"]) < Decimal(base["value"])
    live = await _run(client, pf, None)
    assert Decimal(_row(live, a)["value"]) != Decimal(base["value"])


async def test_two_approved_on_one_date_uses_the_latest_approval_and_warns(client: AsyncClient):
    a, _, _, _, pf = await _setup(client)
    second = await _approved(client, a, "2026-10-01", "0.06", "Q3 2026 alt")
    row = _row(await _run(client, pf, "2026-09-30"), a)
    assert row["valuation_id"] == second["id"]
    assert row["warnings"] and "2 approvals for 2026-09-30" in row["warnings"][0]


async def test_reopened_approval_still_values_its_quarter(client: AsyncClient):
    a, _, q3, _, pf = await _setup(client)
    r = await client.post(f"{V}/{q3['id']}/reopen", json={"name": "R", "note": "Fix a lease"})
    assert r.status_code == 200, r.text
    row = _row(await _run(client, pf, "2026-09-30"), a)
    assert row["valuation_id"] == q3["id"] and Decimal(row["value"]) == Decimal(q3["result_npv"])
    assert any("reopened" in w and "Fix a lease" in w for w in row["warnings"])


async def test_engine_drift_shifts_every_case_so_scenarios_show_only_their_change(client: AsyncClient, db_session):
    from sqlalchemy import update

    from src.models.valuation import ValuationSnapshot

    a, _, q3, _, pf = await _setup(client)
    # Pretend the engine changed since approval: the approved value no longer matches a re-run
    approved = Decimal(q3["result_npv"]) + Decimal("1000000")
    await db_session.execute(update(ValuationSnapshot).where(ValuationSnapshot.valuation_id == q3["id"])
                             .values(result_npv=approved))
    await db_session.commit()
    scen = (await client.post(f"/api/v1/portfolios/{pf['id']}/scenarios", json={
        "name": "No change", "overrides": [{"mode": "set", "values": {"discount_rate": "0.08"}}]})).json()
    run = await _run(client, pf, "2026-09-30", [scen["id"]])
    base, same = _row(run, a, 0), _row(run, a, 1)
    assert Decimal(base["value"]) == approved
    assert Decimal(same["value"]) == approved
    assert Decimal(str(run["scenarios"][1]["property_value_attribution"][a])) == 0
    assert any("Today's engine" in w for w in base["warnings"])


async def test_live_run_flags_a_frozen_valuation_on_current_inputs(client: AsyncClient):
    a, _, _, _, pf = await _setup(client)
    row = _row(await _run(client, pf, None), a)
    assert any("is frozen and there is no draft" in w for w in row["warnings"])
