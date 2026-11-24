"""Initial schema for AI Finance Operations.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tax_id", sa.String(length=64), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False),
        sa.Column("default_gl_account", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vendors_code"), "vendors", ["code"], unique=True)
    op.create_index(op.f("ix_vendors_name"), "vendors", ["name"], unique=False)

    op.create_table(
        "ingested_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("doc_type", sa.String(length=40), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_size_bytes", sa.Integer(), nullable=False),
        sa.Column("parsed_records_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_of_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("uploaded_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ingested_documents_content_sha256"),
        "ingested_documents",
        ["content_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingested_documents_doc_type"),
        "ingested_documents",
        ["doc_type"],
        unique=False,
    )

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("action_requested", sa.String(length=80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column("decided_by", sa.String(length=200), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_approval_requests_entity_id"), "approval_requests", ["entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_approval_requests_entity_type"),
        "approval_requests",
        ["entity_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_requests_status"), "approval_requests", ["status"], unique=False
    )

    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("external_ref", sa.String(length=80), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("normalized_counterparty", sa.String(length=200), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("account_name", sa.String(length=100), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_bank_transactions_content_sha256"),
        "bank_transactions",
        ["content_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bank_transactions_external_ref"),
        "bank_transactions",
        ["external_ref"],
        unique=True,
    )
    op.create_index(
        op.f("ix_bank_transactions_normalized_counterparty"),
        "bank_transactions",
        ["normalized_counterparty"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bank_transactions_status"), "bank_transactions", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_bank_transactions_transaction_date"),
        "bank_transactions",
        ["transaction_date"],
        unique=False,
    )

    op.create_table(
        "recurring_commitments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("counterparty", sa.String(length=200), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("cadence", sa.String(length=24), nullable=False),
        sa.Column("next_due_date", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "cash_account_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_name", sa.String(length=120), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("balance", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cash_account_snapshots_account_name"),
        "cash_account_snapshots",
        ["account_name"],
        unique=True,
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_email", sa.String(length=200), nullable=False),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_events_entity_id"), "audit_events", ["entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_audit_events_entity_type"), "audit_events", ["entity_type"], unique=False
    )
    op.create_index(
        op.f("ix_audit_events_event_type"), "audit_events", ["event_type"], unique=False
    )
    op.create_index(
        op.f("ix_audit_events_sequence_no"), "audit_events", ["sequence_no"], unique=True
    )

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("po_number", sa.String(length=64), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("line_items_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_purchase_orders_po_number"), "purchase_orders", ["po_number"], unique=True
    )
    op.create_index(
        op.f("ix_purchase_orders_vendor_id"), "purchase_orders", ["vendor_id"], unique=False
    )

    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("receipt_number", sa.String(length=64), nullable=False),
        sa.Column("po_id", sa.String(length=36), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("line_items_json", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["po_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_goods_receipts_po_id"), "goods_receipts", ["po_id"], unique=False)
    op.create_index(
        op.f("ix_goods_receipts_receipt_number"),
        "goods_receipts",
        ["receipt_number"],
        unique=True,
    )
    op.create_index(
        op.f("ix_goods_receipts_vendor_id"), "goods_receipts", ["vendor_id"], unique=False
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("invoice_number", sa.String(length=80), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), nullable=True),
        sa.Column("counterparty_name", sa.String(length=200), nullable=False),
        sa.Column("po_number", sa.String(length=64), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_document_id", sa.String(length=36), nullable=True),
        sa.Column("line_items_json", sa.JSON(), nullable=False),
        sa.Column("match_status", sa.String(length=32), nullable=False),
        sa.Column("payment_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_document_id"], ["ingested_documents.id"]),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_invoices_content_sha256"), "invoices", ["content_sha256"], unique=False
    )
    op.create_index(
        op.f("ix_invoices_counterparty_name"), "invoices", ["counterparty_name"], unique=False
    )
    op.create_index(op.f("ix_invoices_due_date"), "invoices", ["due_date"], unique=False)
    op.create_index(
        op.f("ix_invoices_invoice_number"), "invoices", ["invoice_number"], unique=False
    )
    op.create_index(op.f("ix_invoices_match_status"), "invoices", ["match_status"], unique=False)
    op.create_index(
        op.f("ix_invoices_payment_status"), "invoices", ["payment_status"], unique=False
    )
    op.create_index(op.f("ix_invoices_po_number"), "invoices", ["po_number"], unique=False)
    op.create_index(op.f("ix_invoices_vendor_id"), "invoices", ["vendor_id"], unique=False)

    op.create_table(
        "three_way_matches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("po_id", sa.String(length=36), nullable=True),
        sa.Column("receipt_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("price_variance", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("price_variance_pct", sa.Float(), nullable=False),
        sa.Column("qty_variance", sa.Float(), nullable=False),
        sa.Column("anomalies_json", sa.JSON(), nullable=False),
        sa.Column("ai_explanation", sa.Text(), nullable=False),
        sa.Column("llm_provider_used", sa.String(length=32), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["approval_requests.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.ForeignKeyConstraint(["po_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["receipt_id"], ["goods_receipts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_three_way_matches_invoice_id"), "three_way_matches", ["invoice_id"], unique=False
    )
    op.create_index(
        op.f("ix_three_way_matches_status"), "three_way_matches", ["status"], unique=False
    )

    op.create_table(
        "payment_allocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("bank_transaction_id", sa.String(length=36), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("match_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["approval_requests.id"]),
        sa.ForeignKeyConstraint(["bank_transaction_id"], ["bank_transactions.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payment_allocations_bank_transaction_id"),
        "payment_allocations",
        ["bank_transaction_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payment_allocations_invoice_id"),
        "payment_allocations",
        ["invoice_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payment_allocations_status"), "payment_allocations", ["status"], unique=False
    )

    op.create_table(
        "expenses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("employee_name", sa.String(length=160), nullable=False),
        sa.Column("employee_email", sa.String(length=200), nullable=False),
        sa.Column("department", sa.String(length=80), nullable=False),
        sa.Column("merchant", sa.String(length=200), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("tax_category", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("receipt_hash", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("policy_violations_json", sa.JSON(), nullable=False),
        sa.Column("ai_audit_note", sa.Text(), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["approval_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_expenses_employee_email"), "expenses", ["employee_email"], unique=False
    )
    op.create_index(
        op.f("ix_expenses_expense_date"), "expenses", ["expense_date"], unique=False
    )
    op.create_index(op.f("ix_expenses_receipt_hash"), "expenses", ["receipt_hash"], unique=False)
    op.create_index(op.f("ix_expenses_status"), "expenses", ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("expenses")
    op.drop_table("payment_allocations")
    op.drop_table("three_way_matches")
    op.drop_table("invoices")
    op.drop_table("goods_receipts")
    op.drop_table("purchase_orders")
    op.drop_table("audit_events")
    op.drop_table("cash_account_snapshots")
    op.drop_table("recurring_commitments")
    op.drop_table("bank_transactions")
    op.drop_table("approval_requests")
    op.drop_table("ingested_documents")
    op.drop_table("vendors")
