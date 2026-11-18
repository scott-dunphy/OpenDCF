"""Loan book CRUD, schedules, risk parameter sets and Monte Carlo runs."""
import json

from httpx import AsyncClient

from src.engine.loan_risk.params import RiskParameters
from src.models.loan import RiskParameterSet
from tests.api.test_valuations_api import _setup_office_property

LOAN = {
    "external_id": "LN-1",
    "origination_date": "2021-06-15",
    "original_balance": "5000000",
    "maturity_date": "2031-07-15",
    "rate_type": "fixed",
    "coupon": "0.045",
    "amortization_months": 360,
    "io_months": 24,
}


async def _tape_property(client: AsyncClient) -> str:
    res = await client.post("/api/v1/properties", json={
        "name": "Tape Only Industrial", "property_type": "industrial", "total_area": "100000",
        "analysis_start_date": "2025-01-01", "market": "Dallas", "area_unit": "sf",
    })
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _fast_params(client: AsyncClient) -> str:
    res = await client.post("/api/v1/risk-parameter-sets", json={
        "name": "Fast", "params": {"num_paths": 200}, "is_default": True,
    })
    assert res.status_code == 201, res.text
    return res.json()["id"]


class TestLoans:
    async def test_crud_and_validation(self, client: AsyncClient):
        prop_id = await _tape_property(client)
        res = await client.post("/api/v1/loans", json={**LOAN, "property_id": prop_id})
        assert res.status_code == 201, res.text
        loan_id = res.json()["id"]

        bad = await client.post("/api/v1/loans", json={**LOAN, "property_id": prop_id, "maturity_date": "2020-01-01"})
        assert bad.status_code == 422
        bad = await client.post("/api/v1/loans", json={**LOAN, "property_id": prop_id, "coupon": None})
        assert bad.status_code == 422
        missing = await client.post("/api/v1/loans", json={**LOAN, "property_id": "nope"})
        assert missing.status_code == 404

        upd = await client.put(f"/api/v1/loans/{loan_id}", json={"delinquency_status": "60"})
        assert upd.status_code == 200 and upd.json()["delinquency_status"] == "60"
        bad_upd = await client.put(f"/api/v1/loans/{loan_id}", json={"maturity_date": "2020-01-01"})
        assert bad_upd.status_code == 422

        listed = await client.get(f"/api/v1/loans?property_id={prop_id}")
        assert [l["id"] for l in listed.json()] == [loan_id]
        assert (await client.delete(f"/api/v1/loans/{loan_id}")).status_code == 204

    async def test_deleting_property_deletes_its_loans(self, client: AsyncClient):
        """Foreign keys are enforced, so the loans' ON DELETE CASCADE runs; none are left orphaned."""
        prop_id = await _tape_property(client)
        loan_id = (await client.post("/api/v1/loans", json={**LOAN, "property_id": prop_id})).json()["id"]
        assert (await client.delete(f"/api/v1/properties/{prop_id}")).status_code == 204
        assert (await client.get(f"/api/v1/loans/{loan_id}")).status_code == 404

    async def test_schedule_rolls_forward_from_origination(self, client: AsyncClient):
        prop_id = await _tape_property(client)
        loan_id = (await client.post("/api/v1/loans", json={**LOAN, "property_id": prop_id})).json()["id"]
        res = await client.get(f"/api/v1/loans/{loan_id}/schedule?as_of_date=2025-01-01")
        assert res.status_code == 200
        s = res.json()
        assert s["payments_made"] == 42                      # Jul 2021 .. Dec 2024
        assert s["remaining_term_months"] == 121 - 42             # 121-month term
        assert float(s["balance"]) < 5_000_000              # amortizing since month 25
        assert s["rows"][0]["payment_date"] == "2025-01-15"
        assert float(s["rows"][-1]["ending_balance"]) == 0


