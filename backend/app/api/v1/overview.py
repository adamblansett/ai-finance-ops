from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import verify_audit_chain
from app.core.auth import Actor, get_current_actor
from app.db.base import quantize_money
from app.db.models import (
    ApprovalRequest,
    BankTransaction,
    CashAccountSnapshot,
    Expense,
    Invoice,
    ThreeWayMatch,
)
from app.db.session import get_db
from app.forecasting.engine import build_13_week_forecast
from app.forecasting.schemas import ForecastScenarioRequest
from app.llm.router import LLMRouter, get_llm_router

router = APIRouter(prefix="/overview", tags=["overview"])


class OverviewSummaryOut(BaseModel):
    total_cash: float
    projected_week_13_cash: float
    estimated_runway_weeks: float | None
    open_ap_total: float
    open_ar_total: float
    pending_approvals_count: int
    flagged_matches_count: int
    matched_invoices_count: int
    flagged_expenses_count: int
    unallocated_transactions_count: int
    audit_events_count: int
    audit_chain_valid: bool


@router.get("", response_model=OverviewSummaryOut)
async def get_overview(
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    _: Actor = Depends(get_current_actor),
) -> OverviewSummaryOut:
    """Return executive operational KPIs across AP, AR, Expenses, Cash, and Audit."""
    accounts = list((await db.execute(select(CashAccountSnapshot))).scalars().all())
    total_cash = quantize_money(sum((a.balance for a in accounts), Decimal("0.00")))

    invoices = list((await db.execute(select(Invoice))).scalars().all())
    open_ap = quantize_money(
        sum(
            (
                max(Decimal("0.00"), i.total_amount - i.amount_paid)
                for i in invoices
                if i.direction == "payable" and i.match_status != "rejected"
            ),
            Decimal("0.00"),
        )
    )
    open_ar = quantize_money(
        sum(
            (
                max(Decimal("0.00"), i.total_amount - i.amount_paid)
                for i in invoices
                if i.direction == "receivable" and i.match_status != "rejected"
            ),
            Decimal("0.00"),
        )
    )

    pending_approvals = int(
        (
            await db.scalar(
                select(func.count(ApprovalRequest.id)).where(
                    ApprovalRequest.status == "pending"
                )
            )
        )
        or 0
    )
    matches = list((await db.execute(select(ThreeWayMatch))).scalars().all())
    matched_count = sum(1 for m in matches if m.status in {"matched", "approved"})
    flagged_matches = sum(
        1
        for m in matches
        if m.status
        in {"variance_flagged", "missing_po", "missing_receipt", "duplicate_flagged"}
    )
    flagged_expenses = int(
        (
            await db.scalar(
                select(func.count(Expense.id)).where(
                    Expense.status.in_(["flagged", "pending_review"])
                )
            )
        )
        or 0
    )
    unallocated_txs = int(
        (
            await db.scalar(
                select(func.count(BankTransaction.id)).where(
                    BankTransaction.status == "unallocated"
                )
            )
        )
        or 0
    )

    forecast = await build_13_week_forecast(
        db, llm_router=llm_router, scenario=ForecastScenarioRequest()
    )
    chain = await verify_audit_chain(db)

    return OverviewSummaryOut(
        total_cash=float(total_cash),
        projected_week_13_cash=forecast.ending_cash_week_13,
        estimated_runway_weeks=forecast.estimated_runway_weeks,
        open_ap_total=float(open_ap),
        open_ar_total=float(open_ar),
        pending_approvals_count=pending_approvals,
        flagged_matches_count=flagged_matches,
        matched_invoices_count=matched_count,
        flagged_expenses_count=flagged_expenses,
        unallocated_transactions_count=unallocated_txs,
        audit_events_count=chain.total_events,
        audit_chain_valid=chain.valid,
    )
