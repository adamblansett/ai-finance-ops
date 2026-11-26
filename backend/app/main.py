import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.auth import Actor
from app.core.config import Settings, get_settings, validate_production_security
from app.core.logging import configure_logging
from app.core.middleware import SecurityHeadersMiddleware
from app.core.rate_limit import RateLimiter, RateLimitMiddleware
from app.core.telemetry import init_telemetry
from app.db.session import build_engine, build_session_factory, ensure_db_initialized
from app.llm.embeddings import EmbeddingService
from app.llm.router import LLMRouter
from app.seed.demo_data import seed_demo_dataset


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    await ensure_db_initialized(application)
    cfg: Settings = application.state.settings
    if cfg.seed_demo_data:
        async with application.state.session_factory() as session:
            await seed_demo_dataset(
                session,
                llm_router=application.state.llm_router,
                settings=cfg,
                actor=Actor(
                    email="system-seed@acme-finops.local",
                    role="admin",
                    auth_method="lifespan",
                ),
                reset=False,
            )
    try:
        yield
    finally:
        await application.state.rate_limiter.close()
        await application.state.db_engine.dispose()


def create_app(settings_override: Settings | None = None) -> FastAPI:
    """Construct and configure the FastAPI application."""
    cfg = settings_override or get_settings()
    validate_production_security(cfg)
    configure_logging(cfg.log_level)
    init_telemetry(cfg)

    engine = build_engine(cfg.database_url)
    session_factory = build_session_factory(engine)
    rate_limiter = RateLimiter(
        limit=cfg.rate_limit_requests_per_minute,
        window_seconds=60,
        redis_url=cfg.redis_url,
    )

    application = FastAPI(
        title=cfg.app_name,
        version="0.2.0",
        description=(
            "Open-source, self-hosted AI finance operations platform for invoice "
            "reconciliation, AP/AR matching, cash flow forecasting, and expense auditing."
        ),
        lifespan=_lifespan,
    )
    application.state.settings = cfg
    application.state.db_engine = engine
    application.state.session_factory = session_factory
    application.state.db_init_lock = asyncio.Lock()
    application.state.db_initialized = False
    application.state.llm_router = LLMRouter(cfg)
    application.state.embedding_service = EmbeddingService(cfg)
    application.state.rate_limiter = rate_limiter

    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RateLimitMiddleware, settings=cfg, limiter=rate_limiter)
    application.add_middleware(SecurityHeadersMiddleware, settings=cfg)
    application.include_router(api_v1_router, prefix=cfg.api_v1_prefix)
    return application


app = create_app()