class TestParameterSets:
    async def test_default_versioning_and_validation(self, client: AsyncClient):
        sets = (await client.get("/api/v1/risk-parameter-sets")).json()
        assert len(sets) == 2 and sets[0]["is_default"] and sets[0]["params"]["num_paths"] == 1000
        # The earlier, wider-scenario calibration is kept as a named alternative
        assert sets[1]["name"] == "CMM fit, wide scenarios" and not sets[1]["is_default"]
        assert sets[1]["params"]["workout_carry_pct"] == 0 and sets[1]["params"]["recession_severity"] == 1.39
        base_id = sets[0]["id"]

        upd = await client.put(f"/api/v1/risk-parameter-sets/{base_id}", json={"params": {"refi_max_ltv": 0.70}})
        assert upd.json()["version"] == 2
        assert upd.json()["params"]["refi_max_ltv"] == 0.70
        assert upd.json()["params"]["num_paths"] == 1000      # omitted keys keep defaults

        bad = await client.post("/api/v1/risk-parameter-sets", json={"name": "x", "params": {"nope": 1}})
        assert bad.status_code == 422
        # Keys from the earlier NOI-shock model are dropped, not rejected
        old = await client.post("/api/v1/risk-parameter-sets", json={
            "name": "old", "params": {"noi_volatility": {"office": 0.1}, "maturity_payoff_max_ltv": 0.9, "global_weight": 0.5},
        })
        assert old.status_code == 201 and "noi_volatility" not in old.json()["params"]
        corr = [row[:] for row in old.json()["params"]["driver_correlation"]]
        corr[0][1] = corr[1][0] = 0.95          # rent growth / vacancy, contradicting other entries
        corr[0][4] = corr[4][0] = -0.95
        corr[1][4] = corr[4][1] = 0.0
        bad_corr = await client.post("/api/v1/risk-parameter-sets", json={
            "name": "bad", "params": {"driver_correlation": corr},
        })
        assert bad_corr.status_code == 422 and "positive definite" in bad_corr.text
        await client.delete(f"/api/v1/risk-parameter-sets/{old.json()['id']}")
        assert (await client.delete(f"/api/v1/risk-parameter-sets/{base_id}")).status_code == 400

        other = await _fast_params(client)
        sets = {s["id"]: s for s in (await client.get("/api/v1/risk-parameter-sets")).json()}
        assert sets[other]["is_default"] and not sets[base_id]["is_default"]

        ref = (await client.get("/api/v1/risk-parameter-sets/reference")).json()
        assert ref["moodys_idealized_el_pct"]["Baa2"][9] == 1.98
        assert ref["naic_cm_factors"]["CM1"] == 0.009


