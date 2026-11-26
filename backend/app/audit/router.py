from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.policy import audit_and_persist_expense, reaudit_existing_expense
from app.audit.schemas import (
    ApprovalDecisionRequest,
    ApprovalOut,
    AuditChainVerifyOut,
    AuditEventOut,
    ExpenseCreate,
    ExpenseOut,
    PiiRedactRequest,
    PiiRedactResponse,
    PolicyViolationOut,
)
from app.audit.service import decide_approval, verify_audit_chain
from app.core.auth import Actor, get_current_actor, require_roles
from app.core.config import Settings, get_settings
from app.db.models import ApprovalRequest, AuditEvent, Expense
from app.db.session import get_db
from app.llm.pii import redact_pii
from app.llm.router import LLMRouter, get_llm_router

router = APIRouter(prefix="/audit", tags=["audit"])


def _resolve_settings(request: Request, fallback: Settings) -> Settings:
    app_cfg = getattr(request.app.state, "settings", None)
    if isinstance(app_cfg, Settings):
        return app_cfg
    return fallback


def _to_expense_out(row: Expense) -> ExpenseOut:
    violations = [
        PolicyViolationOut(
            rule_code=str(v.get("rule_code", "POLICY_RULE")),
            severity=v.get("severity", "medium"),
            message=str(v.get("message", "")),
        )
        for v in (row.policy_violations_json or [])
    ]
    return ExpenseOut(
        id=row.id,
        employee_name=row.employee_name,
        employee_email=row.employee_email,
        department=row.department,
        merchant=row.merchant,
        expense_date=row.expense_date,
        category=row.category,
        tax_category=row.tax_category,
        amount=float(row.amount),
        currency=row.currency,
        receipt_hash=row.receipt_hash,
        description=row.description,
        status=row.status,
        policy_violations=violations,
        ai_audit_note=row.ai_audit_note,
        approval_id=row.approval_id,
        created_at=row.created_at,
    )


def _to_approval_out(row: ApprovalRequest) -> ApprovalOut:
    return ApprovalOut(
        id=row.id,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        action_requested=row.action_requested,
        summary=row.summary,
        amount=float(row.amount),
        risk_level=row.risk_level,
        status=row.status,
        requested_by=row.requested_by,
        decided_by=row.decided_by,
        decision_notes=row.decision_notes,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


@router.get("/expenses", response_model=list[ExpenseOut])
async def list_expenses(
    response: Response,
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[ExpenseOut]:
    """List submitted expenses newest first with pagination and search."""
    stmt = select(Expense)
    count_stmt = select(func.count(Expense.id))
    if status_filter:
        st = status_filter.strip().lower()
        stmt = stmt.where(Expense.status == st)
        count_stmt = count_stmt.where(Expense.status == st)
    if search and search.strip():
        pat = f"%{search.strip()}%"
        cond = or_(
            Expense.merchant.ilike(pat),
            Expense.employee_name.ilike(pat),
            Expense.category.ilike(pat),
            Expense.description.ilike(pat),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.scalar(count_stmt)) or 0)
    response.headers["X-Total-Count"] = str(total)
    stmt = (
        stmt.order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_expense_out(r) for r in rows]


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def submit_expense(
    payload: ExpenseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require_roles("analyst", "controller", "admin")),
) -> ExpenseOut:
    """Submit a corporate expense and evaluate policy, tax, and duplicate receipt rules."""
    cfg = _resolve_settings(request, settings)
    expense = await audit_and_persist_expense(
        db,
        payload=payload,
        llm_router=llm_router,
        settings=cfg,
        actor=actor,
    )
    await db.commit()
    await db.refresh(expense)
    return _to_expense_out(expense)


