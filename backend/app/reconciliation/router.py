from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
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
from app.llm.embeddings import EmbeddingService, find_similar_entities, get_embedding_service
from app.llm.router import LLMRouter, get_llm_router
from app.reconciliation.ap_ar import propose_payment_allocations
from app.reconciliation.gl_coding import GLSuggestionOut, suggest_gl_account
from app.reconciliation.schemas import (
    BankTransactionOut,
    BatchAllocationSummaryOut,
    BatchMatchSummaryOut,
    GLSuggestRequest,
    GoodsReceiptOut,
    InvoiceOut,
    MatchAnomalyOut,
    PaymentAllocationOut,
    PurchaseOrderOut,
    SemanticSearchHitOut,
    SemanticSearchRequest,
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
    inv_ids = {r.invoice_id for r in rows}
    po_ids = {r.po_id for r in rows if r.po_id}
    rec_ids = {r.receipt_id for r in rows if r.receipt_id}

    inv_map = {
        r.id: r
        for r in (await db.execute(select(Invoice).where(Invoice.id.in_(inv_ids)))).scalars().all()
    }
    po_map = (
        {
            r.id: r
            for r in (
                await db.execute(select(PurchaseOrder).where(PurchaseOrder.id.in_(po_ids)))
            )
            .scalars()
            .all()
        }
        if po_ids
        else {}
    )
    rec_map = (
        {
            r.id: r
            for r in (
                await db.execute(select(GoodsReceipt).where(GoodsReceipt.id.in_(rec_ids)))
            )
            .scalars()
            .all()
        }
        if rec_ids
        else {}
    )

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
    tx_ids = {r.bank_transaction_id for r in rows}
    inv_ids = {r.invoice_id for r in rows}

    tx_map = {
        r.id: r
        for r in (
            await db.execute(select(BankTransaction).where(BankTransaction.id.in_(tx_ids)))
        )
        .scalars()
        .all()
    }
    inv_map = {
        r.id: r
        for r in (await db.execute(select(Invoice).where(Invoice.id.in_(inv_ids)))).scalars().all()
    }

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
    response: Response,
    direction: str | None = Query(default=None),
    match_status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[InvoiceOut]:
    stmt = select(Invoice)
    count_stmt = select(func.count(Invoice.id))
    if direction:
        d = direction.strip().lower()
        stmt = stmt.where(Invoice.direction == d)
        count_stmt = count_stmt.where(Invoice.direction == d)
    if match_status:
        ms = match_status.strip().lower()
        stmt = stmt.where(Invoice.match_status == ms)
        count_stmt = count_stmt.where(Invoice.match_status == ms)
    if search and search.strip():
        pat = f"%{search.strip()}%"
        cond = or_(
            Invoice.invoice_number.ilike(pat),
            Invoice.counterparty_name.ilike(pat),
            Invoice.po_number.ilike(pat),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.scalar(count_stmt)) or 0)
    response.headers["X-Total-Count"] = str(total)
    stmt = (
        stmt.order_by(Invoice.due_date.asc(), Invoice.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
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
            gl_account=r.gl_account,
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
    embedding_service: EmbeddingService = Depends(get_embedding_service),
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
        embedding_service=embedding_service,
    )
    await db.commit()
    hydrated = await _hydrate_matches(db, [match])
    return hydrated[0]


@router.post("/match-all", response_model=BatchMatchSummaryOut)
async def match_all_payable_invoices(
    request: Request,
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
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
                embedding_service=embedding_service,
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
    response: Response,
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[ThreeWayMatchOut]:
    stmt = select(ThreeWayMatch)
    count_stmt = select(func.count(ThreeWayMatch.id))
    if status_filter:
        st = status_filter.strip().lower()
        stmt = stmt.where(ThreeWayMatch.status == st)
        count_stmt = count_stmt.where(ThreeWayMatch.status == st)
    if search and search.strip():
        pat = f"%{search.strip()}%"
        inv_ids_subq = select(Invoice.id).where(
            or_(Invoice.invoice_number.ilike(pat), Invoice.counterparty_name.ilike(pat))
        )
        cond = ThreeWayMatch.invoice_id.in_(inv_ids_subq)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.scalar(count_stmt)) or 0)
    response.headers["X-Total-Count"] = str(total)
    stmt = stmt.order_by(ThreeWayMatch.updated_at.desc()).offset(offset).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    return await _hydrate_matches(db, rows)


@router.get("/bank-transactions", response_model=list[BankTransactionOut])
async def list_bank_transactions(
    response: Response,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[BankTransactionOut]:
    stmt = select(BankTransaction)
    count_stmt = select(func.count(BankTransaction.id))
    if status_filter:
        st = status_filter.strip().lower()
        stmt = stmt.where(BankTransaction.status == st)
        count_stmt = count_stmt.where(BankTransaction.status == st)

    total = int((await db.scalar(count_stmt)) or 0)
    response.headers["X-Total-Count"] = str(total)
    stmt = stmt.order_by(BankTransaction.transaction_date.desc()).offset(offset).limit(limit)
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
    response: Response,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[PaymentAllocationOut]:
    stmt = select(PaymentAllocation)
    count_stmt = select(func.count(PaymentAllocation.id))
    if status_filter:
        st = status_filter.strip().lower()
        stmt = stmt.where(PaymentAllocation.status == st)
        count_stmt = count_stmt.where(PaymentAllocation.status == st)

    total = int((await db.scalar(count_stmt)) or 0)
    response.headers["X-Total-Count"] = str(total)
    stmt = stmt.order_by(PaymentAllocation.created_at.desc()).offset(offset).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    return await _hydrate_allocations(db, rows)


@router.post("/gl-suggest", response_model=GLSuggestionOut)
async def suggest_gl_code(
    payload: GLSuggestRequest,
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    _: Actor = Depends(get_current_actor),
) -> GLSuggestionOut:
    """Suggest Chart-of-Accounts GL coding via semantic similarity."""
    return await suggest_gl_account(
        description=payload.description,
        vendor_name=payload.vendor_name,
        default_gl=payload.default_gl,
        embedding_service=embedding_service,
    )


@router.post("/semantic-search", response_model=list[SemanticSearchHitOut])
async def semantic_search(
    payload: SemanticSearchRequest,
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    _: Actor = Depends(get_current_actor),
) -> list[SemanticSearchHitOut]:
    """Search invoices or purchase orders by vector cosine similarity."""
    hits = await find_similar_entities(
        db,
        entity_type=payload.entity_type,
        query_text=payload.query,
        embedding_service=embedding_service,
        top_k=payload.top_k,
    )
    return [
        SemanticSearchHitOut(
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            score=score,
            source_text=row.source_text,
        )
        for row, score in hits
    ]
