# Valuation lifecycle: freeze, review, roll forward, scenarios

> Superseded in part (2026-11-14): inputs are now owned by each valuation, change-set scenarios are
> dropped (a scenario is a copy) and roll forward copies the valuation. See
> docs/valuation-owned-inputs-plan.md.

Status: step 1 built 2026-11-14 (migration `a9c3e5f7b1d2`). Steps 1b-4 pending.

Step 1 as built: `valuations.review_status` (draft | in_review | approved; `status` stays the run
state) and `valuation_snapshots` (inputs, full results response, engine version, review trail;
reopened ones are kept). `services/valuation_snapshot.py` captures every input row with ids and
restores them into a private in-memory SQLite for re-runs; `services/valuation_lock.py` is a
flush guard (409) on any change or delete of a frozen valuation except labels. Frozen reports
come from the stored response; sensitivity, what-if repricing and monthly cash flows re-run the
restored snapshot. Submit refuses to freeze unless the restored snapshot reproduces the NPV.
Copilot, what-if chat, Monte Carlo and the .odcf.json package are drafts-only (409). Exports (Excel, memo PDF, NCREIF forecast) and the valuation page use the frozen property. A valuation with review history cannot be deleted, nor its property. Snapshots record the alembic revision; restore drops columns that no longer exist and reports a clear error if rebuilding fails. Step 1b (built 2026-11-14): portfolio runs take an optional `as_of` date. Each property uses
its latest valuation currently approved with a date of value (`valuation_snapshots.value_date` =
day before the analysis start) on or before it; ties go to the latest approval, with a warning.
Base = the approved NPV exactly (warning if a re-run on today's engine differs); library profiles
are not applied; scenarios apply only their own overrides to the frozen inputs. Properties
without one are excluded and flagged (`excluded_count`); ownership is taken on the as-of date.
`GET /portfolios/{id}/approved-dates` feeds the picker. Live runs (no as_of) are unchanged.
Approvals since reopened still count for their date (flagged), so a past quarter stays
reproducible. Each property is described as frozen (type, market, quality) when resolving scenarios.
If today's engine values the approved inputs differently, every case is shifted by that difference,
so the base is the approved value and scenario deltas show only the scenario. Live runs prefer a
draft valuation; a frozen one run on current inputs is flagged.
Loan collateral still uses the latest valuation and live inputs (not built).

## Decision

The property stays the live source of truth for the rent roll, expenses, market leasing and the
operating model. Valuations become auditable by **freezing a full copy of their inputs when they
are submitted for review**, not by owning editable inputs. Lease-level scenarios are **saved
change sets** on top of a base valuation, not copied rent rolls.

Considered and rejected: moving suites, leases, expenses, market profiles and operating models
onto the valuation (8 tables, 43 property-scoped routes, 56 source files, 60 frontend calls).
Freeze-on-submit gives the same auditable, locked, reviewable valuation per quarter; change sets
give lease-level scenarios that show reviewers exactly what differs and never drift from the base.
Revisit only if two independently editable rent rolls for one property are ever needed at once.

**Amended 2026-11-14:** market leasing profiles moved onto the valuation (migration b7e2c4d9a1f3),
so each valuation holds its own market view. A new valuation copies the latest valuation's
profiles; duplicate copies the source's. Suites name a `market_space_type` instead of a profile
id. Frozen valuations lock their profiles; profile edits stamp `valuations.inputs_updated_at`.
Rent roll, expenses and operating models stay on the property.

## What exists to build on

- `appraisal_reconstruction.build_plan` serializes the whole property model (property, suites,
  tenants, leases, rent steps, free rent, recovery overrides and structures, expenses, other income,
  capital projects, market profiles, valuation) to JSON with source ids; `materialize_plan` rebuilds
  rows from it with id remapping. This is the freeze format.
- `audit_log` already records every create/update/delete of input rows with before/after values.
- The what-if chat applies lease, suite, market and storage changes in a rolled-back transaction
  and runs the engine (`api/copilot.py: what_if_chat`, `resolve_scenario_changes`,
  `resolve_storage_changes`). Saved scenarios persist those changes.
- Stale tracking (`Property.inputs_updated_at`) and the duplicate endpoint.

## 1. Status and freeze

Statuses: `draft` -> `in_review` -> `approved`; `reopened` returns to draft with a logged reason.
(`running` / `completed` / `failed` stay as the run state, split into a separate `run_status`.)

- **Submit for review** (`POST /valuations/{id}/submit`): runs the valuation, then stores
  `inputs_snapshot_json` (the `build_plan` JSON without appraisal facts), `snapshot_at`,
  `engine_version` (git sha or app version) and the results. Valuation fields become read-only.
- **Approve** (`POST /valuations/{id}/approve`), **Reopen** (`POST /valuations/{id}/reopen`,
  reason required). Each writes an audit entry.
- Frozen valuations never read the live property. Results come from storage; **Re-run from
  snapshot** materializes the snapshot in a rolled-back transaction (as the what-if chat does) and
  compares to the stored result, flagging any difference as an engine change.
- Edits to the property while a valuation is in review are allowed: they belong to the next
  quarter and cannot touch the frozen one.
- Read-only review screens (rent roll, cash flow, tenant detail, assumptions) render from the
  snapshot, with a banner: "Frozen 2026-12-31 for review. Inputs as of that date."
- Existing completed valuations get no snapshot; they show "Not frozen: inputs not reproducible"
  until submitted.

## 2. Roll forward

`POST /valuations/{id}/roll-forward` on an approved valuation:

- Copies valuation fields into a new draft, `prior_valuation_id` -> the approved one.
- Moves the analysis start forward one quarter (configurable: quarter / month / year), keeping
  month-start dates and whole-year hold periods.
- Copies its saved scenarios (section 3), re-pointed at the new base.
- Returns a checklist: leases that expired between the two dates, leases starting in the window,
  scenario changes whose target row no longer exists, library values that changed since the prior
  valuation.

The analyst then edits the live property (new leases, renewals, market) as today.

## 3. Saved scenarios (change sets)

A scenario is a valuation with `base_valuation_id` and `changes_json`: a list of
`{entity_type, entity_id, field, operation, value}` (set / add / multiply), the same shape the
what-if chat produces. Valuation-level fields (rates, debt) are set directly on the scenario row.

- Running a scenario: build the base inputs, apply changes in a rolled-back transaction, run.
- "Save as scenario" button on a what-if chat answer; a change-set editor on the scenario page.
- The scenario page lists every difference from the base in plain words ("Suite 100 lease ends
  2027-06-30, renewal probability 0%").
- Submitting the base freezes its scenarios together with it.
- A change whose target row is deleted fails the run with a clear message instead of being skipped.

## 4. Quarter-over-quarter value bridge

`GET /valuations/{id}/bridge` for a valuation with a frozen prior. Runs cumulatively, each step
changing one group and attributing the value change to it:

1. Prior value (stored).
2. Time: prior snapshot inputs, new analysis start.
3. Leasing: new leases, renewals, expirations, rent roll edits.
4. Market leasing: market rent, growth, downtime, TI/LC, renewal probability.
5. Expenses and other income.
6. Valuation assumptions: discount, exit cap, reserves, costs.
7. Current value.

Order matters and is fixed and shown. A waterfall chart on the valuation page.

## Build order

1. Status split + snapshot on submit + read-only snapshot views + approve/reopen + audit. Tests:
   frozen result unchanged after property edits; re-run from snapshot reproduces the stored NPV.
2. Roll forward + checklist. Tests: dates, expiry list, scenario copy.
3. Saved scenarios + "Save as scenario" + difference list. Tests: change set applied, base edits
   flow into the scenario, deleted-target error.
4. Value bridge + waterfall. Test: steps sum to the change.

## Decisions (2026-11-14)

1. Approval: submit and approve each ask for a typed name and an optional note, stored on the
   valuation and in the audit log. No user accounts.
2. Portfolio runs and loan collateral use each property's latest **approved** valuation, falling
   back to the latest completed run when none is approved (the row says which).
3. Roll forward defaults to one quarter; month or year can be chosen when rolling.

## Open questions

1. Snapshot storage: decided, separate `valuation_snapshots` table (keeps history on reopen).
2. Marina and seniors housing: same lifecycle (their models are on the property as JSON, so the
   snapshot covers them). Assumed yes.
