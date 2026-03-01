# OpenDCF

OpenDCF is an open-source commercial real estate valuation engine that models lease-level cash flows, recoveries, market leasing assumptions, and debt to produce DCF outputs including NOI, NPV, IRR, and terminal value.

## What It Includes

- FastAPI backend (`/api/v1`) for property, lease, market, expense, and valuation workflows
- Built-in frontend at `http://localhost:8001`
- Pure-Python valuation engine (`src/engine`) with deterministic `Decimal` math
- SQLite + Alembic migrations
- Unit, integration, and API test suites

## Quick Start

### 1. Create environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure environment (optional)

Defaults are provided in `.env.example`:

```bash
cp .env.example .env
```

### 3. Run database migrations

```bash
alembic upgrade head
```

### 4. Start the API + frontend

```bash
uvicorn src.main:app --host 127.0.0.1 --port 8001 --reload
```

Then open:

- App UI: `http://localhost:8001`
- OpenAPI docs: `http://localhost:8001/docs`
- Health check: `http://localhost:8001/health`

## API Notes

- Base URL: `http://localhost:8001/api/v1`
- Percent fields are decimals in API payloads (example: `0.05` = 5%)
- Dollar amounts should be sent as decimal-compatible values

Example: create a property

```bash
curl -X POST "http://localhost:8001/api/v1/properties" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sample Office",
    "property_type": "office",
    "total_area": "100000",
    "area_unit": "sf",
    "analysis_start_date": "2026-01-01",
    "analysis_period_months": 120,
    "fiscal_year_end_month": 12
  }'
```

## Run Tests

```bash
pytest -q
```

Or by suite:

```bash
pytest tests/unit/
pytest tests/integration/
pytest tests/api/
```

## Project Structure

- `src/main.py` - FastAPI app + frontend mount
- `src/api/` - REST endpoints
- `src/services/valuation_service.py` - DB-to-engine orchestration
- `src/engine/` - core valuation logic
- `src/models/` - SQLAlchemy models
- `src/schemas/` - Pydantic request/response models
- `alembic/` - migrations
- `frontend/` - single-page app
- `tests/` - unit/integration/API tests

## Documentation

- Architecture: `ARCHITECTURE.md`
- Full endpoint reference: `.claude/skills/ares-valuation/references/api-reference.md`

