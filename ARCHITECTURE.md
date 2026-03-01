# OpenDCF — Architectural Design

A commercial real estate DCF valuation engine exposed via REST API. Supports multifamily, self-storage, office, retail, and industrial property types with tenant/suite-level modeling, probability-weighted renewals, and comprehensive expense recovery structures.

**Stack**: Python 3.13, FastAPI, SQLAlchemy 2.0 (async), SQLite/aiosqlite, Pydantic v2, Alembic

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      HTTP / FastAPI                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │properties│ │  leases  │ │ market/  │ │  valuations  │   │
│  │ suites   │ │ tenants  │ │ expenses │ │  reports     │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘   │
│       │             │            │               │          │
│       ▼             ▼            ▼               ▼          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Pydantic Schemas (validation)           │   │
│  └──────────────────────────┬───────────────────────────┘   │
│                             │                               │
│  ┌──────────────────────────▼───────────────────────────┐   │
│  │          SQLAlchemy ORM Models (persistence)         │   │
│  │          SQLite via aiosqlite (async)                │   │
│  └──────────────────────────┬───────────────────────────┘   │
│                             │                               │
│  ┌──────────────────────────▼───────────────────────────┐   │
│  │             ValuationService (bridge)                │   │
│  │         ORM models ──► engine dataclasses             │   │
│  │         engine results ──► response schemas           │   │
│  └──────────────────────────┬───────────────────────────┘   │
└─────────────────────────────┼───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│              Pure-Python DCF Engine (no deps)               │
│                                                             │
│  ┌─────────────────┐    ┌──────────────────┐                │
│  │ property_cashflow│◄──│   date_utils     │                │
│  │  (orchestrator)  │    │   growth         │                │
│  └───────┬──────────┘    └──────────────────┘                │
│          │                                                   │
│    ┌─────┼──────────┬──────────────┬──────────────┐          │
│    ▼     ▼          ▼              ▼              ▼          │
│  lease  renewal   expense      waterfall        dcf          │
│projector engine    engine    (aggregation)  (NPV/IRR/TV)     │
│                                                              │
│  All math: Decimal · All types: dataclasses · No ORM/DB     │
└──────────────────────────────────────────────────────────────┘
```

### Key Design Principle

The engine layer (`src/engine/`) is 100% pure Python with zero external dependencies. It uses only stdlib `dataclasses` and `Decimal`. No database, no ORM, no Pydantic, no I/O. This makes it deterministic, trivially testable, and portable.

The service layer (`src/services/valuation_service.py`) is the sole bridge: it converts ORM models to engine dataclasses, calls `run_valuation()`, and converts results back to Pydantic response schemas.

---

## 2. Directory Structure

```
OpenDCF/
├── ARCHITECTURE.md                  # This file
├── pyproject.toml                   # Dependencies & pytest config
├── alembic.ini                      # Alembic config
├── alembic/
│   ├── env.py                       # Async migration env
│   ├── script.py.mako               # Migration template
│   └── versions/                    # Migration scripts
├── src/
│   ├── main.py                      # FastAPI app + lifespan + /health + /enums
│   ├── config.py                    # pydantic-settings (DATABASE_URL, DEBUG)
│   ├── dependencies.py              # DI placeholder
│   ├── db/
│   │   └── session.py               # AsyncEngine + async_sessionmaker + get_session()
│   ├── models/                      # SQLAlchemy ORM (8 tables)
│   │   ├── base.py                  # DeclarativeBase + UUIDPrimaryKey + TimestampMixin
│   │   ├── property.py              # Property, Suite
│   │   ├── lease.py                 # Tenant, Lease, RentStep, FreeRentPeriod, LeaseExpenseRecovery
│   │   ├── market.py                # MarketLeasingProfile
│   │   ├── expense.py               # PropertyExpense
│   │   ├── valuation.py             # Valuation (assumptions + persisted results)
│   │   └── __init__.py              # Re-exports all models (relationship resolution)
│   ├── schemas/                     # Pydantic v2 request/response
│   │   ├── common.py                # Enums: PropertyType, AreaUnit, EscalationType, RecoveryType, etc.
│   │   ├── property.py              # PropertyCreate/Read/Update, SuiteCreate/Read/Update
│   │   ├── lease.py                 # LeaseCreate/Read/Update, RentStep, FreeRent, RecoveryOverride, Tenant
│   │   ├── market.py                # MarketLeasingProfileCreate/Read/Update
│   │   ├── expense.py               # PropertyExpenseCreate/Read/Update
│   │   ├── valuation.py             # ValuationCreate/Read/Update
│   │   └── cashflow.py              # Output-only: AnnualCashFlowSummary, KeyMetrics, ValuationRunResponse
│   ├── api/                         # FastAPI routers
│   │   ├── properties.py            # CRUD /api/v1/properties
│   │   ├── suites.py                # CRUD /api/v1/properties/{id}/suites
│   │   ├── tenants.py               # CRUD /api/v1/tenants
│   │   ├── leases.py                # CRUD + sub-resources (rent-steps, free-rent, recovery-overrides)
│   │   ├── market_assumptions.py    # CRUD /api/v1/properties/{id}/market-profiles
│   │   ├── expenses.py              # CRUD /api/v1/properties/{id}/expenses
│   │   ├── valuations.py            # CRUD + /run + 6 report endpoints
│   │   └── router.py                # Aggregate router (includes all above)
│   ├── services/
│   │   └── valuation_service.py     # ORM ↔ engine bridge; orchestrates full valuation lifecycle
│   └── engine/                      # Pure-Python DCF engine
│       ├── types.py                 # Engine dataclasses (inputs + outputs)
│       ├── date_utils.py            # Fiscal periods, proration, month iteration
│       ├── growth.py                # Compound growth, anniversary-based escalation
│       ├── lease_projector.py       # Single-lease monthly cash flow projection
│       ├── renewal_engine.py        # Probability-weighted speculative leasing (recursive)
│       ├── expense_engine.py        # NNN/FSG/ModGross/BaseYearStop recovery calculations
│       ├── waterfall.py             # Annual property cash flow aggregation
│       ├── dcf.py                   # Terminal value, NPV, IRR, debt service, key metrics
│       └── property_cashflow.py     # Master orchestrator: run_valuation()
└── tests/
    ├── conftest.py                  # In-memory SQLite fixtures, AsyncClient
    ├── unit/                        # Engine-only tests (no DB)
    │   ├── test_date_utils.py
    │   ├── test_growth.py
    │   ├── test_lease_projector.py   # Flat, pct_annual, CPI, fixed_step, free rent, % rent, edge cases
    │   ├── test_renewal_engine.py    # Probability weights, downtime, recursion, TI/LC
    │   ├── test_expense_engine.py    # NNN, base year stop, modified gross, gross-up, overrides
    │   ├── test_waterfall.py         # GPR aggregation, vacancy, mgmt fee, cap reserves, debt, multi-year
    │   └── test_dcf.py               # Terminal value, discounting, IRR, debt schedule, cap rate
    ├── integration/                  # Engine-level parity tests
    │   ├── test_engine_parity.py     # 8 hand-calculated scenarios (NNN, FSG, multi-tenant, MTM, etc.)
    │   └── test_large_rent_roll.py   # 200-suite stress test (<5s, correctness checks)
    └── api/                          # HTTP round-trip tests
        ├── test_properties_api.py
        ├── test_leases_api.py
        ├── test_market_expenses_api.py
        └── test_valuations_api.py    # Full lifecycle: create property → run valuation → check reports
