from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.audit.service import create_approval_request, record_audit_event
from app.core.auth import Actor
from app.core.config import Settings
from app.db.base import quantize_money
from app.db.models import (
    ApprovalRequest,
    GoodsReceipt,
    Invoice,
    PurchaseOrder,
    ThreeWayMatch,
    Vendor,
)
from app.llm.embeddings import EmbeddingService, cosine_similarity, upsert_embedding
from app.llm.router import LLMRouter
from app.reconciliation.gl_coding import suggest_gl_account


def _sum_quantities(line_items: list[dict[str, Any]]) -> float:
    total = 0.0
    for item in line_items:
        qty_raw = item.get("qty", item.get("quantity", 0))
        try:
            total += float(qty_raw)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def _invoice_text(invoice: Invoice) -> str:
    items = " ".join(
        str(i.get("description") or i.get("sku") or "") for i in invoice.line_items_json
    )
    return f"{invoice.counterparty_name} {invoice.invoice_number} {items}".strip()


async def _find_purchase_order(
    db: AsyncSession,
    invoice: Invoice,
    embedding_service: EmbeddingService | None = None,
) -> tuple[PurchaseOrder | None, bool]:
    """Resolve PO by exact po_number or unambiguous semantic vendor+amount+embedding fallback."""
    if invoice.po_number:
        stmt = select(PurchaseOrder).where(PurchaseOrder.po_number == invoice.po_number)
        return (await db.execute(stmt)).scalar_one_or_none(), False

    if not invoice.vendor_id:
        return None, False

    candidates = list(
        (
            await db.execute(
                select(PurchaseOrder).where(PurchaseOrder.vendor_id == invoice.vendor_id)
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return None, False

    target = invoice.subtotal if invoice.subtotal > Decimal("0.00") else invoice.total_amount
    if target <= Decimal("0.00"):
        return None, False

    inv_vec: list[float] = []
    if embedding_service is not None:
        inv_vec, _ = await embedding_service.embed(_invoice_text(invoice))

    best: PurchaseOrder | None = None
    best_score = -1.0
    for po in candidates:
        if po.total_amount <= Decimal("0.00"):
            continue
        diff = abs(po.total_amount - target)
        ratio = float(diff / po.total_amount)
        days_apart = abs((invoice.issue_date - po.issue_date).days)
        if ratio <= 0.15 and days_apart <= 45:
            sem_score = 0.0
            if embedding_service is not None and inv_vec:
                po_items = " ".join(
                    str(i.get("description") or i.get("sku") or "") for i in po.line_items_json
                )
                po_vec, _ = await embedding_service.embed(
                    f"{invoice.counterparty_name} {po.po_number} {po_items}"
                )
                sem_score = max(0.0, cosine_similarity(inv_vec, po_vec))
            combined = (1.0 - ratio) + 0.25 * sem_score
            if combined > best_score:
                best = po
                best_score = combined
    return (best, True) if best is not None else (None, False)


async def run_three_way_match(
    db: AsyncSession,
    *,
    invoice: Invoice,
    llm_router: LLMRouter,
    settings: Settings,
    actor: Actor,
    embedding_service: EmbeddingService | None = None,
) -> ThreeWayMatch:
    """Execute deterministic + semantic 3-way match across PO, Goods Receipt, and Invoice."""
    anomalies: list[dict[str, Any]] = []
    emb_svc = embedding_service or EmbeddingService(settings)

    # Auto-assign GL account via semantic Chart of Accounts coding if blank
    if not invoice.gl_account:
        vendor_default_gl: str | None = None
        if invoice.vendor_id:
            vendor_row = await db.get(Vendor, invoice.vendor_id)
            if vendor_row is not None:
                vendor_default_gl = vendor_row.default_gl_account
        gl_suggestion = await suggest_gl_account(
            description=_invoice_text(invoice),
            vendor_name=invoice.counterparty_name,
            default_gl=vendor_default_gl,
            embedding_service=emb_svc,
        )
        invoice.gl_account = gl_suggestion.gl_account

    await upsert_embedding(
        db,
        entity_type="invoice",
        entity_id=invoice.id,
        source_text=_invoice_text(invoice),
        embedding_service=emb_svc,
    )

    # 1. Exact duplicate invoice check (number+vendor or exact file/payload SHA-256)
    dup_conditions: list[ColumnElement[bool]] = [
        (Invoice.invoice_number == invoice.invoice_number)
        & (Invoice.counterparty_name == invoice.counterparty_name)
    ]
    if invoice.content_sha256:
        dup_conditions.append(Invoice.content_sha256 == invoice.content_sha256)

    dup_stmt = (
        select(Invoice)
        .where(
            Invoice.id != invoice.id,
            Invoice.created_at < invoice.created_at,
            or_(*dup_conditions),
        )
        .order_by(Invoice.created_at.asc())
        .limit(1)
    )
    duplicate_inv = (await db.execute(dup_stmt)).scalar_one_or_none()
    if duplicate_inv is not None:
        anomalies.append(
            {
                "code": "DUPLICATE_INVOICE",
                "severity": "high",
                "message": (
                    f"Matches earlier invoice '{duplicate_inv.invoice_number}' "
                    f"({duplicate_inv.id[:8]}...) from {duplicate_inv.counterparty_name}."
                ),
            }
        )
    else:
        # Semantic near-duplicate check across recent vendor invoices with nearly identical amounts
        window_start = invoice.issue_date - timedelta(days=14)
        window_end = invoice.issue_date + timedelta(days=14)
        peer_stmt = select(Invoice).where(
            Invoice.id != invoice.id,
            Invoice.created_at < invoice.created_at,
            Invoice.counterparty_name == invoice.counterparty_name,
            Invoice.issue_date >= window_start,
            Invoice.issue_date <= window_end,
        )
        peers = list((await db.execute(peer_stmt)).scalars().all())
        inv_vec, _ = await emb_svc.embed(_invoice_text(invoice))
        for peer in peers:
            if peer.total_amount <= Decimal("0.00"):
                continue
            amt_delta_pct = float(abs(peer.total_amount - invoice.total_amount) / peer.total_amount)
            if amt_delta_pct <= 0.01:
                peer_vec, _ = await emb_svc.embed(_invoice_text(peer))
                sim = cosine_similarity(inv_vec, peer_vec)
                if sim >= 0.88:
                    anomalies.append(
                        {
                            "code": "NEAR_DUPLICATE_INVOICE",
                            "severity": "medium",
                            "message": (
                                f"Near-duplicate of '{peer.invoice_number}' "
                                f"(${peer.total_amount:.2f}, semantic similarity {sim:.0%})."
                            ),
                        }
                    )
                    break

    # 2. Purchase Order lookup
    po, used_semantic_po = await _find_purchase_order(db, invoice, emb_svc)
    if po is None:
        po_label = invoice.po_number or "none provided"
        anomalies.append(
            {
                "code": "MISSING_PO",
                "severity": "high",
                "message": f"No matching Purchase Order found (PO ref: {po_label}).",
            }
        )
    elif used_semantic_po:
        anomalies.append(
            {
                "code": "SEMANTIC_PO_INFERRED",
                "severity": "low",
                "message": (
                    f"Invoice lacked PO number; semantically matched to {po.po_number} "
                    f"(${po.total_amount:.2f}) by vendor, date, and amount."
                ),
            }
        )

    if po is not None and invoice.vendor_id and po.vendor_id != invoice.vendor_id:
        anomalies.append(
            {
                "code": "VENDOR_MISMATCH",
                "severity": "high",
                "message": "Invoice vendor does not match Purchase Order vendor.",
            }
        )

    # 3. Goods Receipt lookup
    receipt: GoodsReceipt | None = None
    if po is not None:
        receipt_stmt = (
            select(GoodsReceipt)
            .where(GoodsReceipt.po_id == po.id)
            .order_by(GoodsReceipt.received_date.desc())
            .limit(1)
        )
        receipt = (await db.execute(receipt_stmt)).scalar_one_or_none()
        if receipt is None:
            anomalies.append(
                {
                    "code": "MISSING_RECEIPT",
                    "severity": "high",
                    "message": f"PO {po.po_number} has no recorded Goods Receipt.",
                }
            )

    # 4. Arithmetic validation on invoice totals
    if (
        invoice.subtotal > Decimal("0.00")
        and abs((invoice.subtotal + invoice.tax_amount) - invoice.total_amount) > Decimal("0.01")
    ):
        anomalies.append(
            {
                "code": "MATH_MISMATCH",
                "severity": "medium",
                "message": (
                    f"Subtotal (${invoice.subtotal:.2f}) + Tax (${invoice.tax_amount:.2f}) "
                    f"does not equal Total (${invoice.total_amount:.2f})."
                ),
            }
        )

    # 5. Price variance (Invoice subtotal vs PO total)
    price_variance = Decimal("0.00")
    price_variance_pct = 0.0
    if po is not None and po.total_amount > Decimal("0.00"):
        inv_base = invoice.subtotal if invoice.subtotal > Decimal("0.00") else invoice.total_amount
        price_variance = quantize_money(inv_base - po.total_amount)
        price_variance_pct = round(float(price_variance / po.total_amount * Decimal("100")), 2)
        if abs(price_variance_pct) > settings.price_variance_tolerance_pct:
            sev = "high" if abs(price_variance_pct) > 10.0 else "medium"
            anomalies.append(
                {
                    "code": "PRICE_VARIANCE",
                    "severity": sev,
                    "message": (
                        f"Invoiced ${inv_base:.2f} vs PO ${po.total_amount:.2f} "
                        f"({price_variance_pct:+.2f}%)."
                    ),
                }
            )

    # 6. Quantity variance (Invoice lines vs Goods Receipt lines)
    qty_variance = 0.0
    if receipt is not None:
        inv_qty = _sum_quantities(invoice.line_items_json)
        rec_qty = _sum_quantities(receipt.line_items_json)
        if inv_qty > 0 or rec_qty > 0:
            qty_variance = round(inv_qty - rec_qty, 2)
            qty_pct = abs(qty_variance) / max(rec_qty, 1.0) * 100.0
            if abs(qty_variance) > 0.001 and qty_pct > settings.qty_variance_tolerance_pct:
                anomalies.append(
                    {
                        "code": "QUANTITY_VARIANCE",
                        "severity": "high",
                        "message": (
                            f"Billed qty {inv_qty:g} vs received qty {rec_qty:g} "
                            f"(delta {qty_variance:+g})."
                        ),
                    }
                )

    codes = {a["code"] for a in anomalies}
    if "DUPLICATE_INVOICE" in codes:
        match_status = "duplicate_flagged"
    elif "MISSING_PO" in codes:
        match_status = "missing_po"
    elif "MISSING_RECEIPT" in codes:
        match_status = "missing_receipt"
    elif codes - {"SEMANTIC_PO_INFERRED"}:
        match_status = "variance_flagged"
    else:
        match_status = "matched"

    confidence = 0.98 if not used_semantic_po else 0.91
    for anomaly in anomalies:
        code = anomaly["code"]
        if code in {"DUPLICATE_INVOICE", "MISSING_PO"}:
            confidence -= 0.40
        elif code in {"MISSING_RECEIPT", "VENDOR_MISMATCH"}:
            confidence -= 0.28
        elif code == "QUANTITY_VARIANCE":
            confidence -= 0.25
        elif code == "PRICE_VARIANCE":
            confidence -= min(0.30, 0.12 + abs(price_variance_pct) / 100.0)
        elif code in {"MATH_MISMATCH", "NEAR_DUPLICATE_INVOICE"}:
            confidence -= 0.15
    confidence = round(max(0.05, min(0.99, confidence)), 2)

    anomaly_summary = "; ".join(f"{a['code']}: {a['message']}" for a in anomalies) or "Clean 3-way"
    llm_res = await llm_router.generate(
        prompt=(
            f"Invoice {invoice.invoice_number} ({invoice.counterparty_name}, "
            f"${invoice.total_amount:.2f}, GL={invoice.gl_account}) -> status={match_status}, "
            f"confidence={confidence:.2f}, findings=[{anomaly_summary}]."
        ),
        system_prompt="Explain this 3-way PO/Receipt/Invoice match concisely for a controller.",
        task_type="three_way_match",
    )

    existing = (
        await db.execute(select(ThreeWayMatch).where(ThreeWayMatch.invoice_id == invoice.id))
    ).scalar_one_or_none()

    if existing is None:
        match = ThreeWayMatch(
            invoice_id=invoice.id,
            po_id=po.id if po else None,
            receipt_id=receipt.id if receipt else None,
            status=match_status,
            confidence_score=confidence,
            price_variance=price_variance,
            price_variance_pct=price_variance_pct,
            qty_variance=qty_variance,
            anomalies_json=anomalies,
            ai_explanation=llm_res.content,
            llm_provider_used=llm_res.provider,
        )
        db.add(match)
        await db.flush()
    else:
        match = existing
        match.po_id = po.id if po else None
        match.receipt_id = receipt.id if receipt else None
        match.status = match_status
        match.confidence_score = confidence
        match.price_variance = price_variance
        match.price_variance_pct = price_variance_pct
        match.qty_variance = qty_variance
        match.anomalies_json = anomalies
        match.ai_explanation = llm_res.content
        match.llm_provider_used = llm_res.provider

    invoice.match_status = match_status

    severities = {a["severity"] for a in anomalies}
    risk_level = "high" if "high" in severities else ("medium" if "medium" in severities else "low")

    existing_approval = (
        await db.get(ApprovalRequest, match.approval_id) if match.approval_id else None
    )
    if existing_approval is None or existing_approval.status != "pending":
        approval = await create_approval_request(
            db,
            entity_type="invoice_match",
            entity_id=match.id,
            action_requested="approve_invoice_posting",
            summary=(
                f"Invoice {invoice.invoice_number} ({invoice.counterparty_name}) — "
                f"{match_status.replace('_', ' ')}"
            ),
            amount=quantize_money(invoice.total_amount),
            risk_level=risk_level,
            requested_by=actor.email,
        )
        match.approval_id = approval.id

    await record_audit_event(
        db,
        event_type="reconciliation.three_way_matched",
        actor=actor,
        entity_type="invoice",
        entity_id=invoice.id,
        action=match_status,
        details={
            "invoice_number": invoice.invoice_number,
            "po_number": po.po_number if po else None,
            "receipt_number": receipt.receipt_number if receipt else None,
            "gl_account": invoice.gl_account,
            "confidence_score": confidence,
            "anomalies": [a["code"] for a in anomalies],
        },
    )
    return match
