from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import CONTROLLER_HEADERS, make_test_app


@pytest.mark.asyncio
async def test_three_way_match_anomalies_and_ap_ar_approval_gate(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seed_res = await client.post("/api/v1/seed/demo", headers=CONTROLLER_HEADERS)
        assert seed_res.status_code == 200
        assert seed_res.json()["seeded"] is True

        matches = (
            await client.get("/api/v1/reconciliation/matches", headers=CONTROLLER_HEADERS)
        ).json()
        statuses = {m["status"] for m in matches}
        expected_statuses = {
            "matched",
            "variance_flagged",
            "missing_po",
            "missing_receipt",
            "duplicate_flagged",
        }
        assert expected_statuses <= statuses

        # Approve the clean CloudCore match
        clean_match = next(m for m in matches if m["status"] == "matched")
        dec = await client.post(
            f"/api/v1/audit/approvals/{clean_match['approval_id']}/decide",
            headers=CONTROLLER_HEADERS,
            json={"decision": "approved", "notes": "Verified PO and receipt"},
        )
        assert dec.status_code == 200
        assert dec.json()["status"] == "approved"

        # Check AP/AR payment allocations proposed by seed
        allocs = (
            await client.get("/api/v1/reconciliation/allocations", headers=CONTROLLER_HEADERS)
        ).json()
        assert len(allocs) >= 3

        # Approve partial AR allocation for Meridian ($40k of $84.5k) -> partially_paid
        meridian_alloc = next(
            a for a in allocs if a["invoice_number"] == "AR-2026-501"
        )
        alloc_dec = await client.post(
            f"/api/v1/audit/approvals/{meridian_alloc['approval_id']}/decide",
            headers=CONTROLLER_HEADERS,
            json={"decision": "approved", "notes": "Partial wire posted"},
        )
        assert alloc_dec.status_code == 200

        invoices = (
            await client.get(
                "/api/v1/reconciliation/invoices?direction=receivable",
                headers=CONTROLLER_HEADERS,
            )
        ).json()
        meridian_inv = next(i for i in invoices if i["invoice_number"] == "AR-2026-501")
        assert meridian_inv["amount_paid"] == 40000.0
        assert meridian_inv["payment_status"] == "partially_paid"


@pytest.mark.asyncio
async def test_semantic_po_fallback_when_po_number_omitted(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/v1/ingestion/payload",
            headers=CONTROLLER_HEADERS,
            json={
                "filename": "po.json",
                "doc_type": "purchase_order",
                "format": "json",
                "content": [
                    {
                        "po_number": "PO-SEM-99",
                        "vendor_name": "Orbital Logistics",
                        "issue_date": "2026-11-01",
                        "total_amount": 3000.00,
                        "qty": 5,
                    }
                ],
            },
        )
        await client.post(
            "/api/v1/ingestion/payload",
            headers=CONTROLLER_HEADERS,
            json={
                "filename": "gr.json",
                "doc_type": "goods_receipt",
                "format": "json",
                "content": [
                    {
                        "receipt_number": "GR-SEM-99",
                        "po_number": "PO-SEM-99",
                        "received_date": "2026-11-03",
                        "total_amount": 3000.00,
                        "qty": 5,
                    }
                ],
            },
        )
        await client.post(
            "/api/v1/ingestion/payload",
            headers=CONTROLLER_HEADERS,
            json={
                "filename": "inv.json",
                "doc_type": "invoice",
                "format": "json",
                "content": [
                    {
                        "invoice_number": "INV-ORB-1",
                        "direction": "payable",
                        "counterparty_name": "Orbital Logistics",
                        "issue_date": "2026-11-04",
                        "subtotal": 3000.00,
                        "total_amount": 3000.00,
                        "qty": 5,
                    }
                ],
            },
        )

        matches = (
            await client.get("/api/v1/reconciliation/matches", headers=CONTROLLER_HEADERS)
        ).json()
        assert len(matches) == 1
        assert matches[0]["po_number"] == "PO-SEM-99"
        assert matches[0]["status"] == "matched"
        assert any(a["code"] == "SEMANTIC_PO_INFERRED" for a in matches[0]["anomalies"])
