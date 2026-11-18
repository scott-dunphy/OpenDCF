# Market assumptions library: plan

Status: phase 1 built 2026-11-14 (migration `e5c1a9f3b2d7`): CBSA data (`src/data`, rebuilt by
`scripts/build_cbsa_data.py`), `src/services/cbsa.py`, `/api/v1/cbsas`, property `cbsa_code`
(filled on insert from ZIP, market name, or city + state) and `quality_score`, profile scope
(CBSA, state, quality), ranges, as-of and source, quality positioning in `resolve()`, the
library page, and the template (`GET /api/v1/assumption-profiles/template.xlsx`; re-import
updates profiles with the same scope). Phases 2-5 not started.

A central, house-wide set of underwriting assumptions keyed by **property type × census market
(CBSA)**, each field held as a **low / base / high** range, used as the starting point for new
properties and valuations, as a reasonableness check on existing ones, and later as a source of
uncertainty for Monte Carlo.

## Decisions confirmed (2026-11-14)

1. **Data source**: manual entry plus spreadsheet import; a downloadable import template
   (`GET /api/v1/assumption-profiles/template.xlsx`) with one row per type x CBSA, low/base/high
   columns, as-of and source. Every row carries source and as-of.
2. **Quality**: a 1-5 score on the property (5 = best, 3 = base), interpolated continuously
   between low/base/high using each field's direction.
3. **Distributions**: both quality positioning and Monte Carlo. Monte Carlo uses a separately
   entered per-field volatility/persistence (not the range itself) plus an optional
   parameter-uncertainty draw of the starting value from the range.
4. **Copy at creation**: library values are copied into new valuations and market profiles with
   provenance; the user can override any value on any valuation; library edits never change
   existing valuations (a "differs from library" flag offers to apply them).
5. **CBSA lookup**: offline ZIP -> CBSA from Census files shipped with the app (2020 ZCTA-to-county
   relationship file joined to the county -> CBSA delineation file); searchable picker to override.
6. **Quality directions are the user's** (2026-11-14): which end of each field's range a
   quality-5 property takes ("higher", "lower" or "none" = always base) is one house-wide
   setting per field, edited on the library page (`GET/PUT /api/v1/assumption-settings`,
   table `assumption_settings`, migration `f3b8d2a6c419`). Defaults: lower cap/discount/TI/
   reserves/fee/downtime is better, higher growth/occupancy/renewal/term is better.
7. **Storage occupancy** (2026-11-14): only `stabilized_occupancy_pct` changes a self storage
   unit mix; `general_vacancy_pct` is skipped there with a warning.
8. **House defaults** (2026-11-14): the unscoped profile (no portfolio/type/market/quality)
   holds `management_fee_pct` (share of EGI), `capital_reserves_per_sf` and
   `capital_reserves_per_unit_count`. The two reserve fields resolve to the property's
   `capital_reserves_per_unit` by its `area_unit`; any scoped profile can override them.
   Copied at creation: a new office/retail/industrial/multifamily/mixed-use/storage property
   gets a non-recoverable % of EGI management fee line; a new valuation without explicit
   reserves gets the library value (form prefilled, source shown). Portfolio runs also apply
   them live (fee sets an existing fee line or adds one).

## What exists today

- `AssumptionProfile` (`src/models/portfolio.py`): name, optional `portfolio_id` (null = house-wide),
  optional `property_type`, optional free-text `market`, `values_json` (point values of
  `AssumptionValues`), comment. Editor in `frontend/portfolios.js`; import sheet in the published
  import template.
- `resolve()` (`src/engine/assumption_overrides.py`): layers that match (type and market compared
  case-insensitively as text) are merged least to most specific: type+market > type > market >
  global, portfolio scope breaking ties. Only portfolio runs use it, as a **live override**.
- `Property.market` is free text. No census code anywhere; no property quality/class field.
- `AssumptionValues` holds valuation-level fields (discount, exit cap, exit costs, reserves…) and
  leasing fields applied to every space type, but market rent only as a **relative change**
  (`market_rent_change_pct`), not an absolute $ amount.
