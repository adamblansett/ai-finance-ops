import hashlib
import json
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.schemas import AuditChainVerifyOut
from app.core.auth import Actor
from app.db.base import quantize_money, utcnow
from app.db.models import (
    ApprovalRequest,
    AuditEvent,
    BankTransaction,
    Expense,
    Invoice,
    PaymentAllocation,
    ThreeWayMatch,
)


def compute_event_hash(
    *,
    sequence_no: int,
    event_type: str,
    actor_email: str,
    actor_role: str,
    entity_type: str,
    entity_id: str,
    action: str,
    details: dict[str, Any],
    prev_hash: str,
) -> str:
    """Compute a deterministic SHA-256 hash chaining an audit event to prev_hash."""
    canonical = json.dumps(
        {
            "sequence_no": sequence_no,
            "event_type": event_type,
            "actor_email": actor_email,
            "actor_role": actor_role,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "details": details,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def record_audit_event(
    db: AsyncSession,
    *,
    event_type: str,
    actor: Actor,
    entity_type: str,
    entity_id: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append an immutable hash-chained event to the SOX audit log."""
    stmt = select(AuditEvent).order_by(AuditEvent.sequence_no.desc()).limit(1)
    latest = (await db.execute(stmt)).scalar_one_or_none()

    next_seq = (latest.sequence_no + 1) if latest is not None else 1
    prev_hash = latest.event_hash if latest is not None else "GENESIS"
    clean_details = details or {}

    event_hash = compute_event_hash(
        sequence_no=next_seq,
        event_type=event_type,
        actor_email=actor.email,
        actor_role=actor.role,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        details=clean_details,
        prev_hash=prev_hash,
    )
    event = AuditEvent(
        sequence_no=next_seq,
        event_type=event_type,
        actor_email=actor.email,
        actor_role=actor.role,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        details_json=clean_details,
        prev_hash=prev_hash,
        event_hash=event_hash,
    )
    db.add(event)
    await db.flush()
    return event


async def verify_audit_chain(db: AsyncSession) -> AuditChainVerifyOut:
    """Recompute every SHA-256 link in audit_events and report integrity status."""
    stmt = select(AuditEvent).order_by(AuditEvent.sequence_no.asc())
    events = list((await db.execute(stmt)).scalars().all())
    if not events:
        return AuditChainVerifyOut(
            valid=True,
            total_events=0,
            head_hash="GENESIS",
            broken_sequence_no=None,
            message="Audit trail is empty (GENESIS state verified).",
        )

    expected_prev = "GENESIS"
    expected_seq = 1
    for ev in events:
        if ev.sequence_no != expected_seq or ev.prev_hash != expected_prev:
            return AuditChainVerifyOut(
                valid=False,
                total_events=len(events),
                head_hash=events[-1].event_hash,
                broken_sequence_no=ev.sequence_no,
                message=(
                    f"Chain linkage mismatch at sequence #{ev.sequence_no}: "
                    f"expected prev_hash={expected_prev[:12]}..."
                ),
            )
        recomputed = compute_event_hash(
            sequence_no=ev.sequence_no,
            event_type=ev.event_type,
            actor_email=ev.actor_email,
            actor_role=ev.actor_role,
            entity_type=ev.entity_type,
            entity_id=ev.entity_id,
            action=ev.action,
            details=ev.details_json,
            prev_hash=ev.prev_hash,
        )
        if ev.event_hash != recomputed:
            return AuditChainVerifyOut(
                valid=False,
                total_events=len(events),
                head_hash=events[-1].event_hash,
                broken_sequence_no=ev.sequence_no,
                message=f"Hash tamper detected at sequence #{ev.sequence_no}.",
            )
        expected_prev = ev.event_hash
        expected_seq += 1

    return AuditChainVerifyOut(
        valid=True,
        total_events=len(events),
        head_hash=events[-1].event_hash,
        broken_sequence_no=None,
        message=f"All {len(events)} audit events verified intact.",
    )


async def create_approval_request(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    action_requested: str,
    summary: str,
    amount: Decimal,
    risk_level: str,
    requested_by: str,
) -> ApprovalRequest:
    """Create a pending human-in-the-loop approval request."""
    approval = ApprovalRequest(
        entity_type=entity_type,
        entity_id=entity_id,
        action_requested=action_requested,
        summary=summary,
        amount=quantize_money(amount),
        risk_level=risk_level,
        status="pending",
        requested_by=requested_by,
    )
    db.add(approval)
    await db.flush()
    return approval


async def decide_approval(
    db: AsyncSession,
    *,
    approval_id: str,
    decision: Literal["approved", "rejected"],
    notes: str,
    actor: Actor,
) -> ApprovalRequest:
    """Approve or reject a pending HITL gate and apply domain side effects atomically."""
    approval = await db.get(ApprovalRequest, approval_id)
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{approval_id}' not found.",
        )
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval request '{approval_id}' is already '{approval.status}'.",
        )

    approval.status = decision
    approval.decided_by = actor.email
    approval.decision_notes = notes.strip() or f"{decision} by {actor.email}"
    approval.decided_at = utcnow()

    if approval.entity_type == "invoice_match":
        match = await db.get(ThreeWayMatch, approval.entity_id)
        if match is None:
            match = (
                await db.execute(
                    select(ThreeWayMatch).where(ThreeWayMatch.approval_id == approval.id)
                )
            ).scalar_one_or_none()
        if match is not None:
            match.status = decision
            invoice = await db.get(Invoice, match.invoice_id)
            if invoice is not None:
                invoice.match_status = decision

    elif approval.entity_type == "payment_allocation":
        alloc = await db.get(PaymentAllocation, approval.entity_id)
        if alloc is None:
            alloc = (
                await db.execute(
                    select(PaymentAllocation).where(PaymentAllocation.approval_id == approval.id)
                )
            ).scalar_one_or_none()
        if alloc is not None:
            alloc.status = decision
            bank_tx = await db.get(BankTransaction, alloc.bank_transaction_id)
            invoice = await db.get(Invoice, alloc.invoice_id)
            if decision == "approved":
                if bank_tx is not None:
                    bank_tx.status = "allocated"
                if invoice is not None:
                    new_paid = quantize_money(invoice.amount_paid + alloc.allocated_amount)
                    if new_paid > invoice.total_amount:
                        new_paid = invoice.total_amount
                    invoice.amount_paid = new_paid
                    invoice.payment_status = (
                        "paid" if new_paid >= invoice.total_amount else "partially_paid"
                    )
            else:
                if bank_tx is not None:
                    bank_tx.status = "unallocated"

    elif approval.entity_type == "expense":
        expense = await db.get(Expense, approval.entity_id)
        if expense is None:
            expense = (
                await db.execute(select(Expense).where(Expense.approval_id == approval.id))
            ).scalar_one_or_none()
        if expense is not None:
            expense.status = decision

    await record_audit_event(
        db,
        event_type="approval.decided",
        actor=actor,
        entity_type=approval.entity_type,
        entity_id=approval.entity_id,
        action=decision,
        details={
            "approval_id": approval.id,
            "decision": decision,
            "notes": approval.decision_notes,
            "amount": float(approval.amount),
        },
    )
    await db.commit()
    await db.refresh(approval)
    return approval
