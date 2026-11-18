# Valuation-owned inputs

Status: decided 2026-11-14. This reverses the "property stays the live source of truth" decision in
`valuation-lifecycle-plan.md`.

## Decision

Each valuation owns a complete, independent model. A property is a folder: its identity (name,
address, type, area, CBSA, quality, year built, fiscal year end, ownership) plus loans, comparables
and portfolio membership. Copying or rolling forward a valuation clones its whole model.

User decisions (2026-11-14):

1. Property keeps identity + loans, comparables, portfolio membership. Everything modeled moves.
2. Tenants are per valuation (no shared directory).
3. Change-set scenarios (lifecycle plan step 3) are dropped: a scenario is a copied valuation.
4. Migration: frozen valuations (in review / approved) get rows rebuilt from their snapshot,
   drafts copy the property's current rows.

## Research

Public documentation of published DCF software does not describe how a scenario's tenancy is
stored or how files are rolled forward (two searches, Nov 2026; only third-party study material
found). From secondhand knowledge: published software keeps the asset as the container and lets
each scenario hold its own full set of cash-flow inputs; a quarterly update is a copy with the
analysis begin date moved forward. We match that. Sources are thin; treat as unverified.

## What moves to the valuation

| Row | How |
| --- | --- |
| suites (leases, rent steps, free rent, recovery overrides follow) | `valuation_id` FK, cascade |
| tenants | `valuation_id` FK, cascade |
| property_expenses, property_other_income, property_capital_projects | `valuation_id` FK, cascade |
| recovery_structures (items follow), recovery_pools | `valuation_id` FK, cascade |
| market_leasing_profiles | already valuation-owned (b7e2c4d9a1f3) |
| analysis start, hold period | valuation's `analysis_start_date_override` / `analysis_period_months_override`, always filled for every valuation; property values are defaults for a new valuation only |
| marina / seniors / storage operating models | valuation columns (`*_assumptions_json`); property columns no longer read |
| staleness | `valuations.inputs_updated_at` only |

`property_id` stays on the moved rows as a grouping column (always the valuation's property).

## Copy and roll forward

- `services/valuation_clone.clone_valuation(db, source, name, ...)`: capture the source's rows
  (same capture as freezing; from the snapshot when the source is frozen), give every row a new id,
  remap every foreign key and `recovery_pools.excluded_suite_ids`, insert. Results are not copied.
- `POST /valuations/{id}/duplicate` uses it (scenario = copy).
- `POST /valuations/{id}/roll-forward` (`period`: quarter | month | year, default quarter): copy,
  analysis start moved forward, `prior_valuation_id` set, returns a checklist (leases expired or
  started between the two starts).
- `POST /valuations` with no source copies the property's latest valuation; with none, it starts
  empty (plus the library management fee).

## AI flows

- Document import (`materialize_plan`) creates the valuation's rows under the new valuation; it can
  target an existing property (new valuation in that folder) or create one.
- Re-materialize (`update_existing_roots`), copilot confirm and what-if chat act on the valuation's
  own rows.
- Copy and roll forward carry documents, extracted facts and AI action history links to the copy,
  so AI updates keep working on it.

## Routes

Collection routes move from `/properties/{property_id}/X` to `/valuations/{valuation_id}/X` for
suites, tenants, leases (list), expenses, other income, capital projects, recovery structures,
recovery pools, readiness and storage rent-roll conversion. Item routes (`/leases/{id}`, ...) stay.

## Build order (tests green at each step)

1. Model columns + migration (copy rows per valuation; frozen from snapshot) + clone service.
   Check: parity NPVs unchanged.
2. Valuation service, snapshot capture, lock, input tracking, readiness scoped by valuation.
3. Routes + tests moved to valuation paths. Duplicate / roll forward endpoints.
4. AI flows (import, copilot, what-if), published import, package, exports, portfolio, loans.
5. Frontend: property page lists valuations; inputs edited on the valuation page.

Back up the SQLite file before `alembic upgrade head`: the migration rewrites ownership of every
input row.
