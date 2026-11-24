from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.llm.pii import RedactionFinding


class PolicyViolationOut(BaseModel):
    rule_code: str
    severity: Literal["low", "medium", "high"]
    message: str


class ExpenseCreate(BaseModel):
    employee_name: str = Field(min_length=1, max_length=160)
    employee_email: str = Field(min_length=3, max_length=200)
    department: str = Field(default="Operations", max_length=80)
    merchant: str = Field(min_length=1, max_length=200)
    expense_date: date
    category: str = Field(min_length=1, max_length=64)
    tax_category: str = Field(min_length=1, max_length=64)
    amount: float = Field(gt=0)
    currency: str = Field(default="USD", max_length=8)
    receipt_hash: str | None = Field(default=None, max_length=64)
    description: str = ""


class ExpenseOut(BaseModel):
    id: str
    employee_name: str
    employee_email: str
    department: str
    merchant: str
    expense_date: date
    category: str
    tax_category: str
    amount: float
    currency: str
    receipt_hash: str | None
    description: str
    status: str
    policy_violations: list[PolicyViolationOut]
    ai_audit_note: str
    approval_id: str | None
    created_at: datetime


class ApprovalOut(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    action_requested: str
    summary: str
    amount: float
    risk_level: str
    status: str
    requested_by: str
    decided_by: str | None
    decision_notes: str | None
    created_at: datetime
    decided_at: datetime | None


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    notes: str = Field(default="", max_length=1000)


class AuditEventOut(BaseModel):
    id: str
    sequence_no: int
    event_type: str
    actor_email: str
    actor_role: str
    entity_type: str
    entity_id: str
    action: str
    details: dict[str, Any]
    prev_hash: str
    event_hash: str
    created_at: datetime


class AuditChainVerifyOut(BaseModel):
    valid: bool
    total_events: int
    head_hash: str
    broken_sequence_no: int | None = None
    message: str


class PiiRedactRequest(BaseModel):
    text: str


class PiiRedactResponse(BaseModel):
    redacted_text: str
    findings: list[RedactionFinding]
    total_redactions: int
