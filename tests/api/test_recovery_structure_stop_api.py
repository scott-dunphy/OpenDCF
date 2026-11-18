"""Recovery structures: modified gross expense stop and editable category overrides.

Setup expenses are recoverable taxes, insurance and CAM of about $17/SF a year on 15,000 SF.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from httpx import AsyncClient

from src.engine.expense_engine import _recovery_for_expense
from src.engine.types import ExpenseInput, ExpenseRecoveryOverride, LeaseInput
from tests.api.test_market_recovery_structure_api import _total_recoveries, _valuation_and_profile
from tests.api.test_valuations_api import _setup_office_property

V = "/api/v1/valuations"


async def _structure(client: AsyncClient, val: str, **fields) -> dict:
    r = await client.post(f"{V}/{val}/recovery-structures", json={"name": "MG", **fields})
    assert r.status_code == 201, r.text
    return r.json()


async def test_market_leases_use_the_structure_stop(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, profile = await _valuation_and_profile(client, ids)
    profile_url = f"{V}/{val}/market-profiles/{profile}"

    async def recoveries_with(**fields) -> float:
        rs = await _structure(client, val, **fields)
        assert (await client.put(profile_url, json={"recovery_structure_id": rs["id"]})).status_code == 200
        return await _total_recoveries(client, val)

    nnn = await recoveries_with(default_recovery_type="nnn")
    base_year = await recoveries_with(default_recovery_type="base_year_stop")
    # No stop: the market lease's base year resets to its start (it no longer recovers like NNN)
    no_stop = await recoveries_with(default_recovery_type="modified_gross")
    assert no_stop == base_year < nnn
    # A stop below expenses recovers the excess over it
    with_stop = await recoveries_with(default_recovery_type="modified_gross", expense_stop_per_sf="10")
    assert 0 < with_stop < nnn and with_stop != no_stop


async def test_structure_stop_replaces_the_lease_stop_only_when_set(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, _ = await _valuation_and_profile(client, ids)
    lease = next(l for l in (await client.get(f"{V}/{val}/leases")).json() if l["tenant_id"])
    assert (await client.put(f"/api/v1/leases/{lease['id']}", json={
        "recovery_type": "modified_gross", "expense_stop_per_sf": "12"})).status_code == 200
    lease_stop = await _total_recoveries(client, val)

    blank = await _structure(client, val, default_recovery_type="modified_gross")
    assert (await client.put(f"/api/v1/leases/{lease['id']}", json={"recovery_structure_id": blank["id"]})).status_code == 200
    assert await _total_recoveries(client, val) == lease_stop  # blank structure stop: the lease's applies

    r = await client.put(f"{V}/{val}/recovery-structures/{blank['id']}", json={"expense_stop_per_sf": "5"})
    assert r.status_code == 200 and float(r.json()["expense_stop_per_sf"]) == 5
    assert await _total_recoveries(client, val) > lease_stop  # lower stop, more recovered

    # null clears it again; the name cannot be cleared
    r = await client.put(f"{V}/{val}/recovery-structures/{blank['id']}",
                         json={"expense_stop_per_sf": None, "name": None})
    assert r.status_code == 200 and r.json()["expense_stop_per_sf"] is None and r.json()["name"] == "MG"
    assert await _total_recoveries(client, val) == lease_stop


async def test_category_overrides_can_be_edited_and_cleared(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, _ = await _valuation_and_profile(client, ids)
    rs = await _structure(client, val, items=[{
        "expense_category": "cam", "recovery_type": "modified_gross", "expense_stop_per_sf": "4",
        "cap_per_sf_annual": "9", "admin_fee_pct": "0.1"}])
    item = rs["items"][0]
    assert float(item["expense_stop_per_sf"]) == 4
    url = f"{V}/{val}/recovery-structures/{rs['id']}/items/{item['id']}"

    r = await client.put(url, json={"expense_stop_per_sf": "6", "cap_per_sf_annual": None, "recovery_type": None})
    assert r.status_code == 200, r.text
    body = r.json()
    assert float(body["expense_stop_per_sf"]) == 6 and body["cap_per_sf_annual"] is None
    assert body["recovery_type"] == "modified_gross" and float(body["admin_fee_pct"]) == 0.1

    # Another valuation's structure path does not reach the item
    other, _ = await _valuation_and_profile(client, ids)
    assert (await client.put(f"{V}/{other}/recovery-structures/{rs['id']}/items/{item['id']}",
                             json={"admin_fee_pct": "0.2"})).status_code == 404
    assert (await client.delete(f"{V}/{other}/recovery-structures/{rs['id']}/items/{item['id']}")).status_code == 404


async def test_editing_an_override_marks_the_valuation_stale_and_frozen_blocks_it(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, _ = await _valuation_and_profile(client, ids)
    rs = await _structure(client, val, items=[{"expense_category": "cam", "recovery_type": "nnn"}])
    url = f"{V}/{val}/recovery-structures/{rs['id']}/items/{rs['items'][0]['id']}"
    assert (await client.post(f"{V}/{val}/run")).status_code == 200
    ran = (await client.get(f"{V}/{val}")).json()

    assert (await client.put(url, json={"admin_fee_pct": "0.15"})).status_code == 200
    after = (await client.get(f"{V}/{val}")).json()
    assert after["inputs_updated_at"] and after["inputs_updated_at"] > ran["last_run_at"]

    assert (await client.post(f"{V}/{val}/run")).status_code == 200
    assert (await client.post(f"{V}/{val}/submit", json={"name": "A"})).status_code == 200
    r = await client.put(url, json={"admin_fee_pct": "0.2"})
    assert r.status_code == 409


async def test_stop_survives_duplicate_roll_forward_and_import(client: AsyncClient, db_session):
    from src.models.property import Property
    from src.models.valuation import Valuation
    from src.services.appraisal_reconstruction import build_plan, materialize_plan

    ids = await _setup_office_property(client)
    val, profile = await _valuation_and_profile(client, ids)
    rs = await _structure(client, val, default_recovery_type="modified_gross", expense_stop_per_sf="10", items=[
        {"expense_category": "cam", "recovery_type": "modified_gross", "expense_stop_per_sf": "3"}])
    assert (await client.put(f"{V}/{val}/market-profiles/{profile}",
                             json={"recovery_structure_id": rs["id"]})).status_code == 200
    base = await _total_recoveries(client, val)

    copy = (await client.post(f"{V}/{val}/duplicate")).json()["id"]
    (copied,) = (await client.get(f"{V}/{copy}/recovery-structures")).json()
    assert float(copied["expense_stop_per_sf"]) == 10 and float(copied["items"][0]["expense_stop_per_sf"]) == 3
    assert await _total_recoveries(client, copy) == base

    rolled = (await client.post(f"{V}/{val}/roll-forward", json={"period": "quarter"})).json()["valuation"]["id"]
    (rolled_rs,) = (await client.get(f"{V}/{rolled}/recovery-structures")).json()
    assert float(rolled_rs["expense_stop_per_sf"]) == 10

    source = await db_session.get(Valuation, val)
    prop = await db_session.get(Property, ids["property_id"])
    plan, _ = await build_plan(db_session, source, [])
    plan["target_property_id"] = prop.id
    _, rebuilt = await materialize_plan(db_session, plan, prop)
    await db_session.commit()
    (imported,) = (await client.get(f"{V}/{rebuilt.id}/recovery-structures")).json()
    assert float(imported["expense_stop_per_sf"]) == 10 and float(imported["items"][0]["expense_stop_per_sf"]) == 3
    assert await _total_recoveries(client, rebuilt.id) == base


async def test_frozen_valuation_with_a_stop_verifies(client: AsyncClient):
    ids = await _setup_office_property(client)
    val, profile = await _valuation_and_profile(client, ids)
    rs = await _structure(client, val, default_recovery_type="modified_gross", expense_stop_per_sf="10")
    assert (await client.put(f"{V}/{val}/market-profiles/{profile}",
                             json={"recovery_structure_id": rs["id"]})).status_code == 200
    assert (await client.post(f"{V}/{val}/run")).status_code == 200
    assert (await client.post(f"{V}/{val}/submit", json={"name": "A"})).status_code == 200
    r = await client.post(f"{V}/{val}/verify")
    assert r.status_code == 200, r.text
    assert r.json()["matches"] is True


def _mg_lease(stop):
    return LeaseInput(
        lease_id="l", suite_id="s", tenant_name=None, area=Decimal(1000),
        start_date=date(2025, 1, 1), end_date=date(2029, 12, 31), base_rent_per_unit=Decimal(30),
        rent_payment_frequency="annual", escalation_type="flat", escalation_pct=None, cpi_floor=None, cpi_cap=None,
        rent_steps=(), free_rent_periods=(), recovery_type="modified_gross", pro_rata_share=None, base_year=None,
        base_year_stop_amount=None, expense_stop_per_sf=stop, recovery_overrides=(), pct_rent_breakpoint=None,
        pct_rent_rate=None,
    )


def test_override_stop_wins_and_old_floor_as_stop_still_reads():
    exp = ExpenseInput(expense_id="e", category="cam", base_amount=Decimal(10000), growth_rate=Decimal(0),
                       is_recoverable=True, is_gross_up_eligible=False, gross_up_vacancy_pct=None,
                       is_pct_of_egi=False, pct_of_egi=None)
    lease = _mg_lease(Decimal(2))  # $10/SF expense over 1,000 SF property

    def recovered(override):
        rec, _ = _recovery_for_expense(replace(lease, recovery_overrides=(override,)), exp, Decimal(10000),
                                       Decimal(1000), 1, 2025)
        return rec

    own = ExpenseRecoveryOverride("cam", "modified_gross", None, None, None, None, expense_stop_per_sf=Decimal(6))
    legacy = ExpenseRecoveryOverride("cam", "modified_gross", None, None, Decimal(7), None)
    neither = ExpenseRecoveryOverride("cam", "modified_gross", None, None, None, None)
    assert recovered(own) == Decimal(4000)      # (10 - 6) x 1,000 SF
    assert recovered(legacy) == Decimal(3000)   # older models: the floor was the stop
    assert recovered(neither) == Decimal(8000)  # the lease's own $2 stop


def test_market_and_option_leases_reset_the_base_year():
    from src.engine.date_utils import build_analysis_period
    from src.engine.renewal_engine import _reset_stop, generate_option_lease
    from src.engine.types import SuiteInput

    mg = ExpenseRecoveryOverride("cam", "modified_gross", None, None, None, None)
    kept = ExpenseRecoveryOverride("taxes", "modified_gross", None, None, None, None, expense_stop_per_sf=Decimal(3))
    rtype, (cam, taxes) = _reset_stop("modified_gross", (mg, kept), None)
    assert (rtype, cam.recovery_type, taxes.recovery_type) == ("base_year_stop", "base_year_stop", "modified_gross")
    assert _reset_stop("modified_gross", (), Decimal(10))[0] == "modified_gross"
    zero = ExpenseRecoveryOverride("cam", "modified_gross", None, None, None, None, expense_stop_per_sf=Decimal(0))
    assert _reset_stop("nnn", (zero,), None)[1][0].recovery_type == "modified_gross"  # $0 is a stop, not blank
    # An override with no stop of its own uses the lease's stop, so it is kept
    assert _reset_stop("modified_gross", (mg,), Decimal(2))[1][0].recovery_type == "modified_gross"

    analysis = build_analysis_period(date(2025, 1, 1), 120, 12)
    suite = SuiteInput(suite_id="s", suite_name="S", area=Decimal(1000), space_type="office")
    source = replace(_mg_lease(None), option_rent_per_unit=Decimal(40), option_term_months=60)
    _, (option,), _ = generate_option_lease(suite, source, date(2030, 1, 1), analysis, None)
    assert option.recovery_type == "base_year_stop" and option.base_year == 2030

    with_stop = replace(source, expense_stop_per_sf=Decimal(12))
    _, (option,), _ = generate_option_lease(suite, with_stop, date(2030, 1, 1), analysis, None)
    assert option.recovery_type == "modified_gross" and option.expense_stop_per_sf == Decimal(12)