```

---

## 3. Data Model

### Entity Relationship Diagram

```
Property (1) ──── (*) Suite (1) ──── (*) Lease (1) ──┬── (*) RentStep
    │                                    │            ├── (*) FreeRentPeriod
    │                                    │            └── (*) LeaseExpenseRecovery
    │                                    │
    │                                    └──── (0..1) Tenant
    │
    ├──── (*) MarketLeasingProfile   (one per space_type)
    ├──── (*) PropertyExpense        (one per expense category)
    └──── (*) Valuation              (DCF assumptions + persisted results)
```

### Key Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `properties` | Physical asset | name, address, property_type, total_area, analysis_start_date, analysis_period_months, fiscal_year_end_month |
| `suites` | Leasable units | suite_name, area, space_type |
| `tenants` | Tenant entities | name, credit_rating, industry |
| `leases` | Lease contracts | start/end dates, base_rent_per_unit, escalation_type/pct, recovery_type, % rent fields |
| `rent_steps` | Fixed rent schedule | effective_date, rent_per_unit |
| `free_rent_periods` | Rent abatement | start/end dates, applies_to_base_rent, applies_to_recoveries |
| `lease_expense_recoveries` | Per-lease per-category overrides | recovery_type, base_year_stop_amount, cap/floor/admin_fee |
| `market_leasing_profiles` | Market leasing assumptions | market_rent, rent_growth, new/renewal terms, TI/LC, downtime, vacancy |
| `property_expenses` | Operating expenses | category, base_year_amount, growth_rate, is_recoverable, gross_up |
| `valuations` | DCF assumptions + results | discount_rate, exit_cap_rate, debt params; result_npv, result_irr, result_cash_flows_json |

---

## 4. Engine Architecture

### 4.1 Data Flow Pipeline

`run_valuation()` in `property_cashflow.py` executes a 9-step pipeline:

```
Step 1: Build AnalysisPeriod (fiscal years, date boundaries)
           │
