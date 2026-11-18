# Self Storage Valuation — Build Plan

Status: built 2026-11-14 (migration `d2a7b9e4c518`). Engine `src/engine/self_storage.py`, schema
`src/schemas/self_storage.py`, UI `frontend/storage.js`, conversion
`POST /properties/{id}/self-storage/convert-rent-roll`, seed "Prairie Lock Storage".

Decisions taken on the open questions below (v1):
1. Model-less storage keeps the suite path; conversion exists, nothing removed.
2. No property tax reassessment.
3. Opening book spread evenly over the ECRI cycle (buckets first_after..first_after+interval).
4. Rentable SF comes from the unit mix; a mismatch with the property's SF is a readiness warning.
5. No ECRI cap vs street; one facility-wide ECRI.
6. Participation % applies to every ancillary basis.
7. Parking/RV is a unit type with access=parking.
8. No standalone endpoint; storage runs through the normal valuation run, reports, what-if,
   sensitivity, NCREIF and portfolio paths. Monte Carlo and loan-risk collateral modeling are off.
   Portfolio overrides map onto the unit mix (rent growth/change -> street rates,
   stabilized occupancy -> unit-type stabilized occupancy (general vacancy only warns), credit loss, other income growth); lease-only fields are
   skipped with a warning on the run row. The what-if chat changes storage model fields
   (street rate growth, churn, ECRI, concessions, credit loss, per-unit-type rates/occupancy).

Row mapping as built: gross_potential_rent = in-place rent billed; absorption_vacancy = street on
vacant units and loss_to_lease = in-place minus street on occupied (signed) are informational, as in
the waterfall, so the cash flow table's "potential" row = street x all units.

## Today
`self_storage` is only a PropertyType. It runs the multifamily occupancy path
(`property_cashflow.py`, `use_occupancy = property_type in ("multifamily", "self_storage")`):
$/unit/month rents, repricing to market on expiry, renewal probability as churn. No street vs in-place
rate, no ECRI, no move-in cohorts, no storage ancillary income. No tests, no seed example.
No local DB has a self_storage property.

## Recommendation
Separate module `src/engine/self_storage.py` that owns only the monthly revenue/occupancy/expense build and
emits standard monthly `AnnualPropertyCashFlow` rows, then reuses shared code:
`build_analysis_period`, `_aggregate_monthly_cash_flows`, `build_debt_schedule_detail`,
`calculate_terminal_value_breakdown`, `discount_cash_flows` / `discount_monthly_cash_flows`, `calculate_irr`,
`going_in_cap_rate`, `compute_investment_returns`, returning an `EngineResult`.

Why not extend the multifamily path: it reprices to market on expiry and can't separate the in-place book from
street rate (the core of storage value); adding ECRI/cohorts would tangle parity-calibrated code.
Why not copy marina/seniors: those duplicate DCF math and so miss transfer tax, forward-year exit NOI,
monthly discounting, acquisition/loan costs, direct cap, sensitivity, NCREIF, portfolio and MC support.

## Features
Must-have (v1)
- Unit mix by type: name, SF per unit, climate-controlled, access (interior / drive_up / parking), count, occupied units
- Units and SF both tracked; physical occupancy by units and by SF
- Street rate vs in-place rate per type; street growth (single or schedule via `growth.py`)
- Monthly move-out rate (length of stay = 1 / rate, derived)
- ECRI: first increase after N months, interval, increase %, extra move-out % on increase
- Move-in concession: % off first month
- Stabilized occupancy per type + optional facility-wide monthly net absorption cap (covers lease-up)
- Credit loss % of rental
- Ancillary lines, basis: annual_fixed | per_occupied_unit_month (with participation %) | per_move_in | pct_of_rental
  (tenant protection, admin, late fees, retail, truck commissions)
- Operating expenses: existing property expense rows (mgmt fee and card fees as % of EGI, occupancy-variable lines)
- Reserves: valuation's reserve rate × rentable SF

Later
- Property tax reassessment at purchase/sale (sale is circular: gross value = NOI before tax / (exit cap + tax rate))
- ECRI cap vs street; per-type ECRI
- Move-in/move-out seasonality; marketing cost per move-in; expansion phases
- Standalone `/self-storage-valuations/run` with scenarios