class TestRiskRuns:
    async def test_run_with_model_and_tape_collateral(self, client: AsyncClient):
        await _fast_params(client)
        ids = await _setup_office_property(client)
        office = ids["property_id"]
        val = await client.post(f"/api/v1/properties/{office}/valuations", json={
            "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })
        assert val.status_code == 201
        tape = await _tape_property(client)

        a = await client.post("/api/v1/loans", json={**LOAN, "property_id": office, "external_id": "A"})
        b = await client.post("/api/v1/loans", json={
            **LOAN, "property_id": tape, "external_id": "B", "rate_type": "floating", "coupon": None,
            "spread": "0.03", "index_floor": "0.01", "amortization_months": None, "io_months": 0,
            "maturity_date": "2027-06-15", "extension_count": 1, "extension_months": 12,
            "tape_noi": "650000", "tape_value": "10000000", "tape_noi_growth": "0.02",
        })
        c = await client.post("/api/v1/loans", json={
            **LOAN, "property_id": tape, "external_id": "C", "lien_position": 2,
            "original_balance": "1000000", "delinquency_status": "foreclosure",
        })
        assert a.status_code == b.status_code == c.status_code == 201

        run = await client.post("/api/v1/loan-risk-runs", json={"name": "Q3", "as_of_date": "2025-09-30"})
        assert run.status_code == 202
        res = (await client.get(f"/api/v1/loan-risk-runs/{run.json()['id']}")).json()
        assert res["status"] == "completed", res["error_message"]
        assert res["params"]["num_paths"] == 200
        r = res["results"]
        loans = {l["external_id"]: l for l in r["loans"]}
        assert loans["A"]["collateral_source"] == "model"
        assert loans["B"]["collateral_source"] == "tape"
        # The model collateral's simulation records the run's parameter set
        sims = (await client.get("/api/v1/collateral-simulations?purpose=loan_risk")).json()
        assert len(sims) == 1 and sims[0]["parameter_set_id"] == res["parameter_set_id"]
        assert sims[0]["parameter_set_version"] == res["parameter_set_version"]
        for key in ("A", "B", "C"):
            l = loans[key]
            assert l["error"] is None
            assert 0 <= l["pd_cumulative"] <= 1
            assert l["moodys_rating"]
            assert l["naic_cm"].startswith("CM")
            assert l["fair_value"] > 0
            assert l["ltv"] > 0
        # The whole stack on a property in foreclosure is in default
        assert loans["C"]["naic_cm"] == "CM7" and loans["C"]["pd_cumulative"] == 1
        assert loans["B"]["pd_cumulative"] == 1
        # Junior LTV is cumulative through its lien
        assert loans["C"]["ltv"] > loans["B"]["ltv"]
        assert sum(b["loan_count"] for b in r["moodys_buckets"]) == 3
        assert sum(b["loan_count"] for b in r["naic_buckets"]) == 3
        assert r["portfolio"]["expected_loss_amount"] >= 0     # foreclosed stack is at 58% LTV: losses are rare
        assert loans["A"]["collateral_simulation_id"] is not None
        assert abs(sum(l["expected_loss_amount"] for l in r["loans"]) - r["portfolio"]["expected_loss_amount"]) < 1

        # A second run records rating migration
        run2 = await client.post("/api/v1/loan-risk-runs", json={"as_of_date": "2025-09-30"})
        res2 = (await client.get(f"/api/v1/loan-risk-runs/{run2.json()['id']}")).json()
        assert res2["results"]["loans"][0]["previous_moodys_rating"] is not None
        # Unchanged property inputs and settings: the collateral simulation is reused
        a2 = next(l for l in res2["results"]["loans"] if l["external_id"] == "A")
        assert a2["collateral_simulation_id"] == loans["A"]["collateral_simulation_id"]
        listed = (await client.get("/api/v1/loan-risk-runs")).json()
        assert len(listed) == 2 and listed[0]["total_balance"] > 0

    async def test_run_fails_cleanly_without_collateral_data(self, client: AsyncClient):
        await _fast_params(client)
        tape = await _tape_property(client)
        await client.post("/api/v1/loans", json={**LOAN, "property_id": tape})
        run = await client.post("/api/v1/loan-risk-runs", json={"as_of_date": "2025-09-30"})
        res = (await client.get(f"/api/v1/loan-risk-runs/{run.json()['id']}")).json()
        assert res["status"] == "completed"
        assert "No property model and no tape" in res["results"]["loans"][0]["error"]


class TestTapeCollateralValue:
    async def test_tape_value_rolls_forward_to_run_date(self, client: AsyncClient):
        await _fast_params(client)
        tape = await _tape_property(client)
        await client.post("/api/v1/loans", json={
            **LOAN, "property_id": tape, "tape_noi": "650000", "tape_value": "10000000",
            "tape_value_date": "2024-10-01", "tape_noi_growth": "0.02",
        })
        run = (await client.post("/api/v1/loan-risk-runs", json={"as_of_date": "2025-09-30"})).json()
        res = (await client.get(f"/api/v1/loan-risk-runs/{run['id']}")).json()
        row = res["results"]["loans"][0]
        expected = 10_000_000 * 1.02 ** (365 / 365.25)            # 2024-10-01 -> 2025-10-01
        assert abs(row["collateral_value"] - expected) < 1
        assert abs(row["noi_year1"] - 650_000 * 1.02 ** (365 / 365.25)) < 1
        inputs = (await client.get(f"/api/v1/loan-risk-runs/{run['id']}/inputs")).json()
        assert abs(float(inputs["collateral"][tape]["tape_roll_factor"]) - expected / 1e7) < 1e-9


class TestLiveRates:
    async def test_curves_implied_from_fred(self, client: AsyncClient, monkeypatch):
        from datetime import date

        from src.services import rate_curves

        flat = {"SOFR": 0.039}

        async def fake_latest(_client, series):
            return date(2026, 10, 22), flat.get(series, 0.045)

        monkeypatch.setattr(rate_curves.settings, "fred_api_key", "test")
        monkeypatch.setattr(rate_curves, "_latest", fake_latest)
        res = (await client.get("/api/v1/risk-parameter-sets/live-rates")).json()
        assert res["as_of"] == "2026-10-22"
        # Flat 4.5% Treasury curve: forwards are 4.5%, SOFR keeps today's 60 bp basis to bills
        assert all(abs(r - 0.039) < 1e-9 for _, r in res["index_curve"])
        assert all(abs(r - 0.045) < 1e-9 for _, r in res["treasury_curve"])

        steep = rate_curves.build_curves(0.04, {0.25: 0.04, 10: 0.05, 30: 0.06})
        assert steep["index_curve"][0] == [0, 0.04]
        assert steep["treasury_curve"][-1][1] > steep["treasury_curve"][0][1] == 0.05   # today = 10-year yield

        monkeypatch.setattr(rate_curves.settings, "fred_api_key", None)
        assert (await client.get("/api/v1/risk-parameter-sets/live-rates")).status_code == 502


class TestCalibrationUpgrade:
    async def test_pre_calibration_default_set_is_refreshed(self, client: AsyncClient, db_session):
        old = RiskParameters().to_dict()
        for k in ("workout_carry_pct", "rent_level_reversion"):
            old.pop(k)
        old.update(recession_severity=1.39, default_intercept=-6.6, refi_max_ltv=0.70)
        db_session.add(RiskParameterSet(name="Base case", version=3, is_default=True, params_json=json.dumps(old)))
        await db_session.commit()

        sets = (await client.get("/api/v1/risk-parameter-sets")).json()
        base = next(s for s in sets if s["is_default"])
        defaults = RiskParameters()
        assert base["version"] == 4
        assert base["params"]["recession_severity"] == defaults.recession_severity
        assert base["params"]["default_intercept"] == defaults.default_intercept
        assert base["params"]["refi_max_ltv"] == 0.70            # the lender's own settings are kept
        # Only once
        again = (await client.get("/api/v1/risk-parameter-sets")).json()
        assert next(s for s in again if s["is_default"])["version"] == 4 and len(again) == 2
