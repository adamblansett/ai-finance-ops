import json

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_roles
from app.core.config import Settings, get_settings
from app.db.models import IngestedDocument
from app.db.session import get_db
from app.ingestion.parsers import ingest_bytes, to_document_out
from app.ingestion.schemas import (
    DocType,
    IngestedDocumentOut,
    IngestionPayloadRequest,
    IngestionResultOut,
)
from app.llm.router import LLMRouter, get_llm_router

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


def _resolve_settings(request: Request, fallback: Settings) -> Settings:
    app_cfg = getattr(request.app.state, "settings", None)
    if isinstance(app_cfg, Settings):
        return app_cfg
    return fallback


@router.get("/documents", response_model=list[IngestedDocumentOut])
async def list_ingested_documents(
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[IngestedDocumentOut]:
    """List ingested documents and duplicate-block attempts newest first."""
    stmt = select(IngestedDocument).order_by(IngestedDocument.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [to_document_out(r) for r in rows]


@router.post("/upload", response_model=IngestionResultOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    doc_type: DocType = Form(...),
    auto_reconcile: bool = Form(True),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require_roles("analyst", "controller", "admin")),
) -> IngestionResultOut:
    """Upload a CSV, JSON, or PDF document with SHA-256 duplicate protection."""
    raw_bytes = await file.read()
    cfg = _resolve_settings(request, settings)
    return await ingest_bytes(
        db,
        filename=file.filename or "upload.dat",
        doc_type=doc_type,
        content=raw_bytes,
        content_type=file.content_type or "application/octet-stream",
        llm_router=llm_router,
        settings=cfg,
        actor=actor,
        auto_reconcile=auto_reconcile,
    )


@router.post("/payload", response_model=IngestionResultOut, status_code=status.HTTP_201_CREATED)
async def ingest_inline_payload(
    payload: IngestionPayloadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require_roles("analyst", "controller", "admin")),
) -> IngestionResultOut:
    """Ingest a JSON or CSV payload inline for API integrations and UI workflows."""
    if isinstance(payload.content, str):
        raw_bytes = payload.content.encode("utf-8")
    else:
        raw_bytes = json.dumps(payload.content, sort_keys=True).encode("utf-8")
    content_type = "application/json" if payload.format == "json" else "text/csv"
    cfg = _resolve_settings(request, settings)
    return await ingest_bytes(
        db,
        filename=payload.filename,
        doc_type=payload.doc_type,
        content=raw_bytes,
        content_type=content_type,
        llm_router=llm_router,
        settings=cfg,
        actor=actor,
        auto_reconcile=payload.auto_reconcile,
    )