- Monte Carlo drivers (`src/engine/loan_risk/params.py`): yearly deviations with volatility and
  persistence around one property's own base case.

## Decisions

### 1. Extend `AssumptionProfile`, don't build a second system

One table of defaults, one resolver, one editor. A parallel "market library" would give two
sources of truth that can disagree, and portfolio runs already depend on profiles.

Changes to `assumption_profiles`:

| Column | Purpose |
|---|---|
| `cbsa_code` (nullable, String(5)) | census market key; replaces matching on free text when set |
| `quality` (nullable: 1-5) | optional: a profile can be specific to a class instead of using range positions |
| `as_of` (date) | vintage of the numbers |
| `source` (text) | where they came from ("Q3 broker survey", "internal comps", …) |
| `ranges_json` | field -> `{low, high}`; the base stays in `values_json` (back-compatible) |

Keep the free-text `market` column for profiles not tied to a CBSA (e.g. "Sun Belt", a submarket
name); the resolver matches CBSA first, then text.

Uniqueness of (portfolio_id, property_type, cbsa_code, market, state, quality) is enforced in the
API (409), since SQLite treats NULLs as distinct in unique indexes; import updates the matching
profile instead of adding a duplicate.

### 2. Market key: CBSA

- **Reference table** `cbsas` shipped as data (code, title, metro/micro, principal state(s)),
  loaded by migration from the Census Bureau delineation file. The vintage is recorded in the
  table, not hard-coded in code. NCREIF has moved to the 2020-census CBSAs too, so this lines up
  with index data later.
- **ZIP → CBSA crosswalk** shipped as a data file (Census 2020 ZCTA-to-county relationship file
  joined to the county→CBSA delineation). A ZIP spanning two CBSAs takes the one with the largest
  land-area share; `GET /cbsas?zip=` lists the alternatives. Connecticut's old counties are mapped
  by hand to the 2023 planning-region CBSAs (approximate: Waterbury-area ZIPs fall in New Haven).
- **Property** gets `cbsa_code` (nullable). Filled from ZIP on create/edit when empty; the user
  can pick another from a searchable list ("Dallas-Fort Worth-Arlington, TX"). Document import
  fills it the same way from the extracted address.
- **Existing free-text `market` values**: a one-off backfill tries ZIP first, then exact/fuzzy
  match of `market` against CBSA titles and principal cities; anything ambiguous is left blank and
  listed for the user. `market` stays as a display/submarket label.
- **Outside any CBSA** (rural): no CBSA, resolves to state-level then type-only then global
  profiles. Add an optional `state` scope to profiles for that.

**Fallback chain** (most specific wins field by field, as today):
CBSA + type + quality → CBSA + type → state + type → type → global. Each resolved field records
which layer it came from.

### 3. Ranges, quality and distributions

**Storage**: per field `{low, base, high}`, where low/high mean roughly the 10th/90th percentile of
properties of that type in that market (not "worst case").

**Direction**: each field declares which end is "better quality": lower for cap rates, discount
rate, vacancy, credit loss, downtime, TI, free rent, expense growth; higher for market rent,
renewal probability, rent growth. Kept in one table next to `AssumptionValues`.

**Quality positioning**: score 5 sits at the favourable end, 3 at base, 1 at the unfavourable end,
linear between (4 = halfway from base to favourable). A profile with an explicit `quality` score
overrides positioning for that score.

**Ranges are not Monte Carlo volatility.** A range says how different properties in a market
differ today; Monte Carlo drivers say how one property's assumption wanders year to year. Using a
cross-sectional range as volatility would overstate risk badly for a well-understood property.
Phase 5 adds an optional, separately entered `volatility` (and persistence) per field to profiles,
which overrides the global `DEFAULT_DRIVER_VOLATILITY` for that type × market. A range can also
seed a one-time draw of the *starting* assumption on each path (parameter uncertainty), clearly
labelled as such.

### 4. Copy at creation, flag differences later

Two semantics, kept distinct:

- **Defaults (new)**: when a valuation, market leasing profile or operating model is created, the
  resolved values are **copied** into it, and the record stores provenance: profile id, as-of,
  quality used. Editing the library afterwards changes nothing in existing models.
- **Overrides (existing)**: portfolio runs and portfolio scenarios keep applying profiles live,
  as they do today.

A **"differs from library"** indicator shows on the valuation and market tabs when the current
library value (for the property's type, CBSA and class) differs from what the model holds, with a
one-click "apply library values" that goes through the normal edit (so it marks results stale).

### 5. Market rent and the field set

- **No absolute market rent in the library** (decided 2026-11-14). Market rent stays on each
  property's market leasing profiles; the library carries rent growth and the relative
  `market_rent_change_pct` only. Possible later additions: `opex_per_sf` (reasonableness check
  only) and `going_in_cap_rate`.
- **v1 scope**: valuation-level fields (discount, exit cap, going-in cap, exit costs, reserves) for
  all types; leasing fields (not absolute rent) for leased types (office, industrial, retail,
  multifamily, mixed use). Marina, seniors housing and self storage get valuation-level fields
  only in v1; their operating-model fields (street rate, ECRI, occupancy, RevPOR…) are a later
  extension using the same `{low, base, high}` shape.

### 6. Populating it

- Library page (replaces the profile list in Portfolios, house-wide view): filter by type and
  market, grid of fields with low/base/high, as-of and source; inline edit; history kept via the
  audit log.
- Spreadsheet import/export: one row per type × CBSA (× class), columns `<field>_low/_base/_high`,
  `as_of`, `source`. Extends the existing assumption-profiles sheet; a single-number column still
  imports as `base`.
- Stale warning when a profile's as-of is older than a set age (default 12 months).

## Consumers, phased

| Phase | What | Verify |
|---|---|---|
| 1 | Schema: CBSA table + crosswalk, `cbsa_code` on property (backfill), profile columns, range-shaped values, resolver matches CBSA/state/quality and returns ranges with provenance | Unit tests: fallback chain, quality interpolation and direction, bare number = base, uniqueness; migration up/down on a DB copy; backfill report on `opendcf.db` copy |
| 2 | **Out-of-range check** in readiness and on valuation/market tabs: each model value vs library range, warning outside low–high | API test: property with exit cap above `high` gets a warning naming the profile; none inside the range |
| 3 | **Defaults on create**: new valuation (discount, exit cap, exit costs, reserves), new market leasing profile (rent, growth, vacancy, renewal, downtime, TI, LC, free rent), new property quick setup; provenance stored | API test: create valuation with no rates → library values copied with provenance; edit library → existing valuation unchanged, "differs" flag on |
| 4 | Document import gap fill: fields the documents don't give come from the library, marked as such in the review step | Test with an extraction lacking cap rates: plan shows library values tagged "library" |
| 5 | Monte Carlo: optional per-profile volatility/persistence; optional parameter-uncertainty draw from range | MC test: profile volatility changes path dispersion; zero volatility reproduces base case |
| 6 (later) | Feeds: index data by CBSA × type (cap rates, NOI growth, occupancy), rates curves for discount-rate spreads; operating-model fields | Import of a sample feed file produces profiles with source/as-of |

Also: the what-if chat can cite the library ("Dallas industrial base exit cap is 6.0%, range
5.5–6.75%") once phase 2 exists.

## Not in scope

- A submarket hierarchy below CBSA (free-text `market` covers it for now).
- Automatic re-valuation when the library changes.
- Calibrating ranges statistically from a comps database.

## Phase 1 notes

- A free-text market on an imported profile row that names exactly one census market is stored
  as that CBSA (text dropped); typed in the API it stays text.
- State profiles apply to every property in the state, not only those outside a CBSA (a CBSA
  profile for the same type still wins).
- Half quality scores position continuously; for quality-specific profiles they round half up.
- Positioned month fields round to whole months.
- Field directions (better quality = higher/lower) are in `BETTER_IS_HIGH`/`BETTER_IS_LOW`
  (`src/engine/assumption_overrides.py`); TI, reserves and lease term are judgement calls.