## Data model
- `properties.self_storage_assumptions_json` (operating model). Same name pattern so
  `_operating_model_json(..., "self_storage")` works (property model wins; a valuation copy is only a legacy
  fallback for marina/seniors, so storage needs no valuation column). One migration after `a1d4e7c2b903`.
- Property: inventory + operating assumptions JSON; expenses and capital projects in existing tables;
  `total_area` = rentable SF, `area_unit="sf"`.
- Valuation: discount, exit cap/year, exit costs, transfer tax, price/costs, debt, reserves, discounting, hold.
  No `valuation` block in the JSON.
- `src/schemas/self_storage.py` → `SelfStorageOperatingModel`, used for save-time validation (422 on bad JSON)
  and engine conversion:

```
unit_types[]: name, sf_per_unit>0, climate_controlled, access: interior|drive_up|parking,
              count>=0, occupied_units (0..count), in_place_rate>=0, street_rate>=0 ($/unit/month),
              stabilized_occupancy (0..1, default occupied/count)
street_rate_growth_pct | street_rate_growth_schedule[]
churn: monthly_move_out_pct
ecri: enabled, first_after_months>=1, interval_months>=1, increase_pct, extra_move_out_pct
concessions: first_month_discount_pct
lease_up: monthly_net_absorption_units | null
credit_loss_pct
ancillary_lines[]: name, basis, amount, participation_pct (default 1), growth_pct
```
Rules: ≥1 unit type, unique names, occupied ≤ count, pct_of_rental amount ≤ 1.

## Engine
Monthly; street rate steps at each analysis-year start. Per unit type, tenure buckets
(move-in → first ECRI, then position in ECRI cycle), each holding units and total rent — exact with
`first_after_months + interval_months` buckets. Opening book spread evenly across buckets.

Month order:
1. Age buckets one month
2. Buckets hitting an ECRI: rent × (1 + increase), units × (1 − extra move-out)
3. Base move-outs: units × move-out rate
4. Target occupied = min(stabilized × count, opening + cumulative absorption cap) if lease-up set, else stabilized × count
5. Move-ins = max(0, target − occupied) at current street into bucket 0
6. Rental = total rent in buckets
7. Concession = −move-ins × street × first-month discount

Row mapping: GPR = street × all units; vacancy = −street × vacant; loss_to_lease = in-place rent − street × occupied
(signed, usually positive — label accordingly); free_rent = −concessions; credit loss; other_income = ancillary;
expenses from `_to_expense_input` monthly at physical SF occupancy, `%EGI` lines on EGI; capital projects spread
over duration; reserves.

Terminal: run hold + 12 months, forward NOI from the extra year, honor `exit_cap_year`.

Outputs: `EngineResult` + per-year `storage_detail` (units, SF, physical occupancy by units/SF, economic occupancy,
avg in-place and street rent per occupied SF, rate gap %, move-ins/outs, ECRI move-outs, revenue per available SF,
NOI margin, per-type breakdown). `AnnualCashFlowSummary` gains optional `storage_detail`.
`result_avg_occupancy_pct` = avg physical SF occupancy.

## Wiring
- Service: in `execute_valuation`, self_storage with an operating model → `_run_self_storage(...)`; suites/leases
  empty; falls through to the normal persist + `_to_run_response`. Same in `monthly_cash_flows`, `ncreif_forecast`.
- `uses_operating_model(property_)` predicate replaces type sets in `portfolio_service._STANDALONE_TYPES` and
  `loan_risk_service.MODEL_UNSUPPORTED_TYPES`; gate collateral Monte Carlo off for it in v1.
- Import mapper: stop aliasing storage to multifamily; storage aliases (unit size/SF, width, depth, climate,
  street rate, in-place rent, occupied, count); `_storage_unit_mix` builds the model; `area_unit="sf"`,
  `total_area` = total SF. No size columns → old suite import + warning.
- Frontend: Unit Mix and Operations views for storage (unit types by climate/access, Year 1 rental build
  GPR → vacancy → loss to lease → concessions; churn, ECRI, lease-up, ancillary, yearly metrics), saved via
  `PUT /properties/{id}`. Keep Expenses and Capital; hide Market and recovery views.
  Route on `isStorageModel = type === 'self_storage' && !!property.self_storage_assumptions_json`.