Step 2: Project all suites → MonthlySlice[]
           │  For each suite:
           │    ├── Sort in-place leases by start date
           │    ├── For gaps: generate speculative leases (renewal engine)
           │    ├── For in-place: project_lease_cash_flows()
           │    └── For post-expiry: generate_speculative_leases()
           │
Step 3: Compute occupancy by month (probability-weighted)
           │
Step 4: Attach expense recoveries to all lease slices
           │  For each lease's slices:
           │    └── attach_expense_recoveries() mutates slice.expense_recovery
           │
Step 5: Build debt schedule (IO + amortizing)
           │
Step 6: Waterfall aggregation → AnnualPropertyCashFlow[]
           │  Monthly slices → fiscal year buckets:
           │    GPR + Recoveries + %Rent + Other = GPI
           │    - General Vacancy (on GPR only) - Credit Loss = EGI
           │    - OpEx (+ mgmt fee circularity) = NOI
           │    - TI/LC - CapReserves = CFBD
           │    - Debt Service = Levered CF
           │
Step 7: Terminal value = forward_NOI / exit_cap_rate × (1 - exit_costs)
           │
Step 8: Discount all CFs + terminal value → NPV
           │
Step 9: IRR (Newton-Raphson) + key metrics (cap rate, equity multiple)
           │
           ▼
       EngineResult
```

### 4.2 Engine Module Dependency Graph

```
types.py (leaf — all dataclasses, no imports)
    │
date_utils.py ──► types.py
    │
growth.py ──► date_utils.py
    │
    ├── lease_projector.py ──► date_utils, growth, types
    │       │
    │       ▼
    │   renewal_engine.py ──► date_utils, growth, lease_projector, types
    │
    ├── expense_engine.py ──► growth, types, date_utils
    │
    ├── waterfall.py ──► growth, types
    │
    └── dcf.py ──► types
            │
            ▼
    property_cashflow.py ──► ALL engine modules (orchestrator)
```

### 4.3 Type System

The engine has a strict type boundary. All inputs and outputs are plain dataclasses defined in `types.py`:

**Input types** (frozen dataclasses):
- `AnalysisPeriod` — date boundaries + fiscal year definitions
- `LeaseInput` — 21 fields covering all lease economics
- `SuiteInput` — physical unit: id, name, area, space_type
- `MarketAssumptions` — 16 fields for speculative leasing parameters
- `ExpenseInput` — operating expense line items
- `ValuationParams` — DCF assumptions (discount rate, exit cap, debt terms)

**Output types** (mutable dataclasses):
- `MonthlySlice` — one month of cash flow for one lease on one suite; fields are mutated in-place by the expense engine
- `SuiteAnnualCashFlow` — per-suite per-year summary
- `AnnualPropertyCashFlow` — full waterfall for one fiscal year
- `EngineResult` — top-level output: annual CFs, NPV, IRR, terminal value, occupancy, equity multiple

### 4.4 Lease Cash Flow Projection

`lease_projector.py` projects month-by-month base rent for a single lease:

```
For each month in analysis period that overlaps the lease:
  1. Determine current rent (dispatch on escalation_type):
     - flat:       base_rent_per_unit (unchanged)
     - pct_annual: base × (1 + pct)^n  where n = lease anniversaries elapsed
     - cpi:        base compounded by CPI (with floor/cap) per anniversary
     - fixed_step: lookup table — last step ≤ period_start
  2. Calculate monthly amount = rent_per_unit × area / 12 (annual) or × area (monthly)
  3. Apply proration for partial first/last months (day-count fraction)
  4. Apply free rent adjustment (overlap fraction of free rent period)
  5. Calculate percentage rent: max(0, annual_sales - breakpoint) × rate / 12
  6. Produce MonthlySlice with base_rent, free_rent_adjustment, effective_rent
