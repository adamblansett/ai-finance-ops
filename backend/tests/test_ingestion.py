import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import CONTROLLER_HEADERS, build_minimal_pdf, make_test_app


@pytest.mark.asyncio
async def test_csv_json_ingestion_and_duplicate_sha256_block(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        po_csv = (
            b"po_number,vendor_name,issue_date,total_amount,qty\n"
            b"PO-TEST-01,Acme Cloud Inc,2026-11-01,5000.00,10\n"
        )
        po_res = await client.post(
            "/api/v1/ingestion/upload",
            headers=CONTROLLER_HEADERS,
            data={"doc_type": "purchase_order", "auto_reconcile": "true"},
            files={"file": ("pos.csv", po_csv, "text/csv")},
        )
        assert po_res.status_code == 201
        assert po_res.json()["document"]["parsed_records_count"] == 1

        gr_csv = (
            b"receipt_number,po_number,received_date,total_amount,qty\n"
            b"GR-TEST-01,PO-TEST-01,2026-11-05,5000.00,10\n"
        )
        gr_res = await client.post(
            "/api/v1/ingestion/upload",
            headers=CONTROLLER_HEADERS,
            data={"doc_type": "goods_receipt"},
            files={"file": ("receipts.csv", gr_csv, "text/csv")},
        )
        assert gr_res.status_code == 201

        inv_json = json.dumps(
            [
                {
                    "invoice_number": "INV-TEST-100",
                    "direction": "payable",
                    "counterparty_name": "Acme Cloud Inc",
                    "po_number": "PO-TEST-01",
                    "issue_date": "2026-11-06",
                    "due_date": "2026-12-06",
                    "subtotal": 5000.00,
                    "tax_amount": 0.00,
                    "total_amount": 5000.00,
                    "line_items": [{"sku": "NODE", "qty": 10}],
                }
            ]
        ).encode("utf-8")
        inv_res = await client.post(
            "/api/v1/ingestion/upload",
            headers=CONTROLLER_HEADERS,
            data={"doc_type": "invoice", "auto_reconcile": "true"},
            files={"file": ("inv.json", inv_json, "application/json")},
        )
        assert inv_res.status_code == 201
        assert len(inv_res.json()["reconciled_match_ids"]) == 1

        matches = (
            await client.get("/api/v1/reconciliation/matches", headers=CONTROLLER_HEADERS)
        ).json()
        assert len(matches) == 1
        assert matches[0]["status"] == "matched"

        # Exact same bytes uploaded again -> blocked with 409
        dup_res = await client.post(
            "/api/v1/ingestion/upload",
            headers=CONTROLLER_HEADERS,
            data={"doc_type": "invoice", "auto_reconcile": "true"},
            files={"file": ("inv-copy.json", inv_json, "application/json")},
        )
        assert dup_res.status_code == 409
        assert "Duplicate document blocked" in dup_res.json()["detail"]["message"]

        docs = (await client.get("/api/v1/ingestion/documents", headers=CONTROLLER_HEADERS)).json()
        assert any(d["status"] == "duplicate_blocked" for d in docs)


@pytest.mark.asyncio
async def test_pdf_invoice_ingestion_and_three_way_match(tmp_path: Path) -> None:
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
                        "po_number": "PO-PDF-77",
                        "vendor_name": "NorthWind Systems",
                        "total_amount": 1200.00,
                        "qty": 4,
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
                        "receipt_number": "GR-PDF-77",
                        "po_number": "PO-PDF-77",
                        "total_amount": 1200.00,
                        "qty": 4,
                    }
                ],
            },
        )

        pdf_bytes = build_minimal_pdf(
            [
                "Invoice Number: INV-PDF-77",
                "PO Number: PO-PDF-77",
                "Vendor: NorthWind Systems",
                "Issue Date: 2026-11-10",
                "Due Date: 2026-12-10",
                "Quantity: 4",
                "Subtotal: $1200.00",
                "Tax: $0.00",
                "Total Due: $1200.00",
            ]
        )
        res = await client.post(
            "/api/v1/ingestion/upload",
            headers=CONTROLLER_HEADERS,
            data={"doc_type": "invoice", "auto_reconcile": "true"},
            files={"file": ("northwind.pdf", pdf_bytes, "application/pdf")},
        )
        assert res.status_code == 201
        matches = (
            await client.get("/api/v1/reconciliation/matches", headers=CONTROLLER_HEADERS)
        ).json()
        assert len(matches) == 1
        assert matches[0]["invoice_number"] == "INV-PDF-77"
        assert matches[0]["status"] == "matched"
