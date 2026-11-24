from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import create_approval_request, record_audit_event
from app.core.auth import Actor
from app.core.text import counterparty_similarity
from app.db.base import quantize_money
from app.db.models import BankTransaction, Invoice, PaymentAllocation
from app.llm.router import LLMRouter


def _score_candidate(tx: BankTransaction, inv: Invoice) -> tuple[float, list[str]]:
    expected_direction = "outflow" if inv.direction == "payable" else "inflow"
    if tx.direction != expected_direction:
        return 0.0, []

    remaining = quantize_money(inv.total_amount - inv.amount_paid)
    if remaining <= Decimal("0.00"):
        return 0.0, []

    score = 0.0
    reasons: list[str] = []

    inv_num_upper = inv.invoice_number.upper()
    if inv_num_upper and inv_num_upper in tx.description.upper():
        score += 0.45
        reasons.append(f"memo references {inv.invoice_number}")

    amount_diff = abs(tx.amount - remaining)
    if amount_diff <= Decimal("0.05"):
        score += 0.35
        reasons.append(f"exact balance match (${remaining:.2f})")
    elif remaining > Decimal("0.00") and tx.amount <= remaining:
        ratio = float(tx.amount / remaining)
        if ratio >= 0.40:
            score += 0.18
            reasons.append(f"partial settlement ({ratio * 100:.0f}% of open balance)")

    cp_sim = counterparty_similarity(
        tx.normalized_counterparty or tx.description,
        inv.counterparty_name,
    )
    if cp_sim >= 0.35:
        score += round(0.25 * cp_sim, 2)
        reasons.append(f"counterparty similarity {cp_sim:.0%}")

    days_delta = abs((tx.transaction_date - inv.due_date).days)
    if days_delta <= 14:
        score += 0.10
        reasons.append(f"within {days_delta}d of due date")

    return round(min(0.99, score), 2), reasons


async def propose_payment_allocations(
    db: AsyncSession,
    *,
    llm_router: LLMRouter,
    actor: Actor,
) -> list[PaymentAllocation]:
    """Match unallocated bank transactions to open AP/AR invoices behind controller approvals."""
    tx_stmt = (
        select(BankTransaction)
        .where(BankTransaction.status == "unallocated")
        .order_by(BankTransaction.transaction_date.asc())
    )
    unallocated = list((await db.execute(tx_stmt)).scalars().all())
    if not unallocated:
        return []

    inv_stmt = select(Invoice).where(
        Invoice.match_status != "rejected",
        Invoice.payment_status != "paid",
    )
    open_invoices = list((await db.execute(inv_stmt)).scalars().all())

    pending_allocs = list(
        (
            await db.execute(
                select(PaymentAllocation.invoice_id).where(
                    PaymentAllocation.status == "proposed"
                )
            )
        )
        .scalars()
        .all()
    )
    reserved_invoice_ids = set(pending_allocs)

    created: list[PaymentAllocation] = []
    for tx in unallocated:
        best_invoice: Invoice | None = None
        best_score = 0.0
        best_reasons: list[str] = []

        for inv in open_invoices:
            if inv.id in reserved_invoice_ids:
                continue
            score, reasons = _score_candidate(tx, inv)
            if score > best_score:
                best_score = score
                best_invoice = inv
                best_reasons = reasons

        if best_invoice is None or best_score < 0.45:
            continue

        remaining = quantize_money(best_invoice.total_amount - best_invoice.amount_paid)
        alloc_amount = quantize_money(min(tx.amount, remaining))
        reason_text = "; ".join(best_reasons)
        llm_res = await llm_router.generate(
            prompt=(
                f"Bank tx {tx.external_ref} (${tx.amount:.2f} {tx.direction}) matched to "
                f"{best_invoice.invoice_number} ({best_invoice.counterparty_name}, open "
                f"${remaining:.2f}) because: {reason_text}."
            ),
            system_prompt="Summarize payment allocation rationale for controller approval.",
            task_type="ap_ar_allocation",
        )

        allocation = PaymentAllocation(
            bank_transaction_id=tx.id,
            invoice_id=best_invoice.id,
            allocated_amount=alloc_amount,
            confidence_score=best_score,
            match_reason=f"{reason_text} — {llm_res.content}",
            status="proposed",
        )
        db.add(allocation)
        await db.flush()

        tx.status = "proposed"
        reserved_invoice_ids.add(best_invoice.id)

        risk_level = "low" if best_score >= 0.80 else "medium"
        approval = await create_approval_request(
            db,
            entity_type="payment_allocation",
            entity_id=allocation.id,
            action_requested="post_payment_allocation",
            summary=(
                f"Allocate {tx.external_ref} (${alloc_amount:.2f}) -> "
                f"{best_invoice.invoice_number} ({best_invoice.counterparty_name})"
            ),
            amount=alloc_amount,
            risk_level=risk_level,
            requested_by=actor.email,
        )
        allocation.approval_id = approval.id

        await record_audit_event(
            db,
            event_type="ap_ar.allocation_proposed",
            actor=actor,
            entity_type="payment_allocation",
            entity_id=allocation.id,
            action="proposed",
            details={
                "bank_ref": tx.external_ref,
                "invoice_number": best_invoice.invoice_number,
                "allocated_amount": float(alloc_amount),
                "confidence_score": best_score,
            },
        )
        created.append(allocation)

    return created
