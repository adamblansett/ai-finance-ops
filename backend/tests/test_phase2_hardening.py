import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect

from alembic import command
from app.audit.service import record_audit_event, verify_audit_chain
from app.core.auth import Actor
from app.db.session import build_engine
from tests.conftest import make_test_app


@pytest.mark.asyncio
async def test_persisted_user_register_login_and_refresh(tmp_path: Path) -> None:
    app = make_test_app(tmp_path, auth_require_token=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Unauthenticated request rejected when auth_require_token=True
        unauth = await client.get("/api/v1/auth/me")
        assert unauth.status_code == 401

        # First registered user receives admin role; subsequent users get analyst
        reg1 = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "admin@finops.local",
                "full_name": "Admin User",
                "password": "StrongPassword123!",
            },
        )
        assert reg1.status_code == 201
        assert reg1.json()["role"] == "admin"

        reg2 = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "analyst@finops.local",
                "full_name": "Analyst User",
                "password": "StrongPassword123!",
            },
        )
        assert reg2.status_code == 201
        assert reg2.json()["role"] == "analyst"

        # Duplicate email blocked with 409
        dup = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "analyst@finops.local",
                "full_name": "Dup",
                "password": "StrongPassword123!",
            },
        )
        assert dup.status_code == 409

        # Invalid password rejected with 401
        bad_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "analyst@finops.local", "password": "wrong-password"},
        )
        assert bad_login.status_code == 401

        # Valid login returns access + refresh token
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "analyst@finops.local", "password": "StrongPassword123!"},
        )
        assert login.status_code == 200
        tokens = login.json()
        assert tokens["access_token"]
        assert tokens["refresh_token"]

        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["email"] == "analyst@finops.local"
        assert me.json()["role"] == "analyst"

        # Refresh token cannot be used directly as access token
        wrong_use = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
        )
        assert wrong_use.status_code == 401

        # Refresh endpoint exchanges refresh_token for fresh access_token
        refreshed = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["actor"]["email"] == "analyst@finops.local"


@pytest.mark.asyncio
async def test_rate_limiter_enforces_429_and_exempts_health(tmp_path: Path) -> None:
    app = make_test_app(
        tmp_path,
        rate_limit_enabled=True,
        rate_limit_requests_per_minute=3,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for idx in range(3):
            ok_res = await client.get("/api/v1/auth/me")
            assert ok_res.status_code == 200
            assert ok_res.headers["x-ratelimit-limit"] == "3"
            assert ok_res.headers["x-ratelimit-remaining"] == str(2 - idx)

        limited = await client.get("/api/v1/auth/me")
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) >= 1

        # Health endpoint remains exempt so k8s/docker probes never fail
        health = await client.get("/api/v1/health/live")
        assert health.status_code == 200


@pytest.mark.asyncio
async def test_concurrent_audit_event_writes_maintain_hash_chain(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Ensure schema tables are initialized via get_db dependency
        assert (await client.get("/api/v1/audit/events")).status_code == 200

    actor = Actor(email="conc@test.local", role="controller", auth_method="test")

    async def _write_event(idx: int) -> None:
        async with app.state.session_factory() as session:
            await record_audit_event(
                session,
                event_type="test.concurrent",
                actor=actor,
                entity_type="invoice",
                entity_id=f"inv-{idx}",
                action="checked",
                details={"idx": idx},
            )
            await session.commit()

    await asyncio.gather(*(_write_event(i) for i in range(10)))

    async with app.state.session_factory() as session:
        chain = await verify_audit_chain(session)
        assert chain.valid is True
        assert chain.total_events == 10


def test_alembic_migrations_are_reversible(tmp_path: Path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "alembic_rev.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "0001_initial_schema")

    async def _list_tables() -> set[str]:
        engine = build_engine(db_url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync_conn: set(inspect(sync_conn).get_table_names())
                )
        finally:
            await engine.dispose()

    tables_after_downgrade = asyncio.run(_list_tables())
    assert "users" not in tables_after_downgrade
    assert "background_jobs" not in tables_after_downgrade
    assert "semantic_embeddings" not in tables_after_downgrade

    command.upgrade(alembic_cfg, "head")
    tables_after_reupgrade = asyncio.run(_list_tables())
    assert {"users", "background_jobs", "semantic_embeddings"} <= tables_after_reupgrade
