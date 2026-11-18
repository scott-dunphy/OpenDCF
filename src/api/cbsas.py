from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.services import cbsa

router = APIRouter(prefix="/api/v1/cbsas", tags=["markets"])


class CbsaRead(BaseModel):
    code: str
    title: str
    kind: str
    land_share: float | None = None  # share of the ZIP's land area, for a ZIP lookup


@router.get("", response_model=list[CbsaRead])
async def list_cbsas(q: str | None = None, zip: str | None = None, limit: int = 20) -> list[CbsaRead]:
    """Census markets: by ZIP (largest land share first), or searched by name or code."""
    if zip:
        return [CbsaRead(code=c.code, title=c.title, kind=c.kind, land_share=share) for c, share in cbsa.zip_candidates(zip)]
    found = cbsa.search(q, limit) if q else sorted(cbsa.all_cbsas().values(), key=lambda c: c.title)[:limit]
    return [CbsaRead(code=c.code, title=c.title, kind=c.kind) for c in found]


@router.get("/{code}", response_model=CbsaRead)
async def get_cbsa(code: str) -> CbsaRead:
    c = cbsa.get(code)
    if c is None:
        raise HTTPException(404, "Unknown CBSA code")
    return CbsaRead(code=c.code, title=c.title, kind=c.kind)