```

### 4.5 Probability-Weighted Renewal Engine

`renewal_engine.py` generates speculative leases when existing leases expire:

```
generate_speculative_leases(vacancy_start_date, market, generation, cumulative_weight):

  Scenario A: RENEWAL (weight = P_renew × cumulative_weight)
    - Starts immediately at vacancy_start_date
    - Rent = market_rent grown to vacancy_start × (1 + renewal_adjustment)
    - Term, TI, LC, free rent from market renewal assumptions
    - Project lease cash flows → slices

  Scenario B: NEW TENANT (weight = (1 - P_renew) × cumulative_weight)
    - Starts after downtime_months of vacancy
    - Rent = market_rent grown to vacancy_start (full market)
    - Term, TI, LC, free rent from market new-tenant assumptions
    - Insert vacancy slices for downtime period
    - Project lease cash flows → slices

  RECURSE: If either speculative lease expires within analysis period
           AND weight > 0.0001 AND generation < 5:
    → generate_speculative_leases(next_vacancy_date, generation+1, new_weight)

  Returns: (all_slices, all_lease_inputs)  — LeaseInputs needed for expense recovery
```

### 4.6 Expense Recovery Engine

`expense_engine.py` computes monthly recovery amounts per lease:

| Recovery Type | Formula |
|---------------|---------|
| **NNN** | `annual_expense × pro_rata_share / 12` |
| **Full Service Gross** | `0` (expenses included in rent) |
| **Base Year Stop** | `max(0, current_expense - base_year_amount) × pro_rata / 12` |
| **Modified Gross** | `max(0, expense_per_SF - stop_per_SF) × lease_area / 12` |

Additional features:
- **Gross-up**: Variable expenses scaled to reference occupancy: `expense × (ref_occ / actual_occ)`
- **Per-category overrides**: Cap, floor, admin fee markup per expense category per lease
- **Free rent on recoveries**: Binary monthly check — if free rent period overlaps month, recovery = 0

### 4.7 Cash Flow Waterfall

`waterfall.py` aggregates monthly slices into annual property-level cash flows:

```
Gross Potential Rent          Σ(effective_rent × scenario_weight)
+ Expense Recoveries          Σ(expense_recovery × scenario_weight)
+ Percentage Rent              Σ(percentage_rent × scenario_weight)
+ Other Income                 flat annual amount
= Gross Potential Income (GPI)
- General Vacancy              GPR × blended_vacancy_rate  (on GPR only, not recoveries)
- Credit Loss                  GPR × blended_credit_loss_rate
= Effective Gross Income (EGI)
- Operating Expenses           Σ(expense_at_year(base, growth, year))
- Management Fee               EGI × pct / (1 + pct)  [circularity solved algebraically]
= Net Operating Income (NOI)
- Tenant Improvements          Σ(ti_cost × scenario_weight)  (negative)
- Leasing Commissions          Σ(lc_cost × scenario_weight)  (negative)
- Capital Reserves             reserves_per_unit × total_area  (negative)
= Cash Flow Before Debt (CFBD)
- Debt Service                 IO interest or fixed amortizing payment  (negative)
= Levered Cash Flow
```

### 4.8 DCF Valuation

`dcf.py` provides the financial mathematics:

- **Terminal Value**: `forward_year_NOI / exit_cap_rate × (1 - exit_costs_pct)`
  - Forward NOI grown component-by-component (revenue at rent_growth, expenses at exp_growth)
- **NPV**: `Σ(CFBD_t / (1+r)^t) + TV / (1+r)^N`; supports mid-year convention
- **IRR**: Newton-Raphson with 5 starting guesses, 300 iterations max, $0.01 convergence
- **Debt Service**: Fixed monthly payment calculated once; supports IO period before amortization
- **Going-in Cap Rate**: `Year1_NOI / NPV`
- **Equity Multiple**: `(Σ CFBD + Terminal_Value) / NPV`

---

## 5. Service Layer

`ValuationService` is the sole bridge between the persistence layer and the engine:

```
execute_valuation(valuation_id):
  1. Load from DB:  Property, Suites, Leases (with rent_steps, free_rent_periods,
                    expense_recovery_overrides, tenant), MarketProfiles, Expenses
  2. Convert to engine types:  _to_suite_input(), _to_lease_input(), etc.
     - MTM leases: end_date clamped to last day of that month
  3. Call:  run_valuation(...)  →  EngineResult
  4. Persist:  npv, irr, cap_rate, terminal_value, equity_multiple, cash_flows_json
  5. Build response:  KeyMetrics, AnnualCashFlows, TenantDetail, RentRoll, LeaseExpirations
     - WALT computed from active leases at analysis start
