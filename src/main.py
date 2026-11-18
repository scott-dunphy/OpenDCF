import hashlib
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.router import api_router
from src.config import settings
from src.services.valuation_lock import ValuationFrozenError
from src.db.session import engine
from src.models.base import Base

# Import all models so SQLAlchemy picks them up for table creation
import src.models.property  # noqa: F401
import src.models.lease  # noqa: F401
import src.models.market  # noqa: F401
import src.models.expense  # noqa: F401
import src.models.valuation  # noqa: F401
import src.models.comparable  # noqa: F401
import src.models.document  # noqa: F401


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


@app.exception_handler(ValuationFrozenError)
async def frozen_valuation(request: Request, exc: ValuationFrozenError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.middleware("http")
async def audit_request_source(request: Request, call_next):
    """Tag audit log entries with the request that caused them."""
    from src.services.audit import audit_source
    if request.method != "GET":
        audit_source.set(f"{request.method} {request.url.path}"[:255])
    return await call_next(request)


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

# Local asset URLs in index.html ("/frontend/app.js?v=55") get ?v=<hash of the file's content>, so
# browsers fetch an asset again exactly when it changes; no hand-bumped version numbers
_ASSET_URL = re.compile(r'((?:src|href)=")/frontend/([^"?#]+)(?:\?[^"#]*)?(")')
_asset_hashes: dict[Path, tuple[tuple[int, int], str]] = {}


def _asset_hash(path: Path) -> str | None:
    """Short content hash, recomputed only when the file's mtime or size changes."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    cached = _asset_hashes.get(path)
    if cached is None or cached[0] != key:
        cached = (key, hashlib.sha256(path.read_bytes()).hexdigest()[:10])
        _asset_hashes[path] = cached
    return cached[1]


def render_index(frontend_dir: Path) -> str:
    def versioned(m: re.Match) -> str:
        digest = _asset_hash(frontend_dir / m.group(2))
        return m.group(0) if digest is None else f"{m.group(1)}/frontend/{m.group(2)}?v={digest}{m.group(3)}"

    return _ASSET_URL.sub(versioned, (frontend_dir / "index.html").read_text(encoding="utf-8"))


if _frontend_dir.exists():
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def serve_frontend():
        return HTMLResponse(render_index(_frontend_dir), headers={"Cache-Control": "no-cache"})

    app.mount("/frontend", StaticFiles(directory=str(_frontend_dir)), name="frontend")
