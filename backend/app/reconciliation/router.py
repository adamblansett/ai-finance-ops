from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_roles
from app.core.config import Settings, get_settings
from app.db.models import (
    BankTransaction,
    GoodsReceipt,
    Invoice,
    PaymentAllocation,
    PurchaseOrder,
    ThreeWayMatch,
    Vendor,
)
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router
from app.reconciliation.ap_ar import propose_payment_allocations
from app.reconciliation.schemas import (
    BankTransactionOut,
    BatchAllocationSummaryOut,
    BatchMatchSummaryOut,
    GoodsReceiptOut,
    InvoiceOut,
    MatchAnomalyOut,
    PaymentAllocationOut,
    PurchaseOrderOut,
    ThreeWayMatchOut,
    VendorOut,
)
from app.reconciliation.three_way import run_three_way_match

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


def _resolve_settings(request: Request, fallback: Settings) -> Settings:
    app_cfg = getattr(request.app.state, "settings", None)
    if isinstance(app_cfg, Settings):
        return app_cfg
    return fallback


async def _hydrate_matches(db: AsyncSession, rows: list[ThreeWayMatch]) -> list[ThreeWayMatchOut]:
    if not rows:
        return []
    inv_map = {r.id: r for r in (await db.execute(select(Invoice))).scalars().all()}
    po_map = {r.id: r for r in (await db.execute(select(PurchaseOrder))).scalars().all()}
    rec_map = {r.id: r for r in (await db.execute(select(GoodsReceipt))).scalars().all()}

    output: list[ThreeWayMatchOut] = []
    for row in rows:
        inv = inv_map.get(row.invoice_id)
        po = po_map.get(row.po_id) if row.po_id else None
        rec = rec_map.get(row.receipt_id) if row.receipt_id else None
        anomalies = [
            MatchAnomalyOut(
                code=str(a.get("code", "ANOMALY")),
                severity=a.get("severity", "medium"),
                message=str(a.get("message", "")),
            )
            for a in (row.anomalies_json or [])
        ]
        output.append(
            ThreeWayMatchOut(
                id=row.id,
                invoice_id=row.invoice_id,
                invoice_number=inv.invoice_number if inv else None,
                counterparty_name=inv.counterparty_name if inv else None,
                invoice_total=float(inv.total_amount) if inv else None,
                po_id=row.po_id,
                po_number=po.po_number if po else None,
                po_total=float(po.total_amount) if po else None,
                receipt_id=row.receipt_id,
                receipt_number=rec.receipt_number if rec else None,
                status=row.status,
                confidence_score=row.confidence_score,
                price_variance=float(row.price_variance),
                price_variance_pct=row.price_variance_pct,
                qty_variance=row.qty_variance,
                anomalies=anomalies,
                ai_explanation=row.ai_explanation,
                llm_provider_used=row.llm_provider_used,
                approval_id=row.approval_id,
                updated_at=row.updated_at,
            )
        )
    return output


async def _hydrate_allocations(
    db: AsyncSession,
    rows: list[PaymentAllocation],
) -> list[PaymentAllocationOut]:
    if not rows:
        return []
    tx_map = {r.id: r for r in (await db.execute(select(BankTransaction))).scalars().all()}
    inv_map = {r.id: r for r in (await db.execute(select(Invoice))).scalars().all()}

    result: list[PaymentAllocationOut] = []
    for row in rows:
        tx = tx_map.get(row.bank_transaction_id)
        inv = inv_map.get(row.invoice_id)
        result.append(
            PaymentAllocationOut(
                id=row.id,
                bank_transaction_id=row.bank_transaction_id,
                bank_ref=tx.external_ref if tx else None,
                bank_description=tx.description if tx else None,
                invoice_id=row.invoice_id,
                invoice_number=inv.invoice_number if inv else None,
                counterparty_name=inv.counterparty_name if inv else None,
                allocated_amount=float(row.allocated_amount),
                confidence_score=row.confidence_score,
                match_reason=row.match_reason,
                status=row.status,
                approval_id=row.approval_id,
                created_at=row.created_at,
            )
        )
    return result


