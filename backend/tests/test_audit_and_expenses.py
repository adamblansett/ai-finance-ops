from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.db.models import AuditEvent
from tests.conftest import ANALYST_HEADERS, CONTROLLER_HEADERS, make_test_app


@pytest.mark.asyncio
async def test_expense_policy_rules_rbac_and_audit_chain(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Clean expense <= $250 -> auto_approved
        clean_res = await client.post(
            "/api/v1/audit/expenses",
            headers=ANALYST_HEADERS,
            json={
                "employee_name": "Jane Doe",
                "employee_email": "jane@test.local",
                "merchant": "Cafe Uno",
                "expense_date": "2026-11-18",
                "category": "meals",
                "tax_category": "deductible_50",
                "amount": 95.0,
                "receipt_hash": "rcpt-unique-1",
                "description": "Team lunch",
            },
        )
        assert clean_res.status_code == 201
        assert clean_res.json()["status"] == "auto_approved"

        # 2. Duplicate receipt + wrong tax category -> flagged
        dup_res = await client.post(
            "/api/v1/audit/expenses",
            headers=ANALYST_HEADERS,
            json={
                "employee_name": "Jane Doe",
                "employee_email": "jane@test.local",
                "merchant": "Cafe Uno",
                "expense_date": "2026-11-18",
                "category": "meals",
                "tax_category": "deductible_100",
                "amount": 95.0,
                "receipt_hash": "rcpt-unique-1",
                "description": "Duplicate lunch",
            },
        )
        assert dup_res.status_code == 201
        dup_body = dup_res.json()
        assert dup_body["status"] == "flagged"
        codes = {v["rule_code"] for v in dup_body["policy_violations"]}
        assert {"DUPLICATE_RECEIPT", "TAX_CATEGORY_MISMATCH"} <= codes
        approval_id = dup_body["approval_id"]
        assert approval_id is not None

        # 3. Analyst cannot decide HITL approval -> 403
        forbidden = await client.post(
            f"/api/v1/audit/approvals/{approval_id}/decide",
            headers=ANALYST_HEADERS,
            json={"decision": "rejected", "notes": "Attempted override"},
        )
        assert forbidden.status_code == 403

        # 4. Controller rejects flagged expense -> 200; re-deciding -> 409
        decided = await client.post(
            f"/api/v1/audit/approvals/{approval_id}/decide",
            headers=CONTROLLER_HEADERS,
            json={"decision": "rejected", "notes": "Duplicate submission"},
        )
        assert decided.status_code == 200
        assert decided.json()["status"] == "rejected"

        conflict = await client.post(
            f"/api/v1/audit/approvals/{approval_id}/decide",
            headers=CONTROLLER_HEADERS,
            json={"decision": "approved", "notes": "Second try"},
        )
        assert conflict.status_code == 409

        # 5. Audit chain verifies intact
        verify_ok = await client.get("/api/v1/audit/events/verify", headers=CONTROLLER_HEADERS)
        assert verify_ok.status_code == 200
        assert verify_ok.json()["valid"] is True
        assert verify_ok.json()["total_events"] >= 3

        # 6. Tamper detection: mutate row #1 directly in DB
        async with app.state.session_factory() as session:
            await session.execute(
                update(AuditEvent)
                .where(AuditEvent.sequence_no == 1)
                .values(action="tampered_action")
            )
            await session.commit()

        verify_broken = await client.get("/api/v1/audit/events/verify", headers=CONTROLLER_HEADERS)
        assert verify_broken.status_code == 200
        assert verify_broken.json()["valid"] is False
        assert verify_broken.json()["broken_sequence_no"] == 1