```

---

## 6. API Endpoints

### Properties & Suites
```
POST   /api/v1/properties                              Create property
GET    /api/v1/properties                              List properties
GET    /api/v1/properties/{id}                         Get property (with suites)
PUT    /api/v1/properties/{id}                         Update property
DELETE /api/v1/properties/{id}                         Delete property
POST   /api/v1/properties/{id}/suites                  Create suite
GET    /api/v1/properties/{id}/suites                  List suites
GET    /api/v1/properties/{id}/suites/{sid}            Get suite
PUT    /api/v1/properties/{id}/suites/{sid}            Update suite
DELETE /api/v1/properties/{id}/suites/{sid}            Delete suite
```

### Tenants & Leases
```
POST   /api/v1/tenants                                 Create tenant
GET    /api/v1/tenants                                 List tenants
GET    /api/v1/tenants/{id}                            Get tenant
PUT    /api/v1/tenants/{id}                            Update tenant
DELETE /api/v1/tenants/{id}                            Delete tenant
POST   /api/v1/suites/{sid}/leases                     Create lease
GET    /api/v1/suites/{sid}/leases                     List leases for suite
GET    /api/v1/leases/{id}                             Get lease (with sub-resources)
PUT    /api/v1/leases/{id}                             Update lease
DELETE /api/v1/leases/{id}                             Delete lease
POST   /api/v1/leases/{id}/rent-steps                  Add rent step
DELETE /api/v1/leases/{id}/rent-steps/{sid}            Delete rent step
POST   /api/v1/leases/{id}/free-rent-periods           Add free rent period
DELETE /api/v1/leases/{id}/free-rent-periods/{fid}     Delete free rent period
POST   /api/v1/leases/{id}/expense-recoveries          Add recovery override
DELETE /api/v1/leases/{id}/expense-recoveries/{oid}    Delete recovery override
```

### Market Assumptions & Expenses
```
POST   /api/v1/properties/{id}/market-profiles         Create market profile
GET    /api/v1/properties/{id}/market-profiles         List market profiles
GET    /api/v1/properties/{id}/market-profiles/{mid}   Get market profile
PUT    /api/v1/properties/{id}/market-profiles/{mid}   Update market profile
DELETE /api/v1/properties/{id}/market-profiles/{mid}   Delete market profile
POST   /api/v1/properties/{id}/expenses                Create expense
GET    /api/v1/properties/{id}/expenses                List expenses
GET    /api/v1/properties/{id}/expenses/{eid}          Get expense
PUT    /api/v1/properties/{id}/expenses/{eid}          Update expense
DELETE /api/v1/properties/{id}/expenses/{eid}          Delete expense
```

### Valuations & Reports
```
POST   /api/v1/properties/{id}/valuations              Create valuation
GET    /api/v1/properties/{id}/valuations              List valuations
GET    /api/v1/valuations/{id}                         Get valuation
PUT    /api/v1/valuations/{id}                         Update valuation
DELETE /api/v1/valuations/{id}                         Delete valuation
POST   /api/v1/valuations/{id}/run                     Execute DCF engine
GET    /api/v1/valuations/{id}/reports/cash-flow-summary   Annual waterfall
GET    /api/v1/valuations/{id}/reports/key-metrics         NPV, IRR, cap rate, etc.
GET    /api/v1/valuations/{id}/reports/tenant-detail        Per-suite multi-year arrays
GET    /api/v1/valuations/{id}/reports/rent-roll            Current lease snapshot
GET    /api/v1/valuations/{id}/reports/lease-expirations    Expiration schedule by year
GET    /api/v1/valuations/{id}/reports/full                 Complete response
GET    /health                                             Health check
GET    /api/v1/enums                                       All enum values
```

---

## 7. Modeling Rules

These rules ensure the engine produces results consistent with industry-standard DCF tools:

1. **Monthly granularity, annual reporting** — compute monthly, aggregate to fiscal years
2. **Escalation on lease anniversary**, not fiscal year boundary
3. **Expense recovery**: current-year pass-through (not lagged reconciliation)
4. **General vacancy**: applied to GPR only, not to expense recoveries
5. **Gross-up**: variable expenses grossed to reference occupancy before recovery calculation
6. **Management fee circularity**: `fee = EGI × pct / (1 + pct)` — algebraic, not iterative
7. **Terminal value**: forward year NOI (year N+1), discounted from end of year N
8. **All financial math in `Decimal`** — no floating-point for monetary calculations
9. **One active lease per suite at a time** — no overlapping leases
10. **Property type differences** handled via MarketAssumptions parameters (not separate code paths)
11. **Debt service**: fixed amortizing payment calculated once at origination (not recalculated monthly)
12. **Free rent on recoveries**: binary monthly check with overlap detection

---

## 8. Testing Strategy

### Test Pyramid

```
                    ┌─────────────┐
                    │   API (4)   │  HTTP round-trip via AsyncClient
                    ├─────────────┤
                    │ Integration │  Engine-level parity scenarios
                    │    (8+7)    │  + 200-suite stress test
                    ├─────────────┤
                    │  Unit (100+)│  Pure engine module tests
                    │             │  Exact Decimal assertions
                    └─────────────┘
