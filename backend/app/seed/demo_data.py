from datetime import timedelta
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.policy import audit_and_persist_expense
from app.audit.schemas import ExpenseCreate
from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.core.config import Settings
from app.core.text import normalize_counterparty
from app.db.base import utcnow
from app.db.models import (
    ApprovalRequest,
    AuditEvent,
    BankTransaction,
    CashAccountSnapshot,
    Expense,
    GoodsReceipt,
    IngestedDocument,
    Invoice,
    PaymentAllocation,
    PurchaseOrder,
    RecurringCommitment,
    ThreeWayMatch,
    Vendor,
)
from app.llm.router import LLMRouter
from app.reconciliation.ap_ar import propose_payment_allocations
from app.reconciliation.three_way import run_three_way_match


class SeedSummaryOut(BaseModel):
    seeded: bool
    vendors: int
    purchase_orders: int
    goods_receipts: int
    invoices: int
    three_way_matches: int
    bank_transactions: int
    payment_allocations: int
    expenses: int
    cash_accounts: int
    recurring_commitments: int
    pending_approvals: int
    message: str


async def _collect_counts(db: AsyncSession) -> dict[str, int]:
    return {
        "vendors": int((await db.scalar(select(func.count(Vendor.id)))) or 0),
        "purchase_orders": int((await db.scalar(select(func.count(PurchaseOrder.id)))) or 0),
        "goods_receipts": int((await db.scalar(select(func.count(GoodsReceipt.id)))) or 0),
        "invoices": int((await db.scalar(select(func.count(Invoice.id)))) or 0),
        "three_way_matches": int((await db.scalar(select(func.count(ThreeWayMatch.id)))) or 0),
        "bank_transactions": int((await db.scalar(select(func.count(BankTransaction.id)))) or 0),
        "payment_allocations": int(
            (await db.scalar(select(func.count(PaymentAllocation.id)))) or 0
        ),
        "expenses": int((await db.scalar(select(func.count(Expense.id)))) or 0),
        "cash_accounts": int((await db.scalar(select(func.count(CashAccountSnapshot.id)))) or 0),
        "recurring_commitments": int(
            (await db.scalar(select(func.count(RecurringCommitment.id)))) or 0
        ),
        "pending_approvals": int(
            (
                await db.scalar(
                    select(func.count(ApprovalRequest.id)).where(
                        ApprovalRequest.status == "pending"
                    )
                )
            )
            or 0
        ),
    }