@router.post("/expenses/{expense_id}/reaudit", response_model=ExpenseOut)
async def reaudit_expense(
    expense_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require_roles("analyst", "controller", "admin")),
) -> ExpenseOut:
    """Re-run expense policy evaluation on an existing expense."""
    expense = await db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expense '{expense_id}' not found.",
        )
    cfg = _resolve_settings(request, settings)
    await reaudit_existing_expense(
        db,
        expense=expense,
        llm_router=llm_router,
        settings=cfg,
        actor=actor,
    )
    await db.commit()
    await db.refresh(expense)
    return _to_expense_out(expense)


@router.get("/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    response: Response,
    status_filter: str | None = Query(default=None, alias="status"),
    entity_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[ApprovalOut]:
    """List HITL controller approval requests with pagination."""
    stmt = select(ApprovalRequest)
    count_stmt = select(func.count(ApprovalRequest.id))
    if status_filter:
        st = status_filter.strip().lower()
        stmt = stmt.where(ApprovalRequest.status == st)
        count_stmt = count_stmt.where(ApprovalRequest.status == st)
    if entity_type:
        et = entity_type.strip().lower()
        stmt = stmt.where(ApprovalRequest.entity_type == et)
        count_stmt = count_stmt.where(ApprovalRequest.entity_type == et)

    total = int((await db.scalar(count_stmt)) or 0)
    response.headers["X-Total-Count"] = str(total)
    stmt = stmt.order_by(ApprovalRequest.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_approval_out(r) for r in rows]


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalOut)
async def decide_approval_endpoint(
    approval_id: str,
    body: ApprovalDecisionRequest,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_roles("controller", "admin")),
) -> ApprovalOut:
    """Approve or reject a pending HITL approval gate (Controller/Admin only)."""
    approval = await decide_approval(
        db,
        approval_id=approval_id,
        decision=body.decision,
        notes=body.notes,
        actor=actor,
    )
    return _to_approval_out(approval)


@router.get("/events", response_model=list[AuditEventOut])
async def list_audit_events(
    response: Response,
    entity_type: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[AuditEventOut]:
    """List immutable SOX audit trail events newest first with pagination."""
    stmt = select(AuditEvent)
    count_stmt = select(func.count(AuditEvent.id))
    if entity_type:
        et = entity_type.strip().lower()
        stmt = stmt.where(AuditEvent.entity_type == et)
        count_stmt = count_stmt.where(AuditEvent.entity_type == et)
    if event_type:
        ev_t = event_type.strip()
        stmt = stmt.where(AuditEvent.event_type == ev_t)
        count_stmt = count_stmt.where(AuditEvent.event_type == ev_t)
    if search and search.strip():
        pat = f"%{search.strip()}%"
        cond = or_(
            AuditEvent.event_type.ilike(pat),
            AuditEvent.actor_email.ilike(pat),
            AuditEvent.action.ilike(pat),
            AuditEvent.entity_id.ilike(pat),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.scalar(count_stmt)) or 0)
    response.headers["X-Total-Count"] = str(total)
    stmt = stmt.order_by(AuditEvent.sequence_no.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        AuditEventOut(
            id=r.id,
            sequence_no=r.sequence_no,
            event_type=r.event_type,
            actor_email=r.actor_email,
            actor_role=r.actor_role,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            action=r.action,
            details=r.details_json,
            prev_hash=r.prev_hash,
            event_hash=r.event_hash,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/events/verify", response_model=AuditChainVerifyOut)
async def verify_audit_events(
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> AuditChainVerifyOut:
    """Verify integrity of the entire SHA-256 hash-chained audit trail."""
    return await verify_audit_chain(db)


@router.post("/pii/redact", response_model=PiiRedactResponse)
async def preview_pii_redaction(
    payload: PiiRedactRequest,
    _: Actor = Depends(get_current_actor),
) -> PiiRedactResponse:
    """Preview outbound cloud PII scrubbing on arbitrary text."""
    result = redact_pii(payload.text)
    return PiiRedactResponse(
        redacted_text=result.redacted_text,
        findings=result.findings,
        total_redactions=result.total_redactions,
    )
