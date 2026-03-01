from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.router import api_router
from src.config import settings
from src.db.session import engine
from src.models.base import Base

# Import all models so SQLAlchemy picks them up for table creation
import src.models.property  # noqa: F401
import src.models.lease  # noqa: F401
import src.models.market  # noqa: F401
import src.models.expense  # noqa: F401
import src.models.valuation  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create all tables on startup (development convenience)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "Commercial Real Estate DCF Valuation Engine — industry-standard modeling for "
        "multifamily, office, retail, industrial, and self-storage properties."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.get("/api/v1/enums", tags=["metadata"])
async def get_enums() -> dict:
    """Return all enum values for UI dropdowns."""
    from src.engine.transfer_tax import transfer_tax_presets_metadata
    from src.schemas.common import (
        AreaUnit, EscalationType, ExpenseCategoryEnum,
        LeaseType, PropertyType, RecoveryType, ValuationStatus,
    )
    return {
        "property_types": [e.value for e in PropertyType],
        "area_units": [e.value for e in AreaUnit],
        "escalation_types": [e.value for e in EscalationType],
        "recovery_types": [e.value for e in RecoveryType],
        "expense_categories": [e.value for e in ExpenseCategoryEnum],
        "lease_types": [e.value for e in LeaseType],
        "valuation_statuses": [e.value for e in ValuationStatus],
        "transfer_tax_presets": transfer_tax_presets_metadata(),
    }


# ── Frontend ──────────────────────────────────────────────────
_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"

if _frontend_dir.exists():
    @app.get("/", response_class=FileResponse, include_in_schema=False)
    async def serve_frontend():
        return FileResponse(str(_frontend_dir / "index.html"))

    app.mount("/frontend", StaticFiles(directory=str(_frontend_dir)), name="frontend")
