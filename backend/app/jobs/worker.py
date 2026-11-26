import asyncio
import contextlib
import signal

import structlog
from redis.asyncio import Redis

from app.core.auth import Actor
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import BackgroundJob
from app.db.session import build_engine, build_session_factory, init_db
from app.jobs.service import REDIS_JOB_QUEUE, execute_job
from app.llm.embeddings import EmbeddingService
from app.llm.router import LLMRouter

logger = structlog.get_logger(__name__)


async def run_worker() -> None:
    """Consume queued background jobs from Redis with graceful shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL must be configured to run the job worker.")

    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    if settings.auto_create_tables:
        await init_db(engine)

    llm_router = LLMRouter(settings)
    embedding_service = EmbeddingService(settings)
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    logger.info("finops_worker_started", queue=REDIS_JOB_QUEUE)
    try:
        while not stop_event.is_set():
            item = await redis_client.blpop([REDIS_JOB_QUEUE], timeout=2)
            if not item:
                continue
            _, job_id = item
            async with session_factory() as session:
                job = await session.get(BackgroundJob, job_id)
                if job is not None and job.status == "queued":
                    await execute_job(
                        session,
                        job=job,
                        llm_router=llm_router,
                        embedding_service=embedding_service,
                        settings=settings,
                        actor=Actor(
                            email=job.created_by,
                            role="controller",
                            auth_method="worker",
                        ),
                    )
                    logger.info("finops_worker_job_done", job_id=job_id, status=job.status)
    finally:
        await redis_client.aclose()
        await engine.dispose()
        logger.info("finops_worker_stopped")


if __name__ == "__main__":
    asyncio.run(run_worker())
