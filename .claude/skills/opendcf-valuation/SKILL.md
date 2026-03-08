---
name: opendcf-valuation
description: >
  Build and run commercial real estate DCF valuations using the OpenDCF engine API.
  Use this skill whenever the user provides property data (rent rolls, leases, OMs, offering
  memorandums, operating statements, T-12s, pro formas, or tenant schedules) and wants to
  value a property, run a DCF analysis, create a cash flow projection, or model an acquisition.
  Also use when the user asks to create properties, suites, tenants, leases, expenses, market
  assumptions, or valuations in OpenDCF, or wants to interact with the OpenDCF valuation engine in
  any way. Trigger on mentions of: DCF, cap rate, NOI, IRR, NPV, rent roll, lease abstract,
  offering memorandum, property valuation, cash flow analysis, OpenDCF, or CRE underwriting.
---

# OpenDCF Valuation Skill

You have access to a full commercial real estate DCF valuation engine running at `http://localhost:8001`. Use `curl` or the Bash tool to call its REST API to build properties, enter lease and expense data, and run valuations.

## When You Receive Property Data

The user will give you property information in many forms — PDFs of offering memorandums, rent roll spreadsheets, lease abstracts, operating statements, T-12 financials, or just a verbal description. Your job is to extract the relevant data and structure it into the right sequence of API calls.

### What to extract

From the data provided, identify:

1. **Property info** — name, type (office/retail/industrial/multifamily/self_storage/mixed_use), total area or unit count, address, year built, analysis start date
2. **Suites/units** — name, area (SF or unit count), space type (office, retail, 1BR, 2BR, etc.)
3. **Tenants** — name, credit rating, industry
4. **Leases** — tenant, suite, start/end dates, base rent, escalation type and rate, recovery type, base year fields, renewal override fields, any free rent or rent steps
5. **Operating expenses** — category (real_estate_taxes, insurance, cam, utilities, management_fee, repairs_maintenance, general_admin, other), annual amount, growth rate
6. **Other income (custom revenue line items)** — category/description, annual amount, growth rate
7. **Market assumptions** — market rent by space type, rent growth, vacancy, renewal probability, TI/LC, downtime
8. **Valuation assumptions** — discount rate, exit cap rate, capital reserves, debt terms if levered
9. **Source comments** — include `comment` notes (source/provenance) on assumptions and line items whenever available

### What to assume when data is missing

Real-world data is always incomplete. Use these defaults when the user doesn't specify:
- **Analysis start**: first of current month or lease commencement, whichever makes sense
- **Analysis period**: 10 years (120 months)
- **Fiscal year end**: December (month 12)
- **Escalation**: 3% annual if not specified
- **Recovery type**: NNN for office/industrial, full_service_gross for multifamily
- **Market rent growth**: 3% for commercial, 3.5% for multifamily
- **General vacancy**: 5%
- **Credit loss**: 1%
- **Discount rate**: 7-8% (ask if the user seems sophisticated)
- **Exit cap rate**: 25-50 bps above going-in cap (ask if important)
- **Capital reserves**: $0.25/SF/yr for commercial, $250-500/unit/yr for multifamily
- **Renewal probability**: 65% for commercial, 70% for multifamily
- **Downtime**: 3-6 months for commercial, 1 month for multifamily

Always tell the user what assumptions you're making so they can correct them.

## API Call Sequence

Build the property in this order (each step depends on IDs from previous steps):

```
1. POST /api/v1/properties                              → property_id
2. POST /api/v1/properties/{property_id}/suites (for each)      → suite_ids
3. POST /api/v1/tenants (for each unique tenant)        → tenant_ids
4. POST /api/v1/suites/{suite_id}/leases (for each)          → lease_ids
   - Optional: POST /api/v1/leases/{lease_id}/rent-steps
   - Optional: POST /api/v1/leases/{lease_id}/free-rent-periods
   - Optional: POST /api/v1/leases/{lease_id}/expense-recoveries
5. POST /api/v1/properties/{property_id}/expenses (for each)
6. POST /api/v1/properties/{property_id}/other-income (optional custom revenue lines)
7. POST /api/v1/properties/{property_id}/market-profiles (for each space type)
8. POST /api/v1/properties/{property_id}/capital-projects (if any)
9. POST /api/v1/properties/{property_id}/valuations             → valuation_id
10. POST /api/v1/valuations/{valuation_id}/run                   → full results
```