- Seed: ~650 units / 75,000 SF (5x5, 5x10, 10x10 CC; 10x10–10x30 drive-up; RV parking), expense rows
  (payroll, tax, insurance, utilities, marketing, repairs, mgmt 6% EGI, card fees 2% EGI), 10-yr valuation.

## Tests
Unit (`tests/unit/test_self_storage.py`): hand-checks A and B, lease-up convergence under cap, ECRI raises rent and
adds move-outs, rental reconciliation, forward NOI = year N+1, each ancillary basis, variable expense scales with
occupancy, monthly vs annual discounting, levered returns.
API (`tests/api/test_self_storage_api.py`): 422 on bad JSON, run from property model with storage detail,
sensitivity and monthly reports, storage without model still runs old path, importer.

Hand-check A (static, 1-yr hold): 100 × 10x10 (10,000 SF), 90 occupied, in-place = street = $100, no churn/ECRI/growth,
credit loss 1%, protection $12 × 60%, fixed expense $30,000, mgmt 6% EGI, reserves $0.20/SF, exit cap 8% forward,
exit costs 2%, discount 9%.
Rental 108,000; credit loss −1,080; protection 7,776; EGI 114,696; mgmt 6,881.76; NOI 77,814.24;
CFBD 75,814.24; gross exit 972,678.00; net 953,224.44; NPV = 1,029,038.68 / 1.09 ≈ 944,072.18.

Hand-check B (month 1): 150 units, 120 occupied at $100 over 12 buckets (10 each), street $90, churn 5%/mo,
ECRI 10% every 12 months with 10% extra move-out, 50% first-month discount, target 120.
ECRI bucket → 9 units at $110; base churn leaves 104.5 + 8.55 = 113.05; move-ins 6.95 at $90.
Rental 10,450 + 940.50 + 625.50 − 312.75 = 11,703.25.
Check: GPR 13,500 − vacancy 2,700 + loss to lease 1,216 − concession 312.75 = 11,703.25.

## Migration of existing storage properties
None exist locally. Engine choice keyed on presence of the model, so model-less storage properties keep the old
path unchanged. Add `convert_self_storage_suites_to_model(property_id)` + UI button: suite → unit type
(count = suite.area), street = market profile rent, in-place = active lease rent or street, occupied =
count × (1 − general vacancy), churn = (1 − renewal prob) / lease term months. SF per unit must be entered
before first run. Old suites/leases left in place.

## Build steps (each with check)
1. Schema + columns + migration + save validation — 422 tests; upgrade/downgrade on DB copy
2. Engine revenue build — hand-check B + reconciliation
3. Engine expenses/reserves/capital + shared DCF — hand-check A to the cent; forward NOI; monthly discounting
4. Service wiring + storage detail + `uses_operating_model` gates — API tests; marina/seniors/multifamily unchanged
5. Import mapper — new import test; existing `test_published_import.py` passes
6. Seed example — Year 1 NOI margin ~55–65%, plausible occupancy and rate gap
7. Frontend views — browser: edit unit type, re-run, numbers change; multifamily unchanged
8. Conversion function + button — Year 1 rental matches old path with ECRI/churn off

## Open questions
1. Keep the old suite path for model-less storage forever, or remove once conversion exists?
2. Property tax reassessment (sale and/or purchase) in v1?
3. Opening book ECRI timing: spread evenly (proposed), single point, or per-type from rent roll?
4. Rentable SF derived from unit mix and locked, or entered and checked?
5. Cap ECRI relative to street? Per-type ECRI?
6. Tenant protection net to owner via participation % — sufficient?
7. Parking/RV as unit type with access=parking (proposed) or own churn/growth?
8. Standalone run endpoint with scenarios needed?

Side finding: marina and seniors duplicate DCF math instead of using `dcf.py`/`returns.py`, so they lack transfer
tax, forward-year exit NOI, monthly discounting, acquisition/loan costs, direct cap, and are excluded from
monthly, NCREIF, sensitivity, portfolio, loan-risk and Monte Carlo features.
