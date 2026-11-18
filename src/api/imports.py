import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.models.portfolio import ImportJob
from src.schemas.imports import ImportCommitRequest, ImportJobRead, ImportOptions
from src.services.published_import.service import ImportService, job_to_read
from src.services.published_import.template import build_template

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.get("/template.xlsx")
async def download_template() -> Response:
    """Blank workbook in XL4ADW layout with every column the importer recognizes."""
    return Response(
        content=build_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="ares_import_template.xlsx"'},
    )


@router.post("/preview", response_model=ImportJobRead, status_code=status.HTTP_201_CREATED)
async def preview_import(
    request: Request,
    filename: str = Query(default="import.xlsx", max_length=255),
    options: str | None = Query(default=None, description="ImportOptions as JSON"),
    db: AsyncSession = Depends(get_session),
) -> ImportJobRead:
    """
    Upload a workbook as the raw request body (Content-Type: application/octet-stream).
    Accepts PUBLISHED Enterprise Excel Add-in (XL4ADW) input sheets or plain sheets with
    one header row. Nothing is created until the job is committed.
    """
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Workbook too large (25 MB max)")
    try:
        opts = ImportOptions.model_validate(json.loads(options)) if options else ImportOptions()
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid options: {exc}")
    try:
        job = await ImportService(db).preview(data, filename, opts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return job_to_read(job)


@router.get("", response_model=list[ImportJobRead])
async def list_imports(db: AsyncSession = Depends(get_session)) -> list[ImportJobRead]:
    rows = (await db.execute(select(ImportJob).order_by(ImportJob.created_at.desc()).limit(100))).scalars().all()
    return [job_to_read(j) for j in rows]


async def _get_job(db: AsyncSession, job_id: str) -> ImportJob:
    job = await db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    return job


@router.get("/{job_id}", response_model=ImportJobRead)
async def get_import(job_id: str, db: AsyncSession = Depends(get_session)) -> ImportJobRead:
    return job_to_read(await _get_job(db, job_id))


@router.post("/{job_id}/commit", response_model=ImportJobRead)
async def commit_import(
    job_id: str, body: ImportCommitRequest, db: AsyncSession = Depends(get_session)
) -> ImportJobRead:
    """Create the previewed properties (and assumption profiles) in Ares."""
    job = await _get_job(db, job_id)
    try:
        job = await ImportService(db).commit(job, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return job_to_read(job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_import(job_id: str, db: AsyncSession = Depends(get_session)) -> None:
    """Delete the import record (created properties are kept)."""
    job = await _get_job(db, job_id)
    await db.delete(job)
    await db.commit()