Most create/update payloads across assumptions and line items support an optional `comment` field. Populate it with data source/provenance (OM page, broker quote, public filing, etc.) when available.

## API Base URL

All endpoints are at `http://localhost:8001/api/v1`. Use `curl -s` with `-H "Content-Type: application/json"` for POST/PUT requests.

## Key Concepts

### Property Types and Area Units
- **Commercial** (office, retail, industrial, mixed_use): `area_unit = "sf"`, rent is $/SF/year, `rent_payment_frequency = "annual"`
- **Residential** (multifamily, self_storage): `area_unit = "unit"`, rent is $/unit/month, `rent_payment_frequency = "monthly"`

The engine automatically uses occupancy-based projection (not lease-by-lease renewal) for multifamily and self_storage properties.

### Rent and Escalation
- All rates (discount_rate, escalation, growth, vacancy) are decimals: 0.08 = 8%, 0.03 = 3%
- All dollar amounts are strings in JSON: `"32.50"`, `"500000"`
- Escalation types: `flat` (no growth), `pct_annual` (compound %), `cpi` (with floor/cap), `fixed_step` (explicit rent steps)

Frontend note:
- The UI displays and accepts percent fields as whole percentages (e.g., `5.00%`) but sends decimals to the API (`0.05`).
- Multifamily/self-storage market rents are shown with whole-dollar formatting (`$#,##0`) with no decimals.
- In valuation reports, `Other Income` is shown as its own annual cash-flow line item (with optional category detail).
- In `Edit In-Place Rent/Unit`, smart paste is enabled:
  - Paste a single numeric value into a rent cell to fill down remaining rent rows.
  - Paste tab/newline spreadsheet ranges (Excel/Sheets TSV) to apply sequentially.
  - Invalid pasted cells are highlighted and reported in toast feedback.

### Recovery Types
- `nnn` — tenant pays all recoverable expenses (triple net)
- `full_service_gross` — landlord absorbs all expenses (typical for multifamily)
- `modified_gross` — tenant pays above an expense stop ($/SF)
- `base_year_stop` — tenant pays above base year expense level
- `none` — no expense recovery

`base_year_stop` modeling conventions:
- Stop precedence is: per-category override stop → lease-level `base_year_stop_amount` → lease `base_year`-derived stop → expense Year 1 amount.
- If `base_year` is provided and stop amount is omitted, derive stop from the expense growth curve relative to the analysis start year.
- Free rent on recoveries is binary by month: if a free-rent period overlaps a month and `applies_to_recoveries=true`, recoveries are fully abated for that month.

### Expense Categories
`real_estate_taxes`, `insurance`, `cam`, `utilities`, `management_fee`, `repairs_maintenance`, `general_admin`, `other`

Management fee can be set as % of EGI: `is_pct_of_egi: true, pct_of_egi: 0.04`
Custom expense category labels are also supported.

### Valuation Results
After running, the response includes:
- **Key metrics**: NPV, IRR, going-in cap rate, terminal value, equity multiple, WALT
- **Annual cash flows**: Full waterfall (GPR → free rent → turnover vacancy → loss to lease → recoveries → GPI → vacancy → credit loss → EGI → OpEx → NOI → TI → LC → reserves → building improvements → CFBD → debt → levered CF)
- **Tenant detail**: Per-suite annual base rent, recoveries, TI/LC, turnover vacancy, loss to lease

Debt modeling convention:
- For levered runs, debt service follows amortization through loan maturity, then applies a balloon payoff of remaining principal at term-end; no debt service is applied after maturity.

Terminal value convention:
- Default `exit_cap_applied_to_year = -1` uses explicit Hold+1 NOI (Year N+1) for sale value, not a simple growth approximation.

## Presenting Results

After running a valuation, present the key metrics clearly:

```
Property: [name]
NPV: $XX,XXX,XXX
IRR: X.XX%
Going-In Cap Rate: X.XX%
Exit Cap Rate: X.XX% (terminal value: $XX,XXX,XXX)
Equity Multiple: X.XXx
Year 1 NOI: $X,XXX,XXX

Year-by-year:
  Year 1: GPR $X,XXX,XXX → NOI $X,XXX,XXX → CFBD $X,XXX,XXX
  Year 2: ...
```

If the user wants to see the full waterfall, show the annual cash flow summary table. If they want tenant detail, show per-suite breakdowns.

## Full API Reference

### Endpoint Catalog (Complete)

System / metadata:
- `GET /` (serves frontend `index.html` when frontend is mounted)
- `GET /health`
- `GET /api/v1/enums`

Properties:
- `POST /api/v1/properties`
- `GET /api/v1/properties`
- `GET /api/v1/properties/{property_id}`
- `PUT /api/v1/properties/{property_id}`
- `DELETE /api/v1/properties/{property_id}`

Suites:
- `POST /api/v1/properties/{property_id}/suites`
- `GET /api/v1/properties/{property_id}/suites`
- `GET /api/v1/properties/{property_id}/suites/{suite_id}`
- `PUT /api/v1/properties/{property_id}/suites/{suite_id}`
- `DELETE /api/v1/properties/{property_id}/suites/{suite_id}`

Tenants:
- `POST /api/v1/tenants`
- `GET /api/v1/tenants`
- `GET /api/v1/tenants/{tenant_id}`
- `PUT /api/v1/tenants/{tenant_id}`
- `DELETE /api/v1/tenants/{tenant_id}`

Leases:
- `POST /api/v1/suites/{suite_id}/leases`
- `GET /api/v1/suites/{suite_id}/leases`
- `GET /api/v1/leases/{lease_id}`
- `PUT /api/v1/leases/{lease_id}`
- `PATCH /api/v1/leases/bulk`
- `DELETE /api/v1/leases/{lease_id}`

Bulk lease update endpoint (`PATCH /api/v1/leases/bulk`):
- Request shape:
  - `atomic` (boolean, default `false`)
  - `updates` (array, required): `{ lease_id, fields }` where `fields` matches `LeaseUpdate`
- Response shape:
  - `updated_count` (int)
  - `failed` (array): `{ lease_id, status_code, detail }`
- Behavior:
  - `atomic: false` applies valid updates and returns per-item failures.
  - `atomic: true` rolls back all updates on first failure.

Lease sub-resources:
- `POST /api/v1/leases/{lease_id}/rent-steps`
- `DELETE /api/v1/leases/{lease_id}/rent-steps/{step_id}`
- `POST /api/v1/leases/{lease_id}/free-rent-periods`
- `DELETE /api/v1/leases/{lease_id}/free-rent-periods/{frp_id}`
- `POST /api/v1/leases/{lease_id}/expense-recoveries`
- `DELETE /api/v1/leases/{lease_id}/expense-recoveries/{override_id}`
- `PATCH /api/v1/leases/expense-recoveries/bulk`

Bulk expense recovery override endpoint (`PATCH /api/v1/leases/expense-recoveries/bulk`):
- Request shape:
  - `atomic` (boolean, default `false`)
  - `updates` (array, required): `{ lease_id, override_id?, fields }`
  - `fields` matches `LeaseExpenseRecoveryCreate` (full override payload)
  - `override_id` omitted → create new override; provided → update existing override for that lease
- Response shape:
  - `upserted_count` (int)
  - `failed` (array): `{ lease_id, override_id, status_code, detail }`
- Behavior:
  - `atomic: false` applies valid items and returns per-item failures.
  - `atomic: true` rolls back all changes on first failure.

Operating expenses:
- `POST /api/v1/properties/{property_id}/expenses`
- `GET /api/v1/properties/{property_id}/expenses`
- `GET /api/v1/properties/{property_id}/expenses/{expense_id}`
- `PUT /api/v1/properties/{property_id}/expenses/{expense_id}`
- `DELETE /api/v1/properties/{property_id}/expenses/{expense_id}`

