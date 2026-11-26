from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel


class VendorOut(BaseModel):
    id: str
    code: str
    name: str
    tax_id: str | None
    payment_terms_days: int
    default_gl_account: str
    status: str


class PurchaseOrderOut(BaseModel):
    id: str
    po_number: str
    vendor_id: str
    vendor_name: str | None = None
    issue_date: date
    expected_delivery_date: date | None
    currency: str
    total_amount: float
    status: str
    line_items: list[dict[str, Any]]


class GoodsReceiptOut(BaseModel):
    id: str
    receipt_number: str
    po_id: str
    vendor_id: str
    received_date: date
    total_amount: float
    line_items: list[dict[str, Any]]
    notes: str | None


class InvoiceOut(BaseModel):
    id: str
    invoice_number: str
    direction: str
    vendor_id: str | None
    counterparty_name: str
    po_number: str | None
    issue_date: date
    due_date: date
    currency: str
    subtotal: float
    tax_amount: float
    total_amount: float
    amount_paid: float
    match_status: str
    payment_status: str
    gl_account: str | None = None
    line_items: list[dict[str, Any]]
    created_at: datetime


class MatchAnomalyOut(BaseModel):
    code: str
    severity: Literal["low", "medium", "high"]
    message: str


class ThreeWayMatchOut(BaseModel):
    id: str
    invoice_id: str
    invoice_number: str | None = None
    counterparty_name: str | None = None
    invoice_total: float | None = None
    po_id: str | None
    po_number: str | None = None
    po_total: float | None = None
    receipt_id: str | None
    receipt_number: str | None = None
    status: str
    confidence_score: float
    price_variance: float
    price_variance_pct: float
    qty_variance: float
    anomalies: list[MatchAnomalyOut]
    ai_explanation: str
    llm_provider_used: str
    approval_id: str | None
    updated_at: datetime


class BatchMatchSummaryOut(BaseModel):
    processed_count: int
    matched_count: int
    flagged_count: int
    matches: list[ThreeWayMatchOut]


class BankTransactionOut(BaseModel):
    id: str
    external_ref: str
    transaction_date: date
    description: str
    normalized_counterparty: str
    direction: str
    amount: float
    currency: str
    account_name: str
    status: str


class PaymentAllocationOut(BaseModel):
    id: str
    bank_transaction_id: str
    bank_ref: str | None = None
    bank_description: str | None = None
    invoice_id: str
    invoice_number: str | None = None
    counterparty_name: str | None = None
    allocated_amount: float
    confidence_score: float
    match_reason: str
    status: str
    approval_id: str | None
    created_at: datetime


class BatchAllocationSummaryOut(BaseModel):
    proposed_count: int
    allocations: list[PaymentAllocationOut]


class GLSuggestRequest(BaseModel):
    vendor_name: str = ""
    description: str
    default_gl: str | None = None


class SemanticSearchRequest(BaseModel):
    query: str
    entity_type: Literal["invoice", "purchase_order"] = "invoice"
    top_k: int = 5


class SemanticSearchHitOut(BaseModel):
    entity_type: str
    entity_id: str
    score: float
    source_text: str