@router.get("/vendors", response_model=list[VendorOut])
async def list_vendors(
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[VendorOut]:
    rows = (await db.execute(select(Vendor).order_by(Vendor.name.asc()))).scalars().all()
    return [
        VendorOut(
            id=r.id,
            code=r.code,
            name=r.name,
            tax_id=r.tax_id,
            payment_terms_days=r.payment_terms_days,
            default_gl_account=r.default_gl_account,
            status=r.status,
        )
        for r in rows
    ]


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
async def list_purchase_orders(
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[PurchaseOrderOut]:
    vendors = {v.id: v.name for v in (await db.execute(select(Vendor))).scalars().all()}
    rows = (
        await db.execute(select(PurchaseOrder).order_by(PurchaseOrder.issue_date.desc()))
    ).scalars().all()
    return [
        PurchaseOrderOut(
            id=r.id,
            po_number=r.po_number,
            vendor_id=r.vendor_id,
            vendor_name=vendors.get(r.vendor_id),
            issue_date=r.issue_date,
            expected_delivery_date=r.expected_delivery_date,
            currency=r.currency,
            total_amount=float(r.total_amount),
            status=r.status,
            line_items=r.line_items_json,
        )
        for r in rows
    ]


@router.get("/receipts", response_model=list[GoodsReceiptOut])
async def list_goods_receipts(
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[GoodsReceiptOut]:
    rows = (
        await db.execute(select(GoodsReceipt).order_by(GoodsReceipt.received_date.desc()))
    ).scalars().all()
    return [
        GoodsReceiptOut(
            id=r.id,
            receipt_number=r.receipt_number,
            po_id=r.po_id,
            vendor_id=r.vendor_id,
            received_date=r.received_date,
            total_amount=float(r.total_amount),
            line_items=r.line_items_json,
            notes=r.notes,
        )
        for r in rows
    ]


@router.get("/invoices", response_model=list[InvoiceOut])
async def list_invoices(
    direction: str | None = Query(default=None),
    match_status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[InvoiceOut]:
    stmt = select(Invoice).order_by(Invoice.due_date.asc(), Invoice.created_at.desc())
    if direction:
        stmt = stmt.where(Invoice.direction == direction.strip().lower())
    if match_status:
        stmt = stmt.where(Invoice.match_status == match_status.strip().lower())
    rows = (await db.execute(stmt)).scalars().all()
    return [
        InvoiceOut(
            id=r.id,
            invoice_number=r.invoice_number,
            direction=r.direction,
            vendor_id=r.vendor_id,
            counterparty_name=r.counterparty_name,
            po_number=r.po_number,
            issue_date=r.issue_date,
            due_date=r.due_date,
            currency=r.currency,
            subtotal=float(r.subtotal),
            tax_amount=float(r.tax_amount),
            total_amount=float(r.total_amount),
            amount_paid=float(r.amount_paid),
            match_status=r.match_status,
            payment_status=r.payment_status,
            line_items=r.line_items_json,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/invoices/{invoice_id}/match", response_model=ThreeWayMatchOut)
async def match_single_invoice(
    invoice_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require_roles("analyst", "controller", "admin")),
) -> ThreeWayMatchOut:
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice '{invoice_id}' not found.",
        )
    cfg = _resolve_settings(request, settings)
    match = await run_three_way_match(
        db,
        invoice=invoice,
        llm_router=llm_router,
        settings=cfg,
        actor=actor,
    )
    await db.commit()
    hydrated = await _hydrate_matches(db, [match])
    return hydrated[0]


@router.post("/match-all", response_model=BatchMatchSummaryOut)
async def match_all_payable_invoices(
    request: Request,
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require_roles("analyst", "controller", "admin")),
) -> BatchMatchSummaryOut:
    cfg = _resolve_settings(request, settings)
    stmt = (
        select(Invoice)
        .where(
            Invoice.direction == "payable",
            Invoice.match_status.notin_(["approved", "rejected"]),
        )
        .order_by(Invoice.created_at.asc())
    )
    invoices = list((await db.execute(stmt)).scalars().all())
    matches: list[ThreeWayMatch] = []
    for inv in invoices:
        matches.append(
            await run_three_way_match(
                db,
                invoice=inv,
                llm_router=llm_router,
                settings=cfg,
                actor=actor,
            )
        )
    await db.commit()
    hydrated = await _hydrate_matches(db, matches)
    matched_count = sum(1 for m in hydrated if m.status == "matched")
    return BatchMatchSummaryOut(
        processed_count=len(hydrated),
        matched_count=matched_count,
        flagged_count=len(hydrated) - matched_count,
        matches=hydrated,
    )


@router.get("/matches", response_model=list[ThreeWayMatchOut])
async def list_three_way_matches(
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[ThreeWayMatchOut]:
    stmt = select(ThreeWayMatch).order_by(ThreeWayMatch.updated_at.desc())
    if status_filter:
        stmt = stmt.where(ThreeWayMatch.status == status_filter.strip().lower())
    rows = list((await db.execute(stmt)).scalars().all())
    return await _hydrate_matches(db, rows)


@router.get("/bank-transactions", response_model=list[BankTransactionOut])
async def list_bank_transactions(
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[BankTransactionOut]:
    stmt = select(BankTransaction).order_by(BankTransaction.transaction_date.desc())
    if status_filter:
        stmt = stmt.where(BankTransaction.status == status_filter.strip().lower())
    rows = (await db.execute(stmt)).scalars().all()
    return [
        BankTransactionOut(
            id=r.id,
            external_ref=r.external_ref,
            transaction_date=r.transaction_date,
            description=r.description,
            normalized_counterparty=r.normalized_counterparty,
            direction=r.direction,
            amount=float(r.amount),
            currency=r.currency,
            account_name=r.account_name,
            status=r.status,
        )
        for r in rows
    ]


@router.post("/ap-ar/propose", response_model=BatchAllocationSummaryOut)
async def run_ap_ar_matching(
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    actor: Actor = Depends(require_roles("analyst", "controller", "admin")),
) -> BatchAllocationSummaryOut:
    created = await propose_payment_allocations(db, llm_router=llm_router, actor=actor)
    await db.commit()
    hydrated = await _hydrate_allocations(db, created)
    return BatchAllocationSummaryOut(proposed_count=len(hydrated), allocations=hydrated)


@router.get("/allocations", response_model=list[PaymentAllocationOut])
async def list_payment_allocations(
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[PaymentAllocationOut]:
    stmt = select(PaymentAllocation).order_by(PaymentAllocation.created_at.desc())
    if status_filter:
        stmt = stmt.where(PaymentAllocation.status == status_filter.strip().lower())
    rows = list((await db.execute(stmt)).scalars().all())
    return await _hydrate_allocations(db, rows)
