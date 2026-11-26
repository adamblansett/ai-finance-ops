import json
import re
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.policy import audit_and_persist_expense
from app.audit.schemas import ExpenseCreate
from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.core.config import Settings
from app.core.text import normalize_counterparty
from app.db.base import parse_iso_date, quantize_money, utcnow
from app.db.models import (
    BankTransaction,
    GoodsReceipt,
    IngestedDocument,
    Invoice,
    PurchaseOrder,
    Vendor,
)
from app.ingestion.extractors import (
    extract_records,
    parse_line_items,
    parse_money,
    sha256_bytes,
)
from app.ingestion.schemas import DocType, IngestedDocumentOut, IngestionResultOut
from app.llm.embeddings import EmbeddingService, upsert_embedding
from app.llm.router import LLMRouter
from app.reconciliation.three_way import run_three_way_match


async def _get_or_create_vendor(
    db: AsyncSession,
    *,
    name: str,
    code: str | None = None,
    tax_id: str | None = None,
) -> Vendor:
    clean_name = name.strip() or "Unnamed Vendor"
    if code:
        existing = (
            await db.execute(select(Vendor).where(Vendor.code == code.strip()))
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    existing_by_name = (
        await db.execute(select(Vendor).where(func.lower(Vendor.name) == clean_name.lower()))
    ).scalar_one_or_none()
    if existing_by_name is not None:
        return existing_by_name

    slug = re.sub(r"[^A-Z0-9]+", "-", clean_name.upper()).strip("-")[:24] or "VENDOR"
    generated_code = (code or f"V-{slug}").strip()[:64]
    code_taken = (
        await db.execute(select(Vendor).where(Vendor.code == generated_code))
    ).scalar_one_or_none()
    if code_taken is not None:
        generated_code = f"{generated_code[:55]}-{sha256_bytes(clean_name.encode())[:6]}"

    vendor = Vendor(code=generated_code, name=clean_name, tax_id=tax_id)
    db.add(vendor)
    await db.flush()
    return vendor


def to_document_out(doc: IngestedDocument) -> IngestedDocumentOut:
    return IngestedDocumentOut(
        id=doc.id,
        filename=doc.filename,
        doc_type=doc.doc_type,
        content_type=doc.content_type,
        content_sha256=doc.content_sha256,
        raw_size_bytes=doc.raw_size_bytes,
        parsed_records_count=doc.parsed_records_count,
        duplicate_of_id=doc.duplicate_of_id,
        status=doc.status,
        summary=doc.summary_json,
        uploaded_by=doc.uploaded_by,
        created_at=doc.created_at,
    )


async def ingest_bytes(
    db: AsyncSession,
    *,
    filename: str,
    doc_type: DocType,
    content: bytes,
    content_type: str,
    llm_router: LLMRouter,
    settings: Settings,
    actor: Actor,
    auto_reconcile: bool = True,
    embedding_service: EmbeddingService | None = None,
) -> IngestionResultOut:
    """Parse, duplicate-check via SHA-256, persist, and optionally reconcile uploaded data."""
    if not content.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded document is empty.",
        )

    digest = sha256_bytes(content)
    dup_doc = (
        await db.execute(
            select(IngestedDocument)
            .where(
                IngestedDocument.content_sha256 == digest,
                IngestedDocument.status == "parsed",
            )
            .order_by(IngestedDocument.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if dup_doc is not None:
        blocked = IngestedDocument(
            filename=filename,
            doc_type=doc_type,
            content_type=content_type,
            content_sha256=digest,
            raw_size_bytes=len(content),
            parsed_records_count=0,
            duplicate_of_id=dup_doc.id,
            status="duplicate_blocked",
            summary_json={"duplicate_of_filename": dup_doc.filename},
            uploaded_by=actor.email,
        )
        db.add(blocked)
        await db.flush()
        await record_audit_event(
            db,
            event_type="document.duplicate_blocked",
            actor=actor,
            entity_type="ingested_document",
            entity_id=blocked.id,
            action="blocked",
            details={
                "filename": filename,
                "duplicate_of_id": dup_doc.id,
                "content_sha256": digest,
            },
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    f"Duplicate document blocked: SHA-256 matches '{dup_doc.filename}' "
                    f"(id={dup_doc.id})."
                ),
                "duplicate_of_id": dup_doc.id,
                "content_sha256": digest,
                "document_id": blocked.id,
            },
        )

    records = extract_records(filename, content, content_type, doc_type)
    if not records:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No valid records found in '{filename}'.",
        )

    doc = IngestedDocument(
        filename=filename,
        doc_type=doc_type,
        content_type=content_type,
        content_sha256=digest,
        raw_size_bytes=len(content),
        parsed_records_count=len(records),
        status="parsed",
        summary_json={"record_count": len(records)},
        uploaded_by=actor.email,
    )
    db.add(doc)
    await db.flush()

    emb_svc = embedding_service or EmbeddingService(settings)
    created_ids: list[str] = []
    reconciled_match_ids: list[str] = []
    today = utcnow().date()

    if doc_type == "purchase_order":
        for rec in records:
            po_num = str(rec.get("po_number") or "").strip()
            if not po_num:
                continue
            existing_po = (
                await db.execute(select(PurchaseOrder).where(PurchaseOrder.po_number == po_num))
            ).scalar_one_or_none()
            if existing_po is not None:
                created_ids.append(existing_po.id)
                continue
            vendor = await _get_or_create_vendor(
                db,
                name=str(rec.get("vendor_name") or rec.get("counterparty_name") or "Vendor"),
                code=rec.get("vendor_code"),
            )
            issue_dt = parse_iso_date(rec.get("issue_date"), today)
            exp_dt = (
                parse_iso_date(rec.get("expected_delivery_date"), issue_dt + timedelta(days=7))
                if rec.get("expected_delivery_date")
                else issue_dt + timedelta(days=7)
            )
            items = parse_line_items(rec.get("line_items"), rec.get("qty"))
            po = PurchaseOrder(
                po_number=po_num,
                vendor_id=vendor.id,
                issue_date=issue_dt,
                expected_delivery_date=exp_dt,
                currency=str(rec.get("currency") or "USD").upper(),
                total_amount=parse_money(rec.get("total_amount"), "0.00"),
                status=str(rec.get("status") or "open"),
                line_items_json=items,
            )
            db.add(po)
            await db.flush()
            await upsert_embedding(
                db,
                entity_type="purchase_order",
                entity_id=po.id,
                source_text=f"{vendor.name} {po.po_number} {items}",
                embedding_service=emb_svc,
            )
            created_ids.append(po.id)

    elif doc_type == "goods_receipt":
        for rec in records:
            rec_num = str(rec.get("receipt_number") or "").strip()
            po_num = str(rec.get("po_number") or "").strip()
            if not rec_num or not po_num:
                continue
            matched_po = (
                await db.execute(select(PurchaseOrder).where(PurchaseOrder.po_number == po_num))
            ).scalar_one_or_none()
            if matched_po is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Goods receipt '{rec_num}' references unknown PO '{po_num}'.",
                )
            existing_gr = (
                await db.execute(
                    select(GoodsReceipt).where(GoodsReceipt.receipt_number == rec_num)
                )
            ).scalar_one_or_none()
            if existing_gr is not None:
                created_ids.append(existing_gr.id)
                continue
            gr = GoodsReceipt(
                receipt_number=rec_num,
                po_id=matched_po.id,
                vendor_id=matched_po.vendor_id,
                received_date=parse_iso_date(rec.get("received_date"), today),
                total_amount=parse_money(rec.get("total_amount"), str(matched_po.total_amount)),
                line_items_json=parse_line_items(rec.get("line_items"), rec.get("qty")),
                notes=rec.get("notes"),
            )
            db.add(gr)
            await db.flush()
            created_ids.append(gr.id)

    elif doc_type == "invoice":
        for rec in records:
            direction = str(rec.get("direction") or "payable").strip().lower()
            counterparty = str(
                rec.get("counterparty_name") or rec.get("vendor_name") or "Unknown Counterparty"
            ).strip()
            vendor_id: str | None = None
            if direction == "payable":
                vendor = await _get_or_create_vendor(
                    db, name=counterparty, code=rec.get("vendor_code")
                )
                vendor_id = vendor.id

            issue_dt = parse_iso_date(rec.get("issue_date"), today)
            due_dt = (
                parse_iso_date(rec.get("due_date"), issue_dt + timedelta(days=30))
                if rec.get("due_date")
                else issue_dt + timedelta(days=30)
            )
            total = parse_money(rec.get("total_amount"), "0.00")
            tax = parse_money(rec.get("tax_amount"), "0.00")
            subtotal = parse_money(rec.get("subtotal"), str(max(Decimal("0.00"), total - tax)))
            if total == Decimal("0.00") and subtotal > Decimal("0.00"):
                total = quantize_money(subtotal + tax)

            inv_num = str(rec.get("invoice_number") or f"INV-{doc.id[:8].upper()}").strip()
            inv_po_num = str(rec.get("po_number")).strip() if rec.get("po_number") else None
            rec_hash = sha256_bytes(json.dumps(rec, sort_keys=True, default=str).encode("utf-8"))

            invoice = Invoice(
                invoice_number=inv_num,
                direction=direction,
                vendor_id=vendor_id,
                counterparty_name=counterparty,
                po_number=inv_po_num,
                issue_date=issue_dt,
                due_date=due_dt,
                currency=str(rec.get("currency") or "USD").upper(),
                subtotal=subtotal,
                tax_amount=tax,
                total_amount=total,
                amount_paid=Decimal("0.00"),
                content_sha256=rec_hash,
                source_document_id=doc.id,
                gl_account=str(rec.get("gl_account")).strip() if rec.get("gl_account") else None,
                line_items_json=parse_line_items(rec.get("line_items"), rec.get("qty")),
                match_status="unmatched" if direction == "payable" else "approved",
                payment_status="unpaid",
            )
            db.add(invoice)
            await db.flush()
            created_ids.append(invoice.id)

            if auto_reconcile and direction == "payable":
                match = await run_three_way_match(
                    db,
                    invoice=invoice,
                    llm_router=llm_router,
                    settings=settings,
                    actor=actor,
                    embedding_service=emb_svc,
                )
                reconciled_match_ids.append(match.id)

    elif doc_type == "bank_statement":
        for idx, rec in enumerate(records, start=1):
            desc = str(rec.get("description") or "").strip()
            tx_date = parse_iso_date(rec.get("transaction_date"), today)
            amount = abs(parse_money(rec.get("amount"), "0.00"))
            raw_ref = str(rec.get("external_ref") or "").strip() or f"TX-{digest[:8].upper()}-{idx}"
            existing_tx = (
                await db.execute(
                    select(BankTransaction).where(BankTransaction.external_ref == raw_ref)
                )
            ).scalar_one_or_none()
            if existing_tx is not None:
                created_ids.append(existing_tx.id)
                continue

            cp_raw = str(rec.get("counterparty") or desc)
            tx = BankTransaction(
                external_ref=raw_ref,
                transaction_date=tx_date,
                description=desc or cp_raw,
                normalized_counterparty=normalize_counterparty(cp_raw),
                direction=str(rec.get("direction") or "outflow").strip().lower(),
                amount=amount,
                currency=str(rec.get("currency") or "USD").upper(),
                account_name=str(rec.get("account_name") or "Operating Checking"),
                content_sha256=digest,
                status="unallocated",
            )
            db.add(tx)
            await db.flush()
            created_ids.append(tx.id)

    elif doc_type == "expense":
        for rec in records:
            exp_payload = ExpenseCreate(
                employee_name=str(rec.get("employee_name") or actor.email.split("@")[0]),
                employee_email=str(rec.get("employee_email") or actor.email),
                department=str(rec.get("department") or "Operations"),
                merchant=str(rec.get("merchant") or "Merchant"),
                expense_date=parse_iso_date(rec.get("expense_date"), today),
                category=str(rec.get("category") or "other"),
                tax_category=str(rec.get("tax_category") or "deductible_100"),
                amount=float(parse_money(rec.get("amount"), "1.00")),
                currency=str(rec.get("currency") or "USD"),
                receipt_hash=rec.get("receipt_hash") or None,
                description=str(rec.get("description") or ""),
            )
            exp = await audit_and_persist_expense(
                db, payload=exp_payload, llm_router=llm_router, settings=settings, actor=actor
            )
            created_ids.append(exp.id)

    doc.summary_json = {
        "record_count": len(records),
        "created_count": len(created_ids),
        "reconciled_count": len(reconciled_match_ids),
    }

    await record_audit_event(
        db,
        event_type="document.ingested",
        actor=actor,
        entity_type="ingested_document",
        entity_id=doc.id,
        action=doc_type,
        details={
            "filename": filename,
            "content_sha256": digest,
            "parsed_records_count": len(records),
            "created_count": len(created_ids),
        },
    )
    await db.commit()
    await db.refresh(doc)

    return IngestionResultOut(
        document=to_document_out(doc),
        created_ids=created_ids,
        reconciled_match_ids=reconciled_match_ids,
        message=(
            f"Ingested {len(records)} {doc_type} record(s) from '{filename}' "
            f"(SHA-256 {digest[:12]}...)."
        ),
    )
