from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.overview import router as overview_router
from app.audit.router import router as audit_router
from app.forecasting.router import router as forecasting_router
from app.ingestion.router import router as ingestion_router
from app.reconciliation.router import router as reconciliation_router
from app.seed.router import router as seed_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(overview_router)
api_v1_router.include_router(ingestion_router)
api_v1_router.include_router(reconciliation_router)
api_v1_router.include_router(audit_router)
api_v1_router.include_router(forecasting_router)
api_v1_router.include_router(seed_router)