Other income (custom revenue line items):
- `POST /api/v1/properties/{property_id}/other-income`
- `GET /api/v1/properties/{property_id}/other-income`
- `PUT /api/v1/properties/{property_id}/other-income/{item_id}`
- `DELETE /api/v1/properties/{property_id}/other-income/{item_id}`

Market leasing profiles:
- `POST /api/v1/properties/{property_id}/market-profiles`
- `GET /api/v1/properties/{property_id}/market-profiles`
- `GET /api/v1/properties/{property_id}/market-profiles/{profile_id}`
- `PUT /api/v1/properties/{property_id}/market-profiles/{profile_id}`
- `DELETE /api/v1/properties/{property_id}/market-profiles/{profile_id}`

Capital projects:
- `POST /api/v1/properties/{property_id}/capital-projects`
- `GET /api/v1/properties/{property_id}/capital-projects`
- `PUT /api/v1/properties/{property_id}/capital-projects/{project_id}`
- `DELETE /api/v1/properties/{property_id}/capital-projects/{project_id}`

Recovery structures:
- `POST /api/v1/properties/{property_id}/recovery-structures`
- `GET /api/v1/properties/{property_id}/recovery-structures`
- `GET /api/v1/properties/{property_id}/recovery-structures/{rs_id}`
- `PUT /api/v1/properties/{property_id}/recovery-structures/{rs_id}`
- `DELETE /api/v1/properties/{property_id}/recovery-structures/{rs_id}`

Recovery structure items:
- `POST /api/v1/properties/{property_id}/recovery-structures/{rs_id}/items`
- `DELETE /api/v1/properties/{property_id}/recovery-structures/{rs_id}/items/{item_id}`

Valuations:
- `POST /api/v1/properties/{property_id}/valuations`
- `GET /api/v1/properties/{property_id}/valuations`
- `GET /api/v1/valuations/{valuation_id}`
- `PUT /api/v1/valuations/{valuation_id}`
- `DELETE /api/v1/valuations/{valuation_id}`
- `POST /api/v1/valuations/{valuation_id}/run`

Valuation reports:
- `GET /api/v1/valuations/{valuation_id}/reports/cash-flow-summary`
- `GET /api/v1/valuations/{valuation_id}/reports/rent-roll`
- `GET /api/v1/valuations/{valuation_id}/reports/lease-expirations`
- `GET /api/v1/valuations/{valuation_id}/reports/key-metrics`
- `GET /api/v1/valuations/{valuation_id}/reports/tenant-detail`
- `GET /api/v1/valuations/{valuation_id}/reports/full`

For complete field specifications, read the reference file:
- `references/api-reference.md` — Every endpoint with all fields, types, and validation rules

## Tips

- Create all suites before any leases (leases reference suite IDs)
- Create all tenants before leases that reference them
- Lease date ranges cannot overlap within the same suite (API returns `409 Conflict` on overlap)
- Lease-level renewal overrides are supported via `renewal_probability` and `renewal_rent_spread_pct`
- Market profiles link to suites via `space_type` string matching — make sure they match exactly
- For multifamily, suites represent unit types (e.g., "1BR", "2BR"), not individual apartments. The `area` field is the unit count, not square footage.
- For multifamily/self-storage, market leasing assumptions are streamlined in the rent roll: market rent and in-place rent are adjacent, and both rent/unit and growth % are editable inline from the rent roll.
- For high-volume lease rent edits, prefer `PATCH /api/v1/leases/bulk` over many single `PUT /leases/{lease_id}` calls.
- For high-volume lease expense recovery override edits, prefer `PATCH /api/v1/leases/expense-recoveries/bulk` over many single POST calls.
- OM ingestion convention: treat OM pro forma values as Year 1 inputs; treat historical/T-12 values as Year 0 context and normalize/roll them into Year 1 assumptions before running valuation.
- You can create multiple valuations with different assumptions (base case, upside, downside) on the same property
- After creating a valuation, you must POST to `/valuations/{id}/run` to execute the engine
- The frontend is at `http://localhost:8001` — tell the user they can view results there too
