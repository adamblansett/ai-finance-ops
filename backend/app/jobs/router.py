from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_roles
from app.core.config import Settings, get_settings
from app.db.models import BackgroundJob
from app.db.session import get_db
from app.forecasting.schemas import ForecastScenarioRequest
from app.jobs.schemas import BackgroundJobOut
from app.jobs.service import enqueue_job, to_job_out
from app.llm.embeddings import EmbeddingService, get_embedding_service
from app.llm.router import LLMRouter, get_llm_router

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _resolve_settings(request: Request, fallback: Settings) -> Settings:
    app_cfg = getattr(request.app.state, "settings", None)
    return app_cfg if isinstance(app_cfg, Settings) else fallback


@router.get("", response_model=list[BackgroundJobOut])
async def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[BackgroundJobOut]:
    rows = (
        await db.execute(
            select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [to_job_out(r) for r in rows]


@router.get("/{job_id}", response_model=BackgroundJobOut)
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> BackgroundJobOut:
    job = await db.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Background job '{job_id}' not found.",
        )
    return to_job_out(job)


@router.post(
    "/reconcile-batch",
    response_model=BackgroundJobOut,
    status_code=status.HTTP_201_CREATED,
)
async def enqueue_reconcile_batch(
    request: Request,
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require_roles("analyst", "controller", "admin")),
) -> BackgroundJobOut:
    job = await enqueue_job(
        db,
        job_type="reconcile_batch",
        payload={},
        session_factory=request.app.state.session_factory,
        llm_router=llm_router,
        embedding_service=embedding_service,
        settings=_resolve_settings(request, settings),
        actor=actor,
    )
    return to_job_out(job)


@router.post(
    "/ap-ar-match",
    response_model=BackgroundJobOut,
    status_code=status.HTTP_201_CREATED,
)
async def enqueue_ap_ar_match(
    request: Request,
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require_roles("analyst", "controller", "admin")),
) -> BackgroundJobOut:
    job = await enqueue_job(
        db,
        job_type="ap_ar_match",
        payload={},
        session_factory=request.app.state.session_factory,
        llm_router=llm_router,
        embedding_service=embedding_service,
        settings=_resolve_settings(request, settings),
        actor=actor,
    )
    return to_job_out(job)


@router.post(
    "/forecast-snapshot",
    response_model=BackgroundJobOut,
    status_code=status.HTTP_201_CREATED,
)
async def enqueue_forecast_snapshot(
    request: Request,
    scenario: ForecastScenarioRequest | None = None,
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require_roles("analyst", "controller", "admin")),
) -> BackgroundJobOut:
    payload = scenario.model_dump() if scenario else {}
    job = await enqueue_job(
        db,
        job_type="forecast_snapshot",
        payload=payload,
        session_factory=request.app.state.session_factory,
        llm_router=llm_router,
        embedding_service=embedding_service,
        settings=_resolve_settings(request, settings),
        actor=actor,
    )
    return to_job_out(job)
