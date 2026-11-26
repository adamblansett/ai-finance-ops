from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import CONTROLLER_HEADERS, make_test_app


@pytest.mark.asyncio
async def test_ofx_and_qbo_csv_ingestion_plus_gl_coding(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. QBO/Xero-aliased CSV invoice ingestion
        qbo_csv = (
            b"Bill No,Supplier,PO #,Bill Date,DueDate,Balance Due,qty\n"
            b"QBO-5501,CloudCore Infrastructure LLC,PO-QBO-1,2026-11-10,2026-12-10,1250.00,2\n"
        )
        inv_res = await client.post(
            "/api/v1/ingestion/upload",
            headers=CONTROLLER_HEADERS,
            data={"doc_type": "invoice", "auto_reconcile": "true"},
            files={"file": ("qbo_bills.csv", qbo_csv, "text/csv")},
        )
        assert inv_res.status_code == 201

        invoices = (
            await client.get("/api/v1/reconciliation/invoices", headers=CONTROLLER_HEADERS)
        ).json()
        assert len(invoices) == 1
        assert invoices[0]["invoice_number"] == "QBO-5501"
        assert invoices[0]["gl_account"] == "6100-CLOUD"

        # 2. OFX bank statement ingestion
        ofx_payload = (
            b"<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>"
            b"<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261112<TRNAMT>-1250.00"
            b"<FITID>OFX-9001<NAME>CLOUDCORE INFRASTRUCTURE<MEMO>QBO-5501</STMTTRN>"
            b"</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
        )
        ofx_res = await client.post(
            "/api/v1/ingestion/upload",
            headers=CONTROLLER_HEADERS,
            data={"doc_type": "bank_statement"},
            files={"file": ("bank.ofx", ofx_payload, "application/x-ofx")},
        )
        assert ofx_res.status_code == 201

        txs = (
            await client.get(
                "/api/v1/reconciliation/bank-transactions", headers=CONTROLLER_HEADERS
            )
        ).json()
        assert len(txs) == 1
        assert txs[0]["external_ref"] == "OFX-9001"
        assert txs[0]["direction"] == "outflow"
        assert txs[0]["amount"] == 1250.0


@pytest.mark.asyncio
async def test_semantic_gl_search_jobs_exports_and_pagination(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/v1/seed/demo", headers=CONTROLLER_HEADERS)

        # GL code suggestion endpoint
        gl_res = await client.post(
            "/api/v1/reconciliation/gl-suggest",
            headers=CONTROLLER_HEADERS,
            json={
                "vendor_name": "Apex Freight Carriers",
                "description": "Pallet warehouse freight shipping delivery",
            },
        )
        assert gl_res.status_code == 200
        assert gl_res.json()["gl_account"] == "5200-FREIGHT"

        # Semantic search across indexed invoices
        search_res = await client.post(
            "/api/v1/reconciliation/semantic-search",
            headers=CONTROLLER_HEADERS,
            json={"query": "GPU-NODE-X CloudCore", "entity_type": "invoice", "top_k": 3},
        )
        assert search_res.status_code == 200
        hits = search_res.json()
        assert len(hits) >= 1
        assert "CloudCore" in hits[0]["source_text"]

        # Pagination & X-Total-Count + search filtering
        paged = await client.get(
            "/api/v1/reconciliation/matches?limit=2&offset=0",
            headers=CONTROLLER_HEADERS,
        )
        assert paged.status_code == 200
        assert int(paged.headers["x-total-count"]) >= 6
        assert len(paged.json()) == 2

        filtered = await client.get(
            "/api/v1/reconciliation/matches?search=Apex",
            headers=CONTROLLER_HEADERS,
        )
        assert filtered.status_code == 200
        assert len(filtered.json()) == 1
        assert filtered.json()[0]["invoice_number"] == "INV-APX-882"

        # Background jobs enqueue & status polling
        job_res = await client.post(
            "/api/v1/jobs/forecast-snapshot",
            headers=CONTROLLER_HEADERS,
            json={"ar_collection_rate_pct": 90.0},
        )
        assert job_res.status_code == 201
        job = job_res.json()
        assert job["status"] == "completed"
        assert job["progress_pct"] == 100
        assert "ending_cash_week_13" in job["result"]

        job_get = await client.get(f"/api/v1/jobs/{job['id']}", headers=CONTROLLER_HEADERS)
        assert job_get.status_code == 200

        # Controller exports (CSV & JSON)
        for path in (
            "/api/v1/exports/audit-log.csv",
            "/api/v1/exports/reconciliation-packet.csv",
            "/api/v1/exports/cashflow-13w.csv",
        ):
            csv_res = await client.get(path, headers=CONTROLLER_HEADERS)
            assert csv_res.status_code == 200
            assert "text/csv" in csv_res.headers["content-type"]
            assert len(csv_res.text.splitlines()) >= 2

        pack_res = await client.get(
            "/api/v1/exports/controller-pack.json", headers=CONTROLLER_HEADERS
        )
        assert pack_res.status_code == 200
        pack = pack_res.json()
        assert pack["audit_chain"]["valid"] is True
        assert pack["matches_summary"]["total"] >= 6
