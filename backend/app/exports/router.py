import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import verify_audit_chain
from app.core.auth import Actor, get_current_actor
from app.db.models import ApprovalRequest, AuditEvent, Invoice, PurchaseOrder, ThreeWayMatch
from app.db.session import get_db
from app.forecasting.engine import build_13_week_forecast
from app.forecasting.schemas import ForecastScenarioRequest
from app.llm.router import LLMRouter, get_llm_router

router = APIRouter(prefix="/exports", tags=["exports"])


def _csv_response(filename: str, headers: list[str], rows: list[list[Any]]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit-log.csv")
async def export_audit_log_csv(
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> Response:
    """Download the immutable SOX hash-chained audit trail as CSV."""
    events = (
        await db.execute(select(AuditEvent).order_by(AuditEvent.sequence_no.asc()))
    ).scalars().all()
    rows = [
        [
            e.sequence_no,
            e.created_at.isoformat(),
            e.event_type,
            e.actor_email,
            e.actor_role,
            e.entity_type,
            e.entity_id,
            e.action,
            e.prev_hash,
            e.event_hash,
        ]
        for e in events
    ]
    return _csv_response(
        "sox-audit-log.csv",
        [
            "sequence_no",
            "created_at",
            "event_type",
            "actor_email",
            "actor_role",
            "entity_type",
            "entity_id",
            "action",
            "prev_hash",
            "event_hash",
        ],
        rows,
    )


@router.get("/reconciliation-packet.csv")
async def export_reconciliation_packet_csv(
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> Response:
    """Download the 3-way reconciliation packet with GL codes and anomalies."""
    matches = (
        await db.execute(select(ThreeWayMatch).order_by(ThreeWayMatch.updated_at.desc()))
    ).scalars().all()
    inv_map = {r.id: r for r in (await db.execute(select(Invoice))).scalars().all()}
    po_map = {r.id: r for r in (await db.execute(select(PurchaseOrder))).scalars().all()}

    rows: list[list[Any]] = []
    for m in matches:
        inv = inv_map.get(m.invoice_id)
        po = po_map.get(m.po_id) if m.po_id else None
        codes = ";".join(str(a.get("code", "")) for a in (m.anomalies_json or []))
        rows.append(
            [
                inv.invoice_number if inv else m.invoice_id,
                inv.counterparty_name if inv else "",
                inv.gl_account if inv else "",
                po.po_number if po else "",
                float(inv.total_amount) if inv else 0.0,
                m.status,
                m.confidence_score,
                float(m.price_variance),
                m.price_variance_pct,
                m.qty_variance,
                codes,
            ]
        )
    return _csv_response(
        "reconciliation-packet.csv",
        [
            "invoice_number",
            "counterparty",
            "gl_account",
            "po_number",
            "invoice_total",
            "status",
            "confidence_score",
            "price_variance",
            "price_variance_pct",
            "qty_variance",
            "anomaly_codes",
        ],
        rows,
    )


@router.get("/cashflow-13w.csv")
async def export_cashflow_csv(
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    _: Actor = Depends(get_current_actor),
) -> Response:
    """Download the rolling 13-week cash flow projection ledger as CSV."""
    fc = await build_13_week_forecast(
        db, llm_router=llm_router, scenario=ForecastScenarioRequest()
    )
    rows = [
        [
            w.week_number,
            w.week_start.isoformat(),
            w.week_end.isoformat(),
            w.opening_cash,
            w.ar_inflows,
            w.recurring_inflows,
            w.ap_outflows,
            w.recurring_outflows,
            w.net_cash_flow,
            w.closing_cash,
        ]
        for w in fc.weeks
    ]
    return _csv_response(
        "cashflow-13-week.csv",
        [
            "week_number",
            "week_start",
            "week_end",
            "opening_cash",
            "ar_inflows",
            "recurring_inflows",
            "ap_outflows",
            "recurring_outflows",
            "net_cash_flow",
            "closing_cash",
        ],
        rows,
    )


@router.get("/controller-pack.json")
async def export_controller_pack_json(
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    _: Actor = Depends(get_current_actor),
) -> dict[str, Any]:
    """Export a consolidated JSON controller close bundle."""
    chain = await verify_audit_chain(db)
    forecast = await build_13_week_forecast(
        db, llm_router=llm_router, scenario=ForecastScenarioRequest()
    )
    approvals = (await db.execute(select(ApprovalRequest))).scalars().all()
    matches = (await db.execute(select(ThreeWayMatch))).scalars().all()
    return {
        "audit_chain": chain.model_dump(),
        "forecast_13w": forecast.model_dump(mode="json"),
        "matches_summary": {
            "total": len(matches),
            "by_status": {
                st: sum(1 for m in matches if m.status == st)
                for st in sorted({m.status for m in matches})
            },
        },
        "approvals_summary": {
            "total": len(approvals),
            "pending": sum(1 for a in approvals if a.status == "pending"),
            "approved": sum(1 for a in approvals if a.status == "approved"),
            "rejected": sum(1 for a in approvals if a.status == "rejected"),
        },
    }
