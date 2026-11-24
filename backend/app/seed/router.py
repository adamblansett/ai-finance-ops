from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, require_roles
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router
from app.seed.demo_data import SeedSummaryOut, seed_demo_dataset

router = APIRouter(prefix="/seed", tags=["seed"])


@router.post("/demo", response_model=SeedSummaryOut)
async def load_demo_seed(
    request: Request,
    reset: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require_roles("controller", "admin")),
) -> SeedSummaryOut:
    """Populate realistic Phase 1 finance data (idempotent unless reset=true)."""
    app_cfg = getattr(request.app.state, "settings", None)
    cfg = app_cfg if isinstance(app_cfg, Settings) else settings
    return await seed_demo_dataset(
        db,
        llm_router=llm_router,
        settings=cfg,
        actor=actor,
        reset=reset,
    )
