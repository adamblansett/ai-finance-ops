from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_test_app


@pytest.mark.asyncio
async def test_health_and_readiness_endpoints(tmp_path: Path) -> None:
    test_app = make_test_app(tmp_path)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready"):
            response = await client.get(path)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["service"] == "ai-finance-ops"
            assert data["app_name"] == "AI Finance Operations"
            assert data["database"] == "ok"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_readiness_returns_503_when_db_unreachable(tmp_path: Path) -> None:
    missing_dir = tmp_path / "nonexistent_dir" / "sub" / "nope.db"
    cfg = Settings(
        database_url=f"sqlite+aiosqlite:///{missing_dir.as_posix()}",
        auto_create_tables=False,
    )
    test_app = create_app(cfg)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        live = await client.get("/api/v1/health/live")
        assert live.status_code == 200
        ready = await client.get("/api/v1/health/ready")
        assert ready.status_code == 503
        assert ready.json()["database"] == "unreachable"


def test_production_security_validation_rejects_default_secret() -> None:
    insecure = Settings(app_env="production")
    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        create_app(insecure)
