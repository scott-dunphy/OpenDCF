# Recovery structures: modified gross stop and editable overrides

Built 2026-11-15 (migration `b4e2c7a9d3f1`).

## Problem

- A recovery structure had no expense stop. A structure defaulting to modified gross, put on a
  market leasing profile, gave every market lease a stop of 0, so they recovered like NNN.
- A modified gross category override's stop could only be entered as its "floor" (the engine read
  the floor as the stop), which the screen did not say.
- Category overrides could only be added or deleted, not edited; the card hid the base-year stop,
  cap group and cap growth.

## Research

No public documentation of published DCF software's recovery settings was found; secondary
sources agree on the concepts used here:

- An expense stop is a negotiated $/area figure; the tenant pays its share of expenses above it
  (https://www.adventuresincre.com/glossary/expense-stop/,
  https://rets.ai/blog/base-year-vs-expense-stop-recoveries).
- A base year sets the threshold at actual expenses in a named year; published DCF software uses
  analysis year 1 when no stop amount is given (https://www.wallstreetoasis.com/forums/argus-expense-reimbursements).
- Gross-up applies to the variable portion of expenses (https://rets.ai/blog/gross-up-provisions-explained).

## What was built

- `recovery_structures.expense_stop_per_sf`: the stop for the structure's default recovery type
  when it is modified gross. When a lease uses the structure, the structure's stop replaces the
  lease's own (the lease form hides recovery terms once a structure is picked); blank keeps the
  lease's stop. Market leases under a profile with the structure get its stop.
- `recovery_structure_items.expense_stop_per_sf`: a modified gross category override's own stop.
  As before, an overridden category is measured alone against its stop (the lease's stop when it
  has none) instead of in the modified gross pool.
- Migration moves floors entered on modified gross structure items to the new column. The engine
  still reads a modified gross override's floor as its stop when no stop is set, so older frozen
  snapshots and per-lease overrides value the same.
- `PUT /valuations/{id}/recovery-structures/{rs_id}/items/{item_id}`; structure and item PUTs now
  clear a field sent as null. Item edits and deletes are scoped to the valuation.
- UI: stop field on the structure (modified gross only); overrides edited in one grid (opened
  right after creating a structure); card shows every override column.

## Base year resets on market and option leases (decided 2026-11-15)

A market lease (renewal, new tenant, lease-up) or exercised option that is modified gross with no
stop set recovers expenses above their level in its first year: it is treated as a base-year lease
whose base year is its start year (`renewal_engine._reset_stop`). A stop that is set (structure,
override or, for options, the lease's own) is kept. Option leases also reset a base-year lease's
base year to the option start. Before this, such leases had a stop of 0 and recovered like NNN.

Effect when built: seeded modified gross valuations fell 3-19%; on the real database one
valuation (a suite on an imported "NN / Modified Gross" structure with no stop) fell 1.65%.

## Follow-up (built 2026-11-15, migration `c7f1a3e5b2d8`)

- Exercised options carry the expiring lease's per-category overrides. A carried override that
  becomes base-year stop drops any fixed `base_year_stop_amount`, so its base year is the option
  start. Growth caps keep growing from the original lease start (`LeaseInput.recovery_cap_start`).
  On the real database three valuations rose 0.3-3.2% (a 15% admin fee now carries into an option).
- `lease_expense_recoveries.expense_stop_per_sf`: per-lease overrides get the same stop column;
  the migration moves modified gross floors to it.

## Growth caps with stops (built 2026-11-15, engine version 2)

Research: a controllable expense cap limits how much the tenant's share of controllable expenses
may grow, measured against the base-year (or prior-year) figure; the lease language sets
whether it compounds (https://rets.ai/blog/how-cam-caps-work, https://www.realogicinc.com/?p=4976).
Sources disagree on whether the cap applies to the tenant's share or the building total; capping
the tenant's share is our assumption (the rets.ai guide says the tenant's share). Neither source
states the order of cap and base-year subtraction; taking the stop off the capped share is ours.
Under a base-year structure the tenant pays the capped expense less the base year; capping the
recovery itself (0 in the base year) would give 0 forever, which no lease intends.

- A growth-capped group with any base-year-stop or modified gross member caps the tenant's share
  of the group's expenses at its cap-start-year level grown (compounding) at the cap rate; each
  member's stop comes off its capped share (admin fees apply on top). A $/SF group cap still caps
  the recovery. Groups of net members are unchanged (the recovery is capped, as before).
- A management fee in a growth cap whose start year is before the analysis: its start-year fee is
  the first analysis year's fee moved in line with the group's other expenses (was counted as 0,
  which made the cap bind too tightly).
- On the real database no valuation moved (its only growth caps are net groups).
- A per-category floor in a base-year-stop member of a growth-capped group is applied before the
  cap and can be cut below the floor; not handled.

## Deliberately not built (open)

- Base year offset (base year + 1), fixed dollar recovery and pro-rata share override on a
  structure.