```

**Unit tests** (`tests/unit/`): Test each engine module in isolation with hand-calculated expected values. No database, no async. Cover: flat/pct_annual/CPI/fixed_step escalation, free rent, percentage rent, all recovery types, gross-up, waterfall arithmetic, terminal value, NPV, IRR, debt service.

**Integration tests** (`tests/integration/`): Run `run_valuation()` end-to-end on hand-calculated scenarios. Tolerance: 0.5% for dollar amounts. Scenarios: NNN single tenant, FSG, multi-tenant, pre-analysis leases, vacant suites, non-December fiscal year, sequential leases, MTM leases. Plus a 200-suite performance test (<5s).

**API tests** (`tests/api/`): Full HTTP lifecycle via FastAPI TestClient. Create property with suites/leases/market/expenses, run valuation, verify all report endpoints return correct data shapes.

### Running Tests

```bash
pytest tests/                        # All tests
pytest tests/unit/                   # Engine only
pytest tests/integration/            # Integration parity scenarios
pytest tests/api/                    # HTTP endpoints
pytest -x -q                        # Stop on first failure, quiet output
```

---

## 9. Database & Migrations

- **Development**: SQLite via aiosqlite (async), file at `opendcf.db`
- **Migrations**: Alembic with async template (`alembic/env.py` uses `run_async`)
- **Schema changes**: `alembic revision --autogenerate -m "description"` → `alembic upgrade head`
- **Test DB**: In-memory SQLite per test function (`conftest.py`)

### Migration History
```
001  Initial schema (properties, suites, tenants, leases, rent_steps, free_rent_periods,
     lease_expense_recoveries, market_leasing_profiles, property_expenses, valuations)
...
370a Add projected_annual_sales_per_sf to leases (percentage rent)
e3bc Add base_year_stop_amount to leases (base year stop recovery)
```

---

## 10. Configuration

`src/config.py` uses `pydantic-settings` to load from environment / `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `"OpenDCF"` | Application name |
| `DEBUG` | `false` | Debug mode |
| `DATABASE_URL` | `"sqlite+aiosqlite:///./opendcf.db"` | Database connection string |

---

## 11. Performance Characteristics

Measured on the pure engine (no DB overhead):

| Suites | Analysis | Time | Notes |
|--------|----------|------|-------|
| 100 | 10yr | 0.23s | With renewal engine |
| 200 | 10yr | 0.47s | Linear scaling |
| 500 | 10yr | 1.25s | Linear scaling |

The engine scales linearly with suite count. The hot path is the per-suite projection loop in `property_cashflow.py`, which is sequential. Each suite's projection involves lease projection + renewal engine (recursive, up to 5 generations) + expense recovery attachment.

---

## 12. Key Conventions

- **Sign convention**: Expenses, TI, LC, capital reserves, and debt service are stored as **negative** values. Revenue items are positive.
- **Proration**: Day-count fraction `active_days / total_days_in_period`, where both endpoints are inclusive.
- **Fiscal years**: 1-based (`year_number = 1` is the first fiscal year). Fiscal years align to `fiscal_year_end_month` (e.g., 12 = Dec 31 year-end).
- **Escalation**: Always on lease anniversary (not fiscal year boundary). Uses `add_months` for anniversary counting.
- **Rent units**: `base_rent_per_unit` is $/SF/year for commercial (`rent_payment_frequency = "annual"`) or $/unit/month for residential (`"monthly"`).
- **UUID primary keys**: All entities use UUID v4 string primary keys via `UUIDPrimaryKey` mixin.
- **Timestamps**: All entities have `created_at` and `updated_at` via `TimestampMixin`.
