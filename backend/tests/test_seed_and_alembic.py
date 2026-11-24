import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect

from alembic import command
from app.db.session import build_engine
from tests.conftest import CONTROLLER_HEADERS, make_test_app


@pytest.mark.asyncio
async def test_seed_idempotency_and_overview_kpis(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/v1/seed/demo", headers=CONTROLLER_HEADERS)
        assert first.status_code == 200
        assert first.json()["seeded"] is True
        assert first.json()["vendors"] == 5
        assert first.json()["invoices"] == 8

        second = await client.post("/api/v1/seed/demo", headers=CONTROLLER_HEADERS)
        assert second.status_code == 200
        assert second.json()["seeded"] is False

        overview = await client.get("/api/v1/overview", headers=CONTROLLER_HEADERS)
        assert overview.status_code == 200
        ov = overview.json()
        assert ov["total_cash"] == 500000.0
        assert ov["open_ar_total"] == 126500.0
        assert ov["pending_approvals_count"] >= 10
        assert ov["audit_chain_valid"] is True


def test_alembic_initial_migration_creates_all_tables(tmp_path: Path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "alembic_test.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(alembic_cfg, "head")

    async def _list_tables() -> set[str]:
        engine = build_engine(db_url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync_conn: set(inspect(sync_conn).get_table_names())
                )
        finally:
            await engine.dispose()

    tables = asyncio.run(_list_tables())
    expected = {
        "vendors",
        "purchase_orders",
        "goods_receipts",
        "ingested_documents",
        "invoices",
        "three_way_matches",
        "bank_transactions",
        "payment_allocations",
        "expenses",
        "recurring_commitments",
        "cash_account_snapshots",
        "approval_requests",
        "audit_events",
        "alembic_version",
    }
    assert expected <= tables
