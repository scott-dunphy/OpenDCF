"""Audit log, parameter set versions and risk run input snapshots."""
from httpx import AsyncClient

from tests.api.test_imports_api import _preview_template
from tests.api.test_loans_api import LOAN, _fast_params, _tape_property
from tests.api.test_valuations_api import _setup_office_property, _drop_setup_valuation


async def _log(client: AsyncClient, **filters) -> list[dict]:
    q = "&".join(f"{k}={v}" for k, v in filters.items())
    return (await client.get(f"/api/v1/audit-log?{q}")).json()


class TestAuditLog:
    async def test_loan_create_update_delete(self, client: AsyncClient):
        prop = await _tape_property(client)
        loan = (await client.post("/api/v1/loans", json={**LOAN, "property_id": prop})).json()

        await client.put(f"/api/v1/loans/{loan['id']}", json={"coupon": "0.05", "delinquency_status": "30"})
        await client.put(f"/api/v1/loans/{loan['id']}", json={"coupon": "0.05"})      # no change: no entry
        await client.delete(f"/api/v1/loans/{loan['id']}")

        log = await _log(client, entity_type="mortgage_loans", entity_id=loan["id"])
        assert [e["action"] for e in log] == ["delete", "update", "create"]
        update = log[1]["changes"]
        assert set(update) == {"coupon", "delinquency_status"}
        assert float(update["coupon"][0]) == 0.045 and float(update["coupon"][1]) == 0.05
        assert update["delinquency_status"] == ["current", "30"]
        assert log[1]["source"] == f"PUT /api/v1/loans/{loan['id']}"
        assert log[1]["property_id"] == prop
        assert float(log[2]["changes"]["original_balance"][1]) == 5_000_000
        assert float(log[0]["changes"]["coupon"][0]) == 0.05

    async def test_valuation_rerun_logs_result_changes_not_blobs(self, client: AsyncClient):
        ids = await _setup_office_property(client)
        val = (await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
            "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })).json()
        await _drop_setup_valuation(client, ids)
        await client.post(f"/api/v1/valuations/{val['id']}/run")
        log = await _log(client, entity_type="valuations", entity_id=val["id"])
        assert [e["action"] for e in log] == ["update", "create"]
        changes = log[0]["changes"]
        assert "result_npv" in changes and changes["result_npv"][0] is None
        assert not {"status", "result_cash_flows_json", "updated_at"} & set(changes)

        # Same inputs, same results: a rerun adds nothing
        await client.post(f"/api/v1/valuations/{val['id']}/run")
        assert len(await _log(client, entity_type="valuations", entity_id=val["id"])) == 2

        by_prop = await _log(client, property_id=ids["property_id"], limit=500)
        assert {"properties", "suites", "valuations"} <= {e["entity_type"] for e in by_prop}

    async def test_import_commit_is_logged(self, client: AsyncClient):
        job = await _preview_template(client)
        await client.post(f"/api/v1/imports/{job['id']}/commit", json={})
        log = await _log(client, limit=1000)
        sources = {e["source"] for e in log if e["entity_type"] in ("properties", "leases", "mortgage_loans")}
        assert sources == {f"POST /api/v1/imports/{job['id']}/commit"}


class TestParameterSetVersions:
    async def test_every_saved_version_is_kept(self, client: AsyncClient):
        base = (await client.get("/api/v1/risk-parameter-sets")).json()[0]
        sid = base["id"]
        await client.put(f"/api/v1/risk-parameter-sets/{sid}", json={"params": {"refi_max_ltv": 0.70}})
        await client.put(f"/api/v1/risk-parameter-sets/{sid}", json={"params": {"refi_max_ltv": 0.65}})
        await client.put(f"/api/v1/risk-parameter-sets/{sid}", json={"name": "Renamed"})       # no new version
        same = await client.put(f"/api/v1/risk-parameter-sets/{sid}", json={"params": {"refi_max_ltv": 0.65}})
        assert same.json()["version"] == 3                                                      # unchanged params

        versions = (await client.get(f"/api/v1/risk-parameter-sets/{sid}/versions")).json()
        assert [v["version"] for v in versions] == [3, 2, 1]
        assert [v["params"]["refi_max_ltv"] for v in versions] == [0.65, 0.70, 0.75]

        created = await _fast_params(client)
        versions = (await client.get(f"/api/v1/risk-parameter-sets/{created}/versions")).json()
        assert [v["version"] for v in versions] == [1] and versions[0]["params"]["num_paths"] == 200


class TestRunInputs:
    async def test_run_keeps_inputs_after_loan_and_valuation_change(self, client: AsyncClient):
        await _fast_params(client)
        ids = await _setup_office_property(client)
        val = (await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
            "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })).json()
        await _drop_setup_valuation(client, ids)
        tape = await _tape_property(client)
        a = (await client.post("/api/v1/loans", json={**LOAN, "property_id": ids["property_id"]})).json()
        b = (await client.post("/api/v1/loans", json={
            **LOAN, "property_id": tape, "external_id": "B", "tape_noi": "650000", "tape_value": "10000000",
        })).json()
        run = (await client.post("/api/v1/loan-risk-runs", json={"as_of_date": "2025-09-30"})).json()

        await client.put(f"/api/v1/loans/{a['id']}", json={"coupon": "0.09"})
        await client.put(f"/api/v1/valuations/{val['id']}", json={"exit_cap_rate": "0.08"})

        inputs = (await client.get(f"/api/v1/loan-risk-runs/{run['id']}/inputs")).json()
        assert inputs["params"]["num_paths"] == 200
        loans = {l["id"]: l for l in inputs["loans"]}
        assert float(loans[a["id"]]["coupon"]) == 0.045              # value at run time
        model = inputs["collateral"][ids["property_id"]]
        assert model["source"] == "model" and model["valuation_id"] == val["id"]
        assert float(model["exit_cap_rate"]) == 0.065
        assert len(model["monthly_noi"]) >= 12 and float(model["value"]) > 0
        tape_col = inputs["collateral"][tape]
        assert tape_col["source"] == "tape" and tape_col["tape_loan_id"] == b["id"]
        assert float(tape_col["noi_year1"]) == 650000


class TestLoanHistory:
    async def test_runs_and_collateral_values_over_time(self, client: AsyncClient):
        await _fast_params(client)
        ids = await _setup_office_property(client)
        val = (await client.post(f"/api/v1/properties/{ids['property_id']}/valuations", json={
            "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })).json()
        await _drop_setup_valuation(client, ids)
        await client.post(f"/api/v1/valuations/{val['id']}/run")
        loan = (await client.post("/api/v1/loans", json={**LOAN, "property_id": ids["property_id"]})).json()

        await client.post("/api/v1/loan-risk-runs", json={"name": "Q2", "as_of_date": "2025-06-30"})
        await client.put(f"/api/v1/valuations/{val['id']}", json={"exit_cap_rate": "0.075"})
        await client.post(f"/api/v1/valuations/{val['id']}/run")
        await client.post("/api/v1/loan-risk-runs", json={"name": "Q3", "as_of_date": "2025-09-30"})

        h = (await client.get(f"/api/v1/loans/{loan['id']}/history")).json()
        assert [r["run_name"] for r in h["runs"]] == ["Q2", "Q3"]
        q2, q3 = h["runs"]
        assert q2["valuation_id"] == q3["valuation_id"] == val["id"]
        assert q3["balance"] < q2["balance"]                                      # amortizing since mid-2023
        assert q3["collateral_value"] < q2["collateral_value"]                    # higher exit cap
        assert q3["ltv"] > q2["ltv"]

        values = h["collateral_values"]
        assert [v["source"] for v in values] == ["model", "model"]
        assert values[0]["previous_value"] is None and values[0]["valuation_name"] == "Base"
        assert values[1]["value"] < values[1]["previous_value"]
