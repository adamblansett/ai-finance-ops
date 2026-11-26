import asyncio
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.core.config import Settings
from app.db.base import utcnow
from app.db.models import BackgroundJob, Invoice
from app.forecasting.engine import build_13_week_forecast
from app.forecasting.schemas import ForecastScenarioRequest
from app.jobs.schemas import BackgroundJobOut, JobType
from app.llm.embeddings import EmbeddingService
from app.llm.router import LLMRouter
from app.reconciliation.ap_ar import propose_payment_allocations
from app.reconciliation.three_way import run_three_way_match

REDIS_JOB_QUEUE = "finops:jobs"


def to_job_out(job: BackgroundJob) -> BackgroundJobOut:
    return BackgroundJobOut(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress_pct=job.progress_pct,
        payload=job.payload_json,
        result=job.result_json,
        error_message=job.error_message,
        created_by=job.created_by,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


async def execute_job(
    db: AsyncSession,
    *,
    job: BackgroundJob,
    llm_router: LLMRouter,
    embedding_service: EmbeddingService,
    settings: Settings,
    actor: Actor,
) -> BackgroundJob:
    """Execute a persisted BackgroundJob and record completion or failure."""
    job.status = "running"
    job.started_at = utcnow()
    job.progress_pct = 15
    await db.flush()

    try:
        result: dict[str, Any]
        if job.job_type == "reconcile_batch":
            stmt = (
                select(Invoice)
                .where(
                    Invoice.direction == "payable",
                    Invoice.match_status.notin_(["approved", "rejected"]),
                )
                .order_by(Invoice.created_at.asc())
            )
            invoices = list((await db.execute(stmt)).scalars().all())
            matched = 0
            for idx, inv in enumerate(invoices, start=1):
                res = await run_three_way_match(
                    db,
                    invoice=inv,
                    llm_router=llm_router,
                    settings=settings,
                    actor=actor,
                    embedding_service=embedding_service,
                )
                if res.status == "matched":
                    matched += 1
                job.progress_pct = min(95, 15 + int((idx / max(1, len(invoices))) * 80))
            result = {
                "processed_count": len(invoices),
                "matched_count": matched,
                "flagged_count": len(invoices) - matched,
            }

        elif job.job_type == "ap_ar_match":
            allocs = await propose_payment_allocations(
                db, llm_router=llm_router, actor=actor
            )
            result = {"proposed_count": len(allocs)}

        elif job.job_type == "forecast_snapshot":
            scenario = ForecastScenarioRequest(**(job.payload_json or {}))
            fc = await build_13_week_forecast(db, llm_router=llm_router, scenario=scenario)
            result = {
                "starting_cash": fc.starting_cash,
                "ending_cash_week_13": fc.ending_cash_week_13,
                "lowest_cash_balance": fc.lowest_cash_balance,
                "buffer_breach_week": fc.buffer_breach_week,
            }

        else:
            raise ValueError(f"Unsupported job type '{job.job_type}'.")

        job.status = "completed"
        job.progress_pct = 100
        job.result_json = result
        job.completed_at = utcnow()
        await record_audit_event(
            db,
            event_type="job.completed",
            actor=actor,
            entity_type="background_job",
            entity_id=job.id,
            action=job.job_type,
            details=result,
        )
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = utcnow()

    await db.commit()
    await db.refresh(job)
    return job


async def _run_background_task(
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    llm_router: LLMRouter,
    embedding_service: EmbeddingService,
    settings: Settings,
    actor: Actor,
) -> None:
    async with session_factory() as session:
        job = await session.get(BackgroundJob, job_id)
        if job is not None:
            await execute_job(
                session,
                job=job,
                llm_router=llm_router,
                embedding_service=embedding_service,
                settings=settings,
                actor=actor,
            )


async def enqueue_job(
    db: AsyncSession,
    *,
    job_type: JobType,
    payload: dict[str, Any] | None,
    session_factory: async_sessionmaker[AsyncSession],
    llm_router: LLMRouter,
    embedding_service: EmbeddingService,
    settings: Settings,
    actor: Actor,
) -> BackgroundJob:
    """Create a BackgroundJob and dispatch via inline, async task, or Redis queue."""
    job = BackgroundJob(
        job_type=job_type,
        status="queued",
        progress_pct=0,
        payload_json=payload or {},
        created_by=actor.email,
    )
    db.add(job)
    await db.flush()
    await record_audit_event(
        db,
        event_type="job.enqueued",
        actor=actor,
        entity_type="background_job",
        entity_id=job.id,
        action=job_type,
        details={"mode": settings.task_execution_mode},
    )
    await db.commit()
    await db.refresh(job)

    mode = settings.task_execution_mode
    if mode == "redis" and settings.redis_url.startswith("redis"):
        try:
            client = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1.0)
            await client.rpush(REDIS_JOB_QUEUE, job.id)
            await client.aclose()
            return job
        except Exception:
            mode = "async"

    if mode == "async":
        asyncio.create_task(
            _run_background_task(
                job.id,
                session_factory,
                llm_router,
                embedding_service,
                settings,
                actor,
            )
        )
        return job

    return await execute_job(
        db,
        job=job,
        llm_router=llm_router,
        embedding_service=embedding_service,
        settings=settings,
        actor=actor,
    )