async def seed_demo_dataset(
    db: AsyncSession,
    *,
    llm_router: LLMRouter,
    settings: Settings,
    actor: Actor,
    reset: bool = False,
) -> SeedSummaryOut:
    """Populate realistic Phase 1 finance ops fixtures across all modules."""
    existing_vendors = int((await db.scalar(select(func.count(Vendor.id)))) or 0)
    if existing_vendors > 0 and not reset:
        counts = await _collect_counts(db)
        return SeedSummaryOut(
            seeded=False,
            message="Database already populated; pass reset=true to reload demo dataset.",
            **counts,
        )

    if reset:
        for model in (
            AuditEvent,
            ThreeWayMatch,
            PaymentAllocation,
            Expense,
            ApprovalRequest,
            BankTransaction,
            Invoice,
            GoodsReceipt,
            PurchaseOrder,
            IngestedDocument,
            Vendor,
            RecurringCommitment,
            CashAccountSnapshot,
        ):
            await db.execute(delete(model))
        await db.flush()

    now = utcnow()
    today = now.date()

    vendors = [
        Vendor(
            code="V-CLOUDCORE",
            name="CloudCore Infrastructure LLC",
            tax_id="84-2104911",
            payment_terms_days=30,
            default_gl_account="6100-CLOUD",
        ),
        Vendor(
            code="V-APEX",
            name="Apex Logistics Group",
            tax_id="47-9930122",
            payment_terms_days=30,
            default_gl_account="5200-FREIGHT",
        ),
        Vendor(
            code="V-VANGUARD",
            name="Vanguard Hardware Supply",
            tax_id="36-5541098",
            payment_terms_days=45,
            default_gl_account="1500-EQUIPMENT",
        ),
        Vendor(
            code="V-NORTHSTAR",
            name="Northstar Security Labs",
            tax_id="91-3348201",
            payment_terms_days=30,
            default_gl_account="6400-SEC",
        ),
        Vendor(
            code="V-SUMMIT",
            name="Summit Advisory Partners",
            tax_id="22-8874120",
            payment_terms_days=15,
            default_gl_account="6300-ADVISORY",
        ),
    ]
    db.add_all(vendors)
    await db.flush()
    v_cloud, v_apex, v_vanguard, v_northstar, v_summit = vendors

    po_cloud = PurchaseOrder(
        po_number="PO-2026-1001",
        vendor_id=v_cloud.id,
        issue_date=today - timedelta(days=20),
        expected_delivery_date=today - timedelta(days=10),
        total_amount=Decimal("24000.00"),
        line_items_json=[{"sku": "GPU-NODE-X", "qty": 10, "unit_price": 2400.0}],
    )
    po_apex = PurchaseOrder(
        po_number="PO-2026-1002",
        vendor_id=v_apex.id,
        issue_date=today - timedelta(days=18),
        expected_delivery_date=today - timedelta(days=8),
        total_amount=Decimal("12000.00"),
        line_items_json=[{"sku": "FREIGHT-LN", "qty": 12, "unit_price": 1000.0}],
    )
    po_vanguard = PurchaseOrder(
        po_number="PO-2026-1003",
        vendor_id=v_vanguard.id,
        issue_date=today - timedelta(days=16),
        expected_delivery_date=today - timedelta(days=6),
        total_amount=Decimal("25000.00"),
        line_items_json=[{"sku": "WS-DOCK-PRO", "qty": 50, "unit_price": 500.0}],
    )
    po_northstar = PurchaseOrder(
        po_number="PO-2026-1004",
        vendor_id=v_northstar.id,
        issue_date=today - timedelta(days=12),
        expected_delivery_date=today - timedelta(days=2),
        total_amount=Decimal("18500.00"),
        line_items_json=[{"sku": "SOC2-AUDIT", "qty": 1, "unit_price": 18500.0}],
    )
    db.add_all([po_cloud, po_apex, po_vanguard, po_northstar])
    await db.flush()

    gr_cloud = GoodsReceipt(
        receipt_number="GR-2026-9001",
        po_id=po_cloud.id,
        vendor_id=v_cloud.id,
        received_date=today - timedelta(days=9),
        total_amount=Decimal("24000.00"),
        line_items_json=[{"sku": "GPU-NODE-X", "qty": 10}],
        notes="Full delivery verified by infrastructure ops.",
    )
    gr_apex = GoodsReceipt(
        receipt_number="GR-2026-9002",
        po_id=po_apex.id,
        vendor_id=v_apex.id,
        received_date=today - timedelta(days=7),
        total_amount=Decimal("12000.00"),
        line_items_json=[{"sku": "FREIGHT-LN", "qty": 12}],
        notes="12 regional freight shipments delivered.",
    )
    gr_vanguard = GoodsReceipt(
        receipt_number="GR-2026-9003",
        po_id=po_vanguard.id,
        vendor_id=v_vanguard.id,
        received_date=today - timedelta(days=5),
        total_amount=Decimal("21000.00"),
        line_items_json=[{"sku": "WS-DOCK-PRO", "qty": 42}],
        notes="Partial warehouse delivery: 42 of 50 docks received.",
    )
    db.add_all([gr_cloud, gr_apex, gr_vanguard])
    await db.flush()

    ap_invoices = [
        Invoice(
            invoice_number="INV-CC-401",
            direction="payable",
            vendor_id=v_cloud.id,
            counterparty_name=v_cloud.name,
            po_number="PO-2026-1001",
            issue_date=today - timedelta(days=8),
            due_date=today + timedelta(days=10),
            subtotal=Decimal("24000.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("24000.00"),
            line_items_json=[{"sku": "GPU-NODE-X", "qty": 10, "unit_price": 2400.0}],
            created_at=now - timedelta(seconds=30),
        ),
        Invoice(
            invoice_number="INV-APX-882",
            direction="payable",
            vendor_id=v_apex.id,
            counterparty_name=v_apex.name,
            po_number="PO-2026-1002",
            issue_date=today - timedelta(days=6),
            due_date=today + timedelta(days=20),
            subtotal=Decimal("13140.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("13140.00"),
            line_items_json=[{"sku": "FREIGHT-LN", "qty": 12, "unit_price": 1095.0}],
            created_at=now - timedelta(seconds=25),
        ),
        Invoice(
            invoice_number="INV-VAN-319",
            direction="payable",
            vendor_id=v_vanguard.id,
            counterparty_name=v_vanguard.name,
            po_number="PO-2026-1003",
            issue_date=today - timedelta(days=5),
            due_date=today + timedelta(days=28),
            subtotal=Decimal("25000.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("25000.00"),
            line_items_json=[{"sku": "WS-DOCK-PRO", "qty": 50, "unit_price": 500.0}],
            created_at=now - timedelta(seconds=20),
        ),
        Invoice(
            invoice_number="INV-SUM-105",
            direction="payable",
            vendor_id=v_summit.id,
            counterparty_name=v_summit.name,
            po_number=None,
            issue_date=today - timedelta(days=4),
            due_date=today + timedelta(days=11),
            subtotal=Decimal("8500.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("8500.00"),
            line_items_json=[{"sku": "ADV-Q4", "qty": 1, "unit_price": 8500.0}],
            created_at=now - timedelta(seconds=15),
        ),
        Invoice(
            invoice_number="INV-NS-774",
            direction="payable",
            vendor_id=v_northstar.id,
            counterparty_name=v_northstar.name,
            po_number="PO-2026-1004",
            issue_date=today - timedelta(days=2),
            due_date=today + timedelta(days=25),
            subtotal=Decimal("18500.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("18500.00"),
            line_items_json=[{"sku": "SOC2-AUDIT", "qty": 1, "unit_price": 18500.0}],
            created_at=now - timedelta(seconds=10),
        ),
        Invoice(
            invoice_number="INV-CC-401",
            direction="payable",
            vendor_id=v_cloud.id,
            counterparty_name=v_cloud.name,
            po_number="PO-2026-1001",
            issue_date=today - timedelta(days=1),
            due_date=today + timedelta(days=10),
            subtotal=Decimal("24000.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("24000.00"),
            line_items_json=[{"sku": "GPU-NODE-X", "qty": 10, "unit_price": 2400.0}],
            created_at=now,
        ),
    ]
    ar_invoices = [
        Invoice(
            invoice_number="AR-2026-501",
            direction="receivable",
            vendor_id=None,
            counterparty_name="Meridian Health Systems",
            po_number=None,
            issue_date=today - timedelta(days=12),
            due_date=today + timedelta(days=18),
            subtotal=Decimal("84500.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("84500.00"),
            match_status="approved",
        ),
        Invoice(
            invoice_number="AR-2026-489",
            direction="receivable",
            vendor_id=None,
            counterparty_name="Helios Retail Corp",
            po_number=None,
            issue_date=today - timedelta(days=52),
            due_date=today - timedelta(days=22),
            subtotal=Decimal("42000.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("42000.00"),
            match_status="approved",
        ),
    ]
    db.add_all([*ap_invoices, *ar_invoices])
    await db.flush()

    for inv in ap_invoices:
        await run_three_way_match(
            db,
            invoice=inv,
            llm_router=llm_router,
            settings=settings,
            actor=actor,
        )

    bank_txs = [
        BankTransaction(
            external_ref="BNK-9901",
            transaction_date=today - timedelta(days=1),
            description="ACH DEBIT CLOUDCORE INFRASTRUCTURE LLC INV-CC-401",
            normalized_counterparty=normalize_counterparty(
                "ACH DEBIT CLOUDCORE INFRASTRUCTURE LLC"
            ),
            direction="outflow",
            amount=Decimal("24000.00"),
        ),
        BankTransaction(
            external_ref="BNK-9902",
            transaction_date=today - timedelta(days=1),
            description="WIRE TRANSFER HELIOS RETAIL CORP AR-2026-489",
            normalized_counterparty=normalize_counterparty("WIRE TRANSFER HELIOS RETAIL CORP"),
            direction="inflow",
            amount=Decimal("42000.00"),
        ),
        BankTransaction(
            external_ref="BNK-9903",
            transaction_date=today,
            description="ACH CREDIT MERIDIAN HEALTH SYSTEMS PARTIAL AR-2026-501",
            normalized_counterparty=normalize_counterparty("ACH CREDIT MERIDIAN HEALTH SYSTEMS"),
            direction="inflow",
            amount=Decimal("40000.00"),
        ),
        BankTransaction(
            external_ref="BNK-9904",
            transaction_date=today,
            description="ACH DEBIT SUMMIT ADVISORY PARTNERS INV-SUM-105",
            normalized_counterparty=normalize_counterparty("ACH DEBIT SUMMIT ADVISORY PARTNERS"),
            direction="outflow",
            amount=Decimal("8500.00"),
        ),
        BankTransaction(
            external_ref="BNK-9905",
            transaction_date=today,
            description="POS PURCHASE UNMATCHED OFFICE DEPOT SUPPLIES",
            normalized_counterparty=normalize_counterparty("POS PURCHASE UNMATCHED OFFICE DEPOT"),
            direction="outflow",
            amount=Decimal("1245.50"),
        ),
    ]
    db.add_all(bank_txs)
    await db.flush()
    await propose_payment_allocations(db, llm_router=llm_router, actor=actor)

    weekday_recent = today - timedelta(days=(today.weekday() - 2) % 7)
    demo_expenses = [
        ExpenseCreate(
            employee_name="Elena Rostova",
            employee_email="elena@acme-finops.local",
            department="Engineering",
            merchant="Linear Software",
            expense_date=weekday_recent,
            category="software",
            tax_category="deductible_100",
            amount=149.00,
            receipt_hash="rcpt-sw-2026-01",
            description="Monthly engineering issue-tracker seats",
        ),
        ExpenseCreate(
            employee_name="Marcus Vance",
            employee_email="marcus@acme-finops.local",
            department="Sales",
            merchant="Bistro Moderne",
            expense_date=weekday_recent,
            category="meals",
            tax_category="deductible_50",
            amount=88.50,
            receipt_hash="rcpt-meal-dup-99",
            description="Working lunch with regional prospect",
        ),
        ExpenseCreate(
            employee_name="Marcus Vance",
            employee_email="marcus@acme-finops.local",
            department="Sales",
            merchant="Bistro Moderne",
            expense_date=weekday_recent,
            category="meals",
            tax_category="deductible_50",
            amount=88.50,
            receipt_hash="rcpt-meal-dup-99",
            description="Resubmitted lunch receipt",
        ),
        ExpenseCreate(
            employee_name="Dana Chen",
            employee_email="dana@acme-finops.local",
            department="Enterprise Sales",
            merchant="Symphony VIP Box",
            expense_date=weekday_recent,
            category="client_entertainment",
            tax_category="deductible_100",
            amount=390.00,
            receipt_hash="rcpt-ent-440",
            description="Client hospitality suite",
        ),
        ExpenseCreate(
            employee_name="Jordan Patel",
            employee_email="jordan@acme-finops.local",
            department="Operations",
            merchant="Prime Steakhouse",
            expense_date=weekday_recent,
            category="meals",
            tax_category="deductible_50",
            amount=310.00,
            receipt_hash=None,
            description="Team dinner without itemized receipt",
        ),
        ExpenseCreate(
            employee_name="Elena Rostova",
            employee_email="elena@acme-finops.local",
            department="Engineering",
            merchant="Delta Air Lines",
            expense_date=weekday_recent,
            category="travel",
            tax_category="deductible_100",
            amount=1180.00,
            receipt_hash="rcpt-trv-881",
            description="Round-trip flight for customer deployment",
        ),
    ]
    for exp_req in demo_expenses:
        await audit_and_persist_expense(
            db,
            payload=exp_req,
            llm_router=llm_router,
            settings=settings,
            actor=actor,
        )

    cash_accounts = [
        CashAccountSnapshot(
            account_name="Operating Checking",
            as_of_date=today,
            balance=Decimal("375000.00"),
            currency="USD",
        ),
        CashAccountSnapshot(
            account_name="Treasury Reserve",
            as_of_date=today,
            balance=Decimal("125000.00"),
            currency="USD",
        ),
    ]
    db.add_all(cash_accounts)

    commitments = [
        RecurringCommitment(
            name="Biweekly Corporate Payroll",
            counterparty="Gusto Payroll",
            direction="outflow",
            category="payroll",
            amount=Decimal("48000.00"),
            cadence="biweekly",
            next_due_date=today + timedelta(days=5),
        ),
        RecurringCommitment(
            name="HQ Office Lease",
            counterparty="Metro Properties REIT",
            direction="outflow",
            category="facilities",
            amount=Decimal("14500.00"),
            cadence="monthly",
            next_due_date=today + timedelta(days=8),
        ),
        RecurringCommitment(
            name="Cloud & AI Compute Hosting",
            counterparty="CloudCore Infrastructure LLC",
            direction="outflow",
            category="infrastructure",
            amount=Decimal("9200.00"),
            cadence="monthly",
            next_due_date=today + timedelta(days=12),
        ),
        RecurringCommitment(
            name="Enterprise SaaS Subscriptions",
            counterparty="Stripe Billing Cohort",
            direction="inflow",
            category="subscription_revenue",
            amount=Decimal("68000.00"),
            cadence="monthly",
            next_due_date=today + timedelta(days=7),
        ),
        RecurringCommitment(
            name="Managed FinOps Retainers",
            counterparty="Enterprise Advisory Clients",
            direction="inflow",
            category="services_revenue",
            amount=Decimal("21000.00"),
            cadence="biweekly",
            next_due_date=today + timedelta(days=4),
        ),
        RecurringCommitment(
            name="Quarterly Estimated Tax",
            counterparty="IRS / State Treasury",
            direction="outflow",
            category="taxes",
            amount=Decimal("32000.00"),
            cadence="quarterly",
            next_due_date=today + timedelta(days=45),
        ),
    ]
    db.add_all(commitments)
    await db.flush()

    await record_audit_event(
        db,
        event_type="seed.loaded",
        actor=actor,
        entity_type="workspace",
        entity_id="demo-dataset",
        action="seeded",
        details={"reset": reset, "vendors": len(vendors), "invoices": len(ap_invoices) + 2},
    )
    await db.commit()

    counts = await _collect_counts(db)
    return SeedSummaryOut(
        seeded=True,
        message="Loaded realistic Phase 1 AI Finance Operations demo dataset.",
        **counts,
    )
