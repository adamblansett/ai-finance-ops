from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.schemas import ExpenseCreate
from app.audit.service import create_approval_request, record_audit_event
from app.core.auth import Actor
from app.core.config import Settings
from app.db.base import quantize_money
from app.db.models import ApprovalRequest, Expense
from app.llm.router import LLMRouter

CATEGORY_CAPS: dict[str, Decimal] = {
    "meals": Decimal("150.00"),
    "travel": Decimal("2500.00"),
    "client_entertainment": Decimal("500.00"),
    "software": Decimal("1000.00"),
    "hardware": Decimal("3000.00"),
    "office_supplies": Decimal("500.00"),
    "professional_services": Decimal("5000.00"),
    "other": Decimal("500.00"),
}


def expected_tax_category(category: str, amount: Decimal) -> str:
    """Return expected IRS/GAAP tax classification for a given expense category and amount."""
    normalized = category.strip().lower()
    if normalized == "client_entertainment":
        return "non_deductible"
    if normalized == "meals":
        return "deductible_50"
    if normalized == "hardware" and amount >= Decimal("2500.00"):
        return "capitalizable"
    return "deductible_100"


def evaluate_expense_rules(
    *,
    category: str,
    tax_category: str,
    amount: Decimal,
    expense_date: date,
    receipt_hash: str | None,
    duplicate_expense_id: str | None,
    settings: Settings,
) -> tuple[list[dict[str, Any]], str, str]:
    """Evaluate expense policy rules and return (violations, status, risk_level)."""
    violations: list[dict[str, Any]] = []
    norm_cat = category.strip().lower()
    norm_tax = tax_category.strip().lower()

    if duplicate_expense_id is not None:
        violations.append(
            {
                "rule_code": "DUPLICATE_RECEIPT",
                "severity": "high",
                "message": (
                    f"Receipt hash matches existing expense '{duplicate_expense_id[:8]}...'."
                ),
            }
        )

    if amount > Decimal("75.00") and not (receipt_hash and receipt_hash.strip()):
        violations.append(
            {
                "rule_code": "MISSING_RECEIPT_OVER_THRESHOLD",
                "severity": "medium",
                "message": (
                    f"Amount ${amount:.2f} exceeds $75.00 threshold and lacks a receipt hash."
                ),
            }
        )

    cap = CATEGORY_CAPS.get(norm_cat, Decimal("500.00"))
    if amount > cap:
        severity = "high" if amount > cap * Decimal("1.5") else "medium"
        violations.append(
            {
                "rule_code": "CATEGORY_CAP_EXCEEDED",
                "severity": severity,
                "message": (
                    f"{norm_cat} spend ${amount:.2f} exceeds policy cap of ${cap:.2f}."
                ),
            }
        )

    expected_tax = expected_tax_category(norm_cat, amount)
    if norm_tax != expected_tax:
        violations.append(
            {
                "rule_code": "TAX_CATEGORY_MISMATCH",
                "severity": "medium",
                "message": (
                    f"Tax category '{norm_tax}' mismatches expected '{expected_tax}' "
                    f"for {norm_cat} (${amount:.2f})."
                ),
            }
        )

    if expense_date.weekday() >= 5 and norm_cat not in {"travel", "client_entertainment"}:
        violations.append(
            {
                "rule_code": "WEEKEND_NON_TRAVEL",
                "severity": "low",
                "message": f"Non-travel expense posted on weekend ({expense_date.isoformat()}).",
            }
        )

    auto_limit = quantize_money(settings.expense_auto_approve_limit)
    has_policy_violation = len(violations) > 0
    if amount > auto_limit:
        violations.append(
            {
                "rule_code": "HIGH_VALUE_APPROVAL_REQUIRED",
                "severity": "medium",
                "message": (
                    f"Amount ${amount:.2f} exceeds auto-approval limit of ${auto_limit:.2f}."
                ),
            }
        )

    if has_policy_violation:
        status = "flagged"
    elif amount > auto_limit:
        status = "pending_review"
    else:
        status = "auto_approved"

    severities = {v["severity"] for v in violations}
    if "high" in severities:
        risk_level = "high"
    elif "medium" in severities:
        risk_level = "medium"
    else:
        risk_level = "low"

    return violations, status, risk_level


async def audit_and_persist_expense(
    db: AsyncSession,
    *,
    payload: ExpenseCreate,
    llm_router: LLMRouter,
    settings: Settings,
    actor: Actor,
) -> Expense:
    """Validate an expense against policy rules, generate AI note, and persist."""
    amount_dec = quantize_money(payload.amount)
    receipt_clean = payload.receipt_hash.strip() if payload.receipt_hash else None

    duplicate_id: str | None = None
    if receipt_clean:
        dup_stmt = (
            select(Expense.id)
            .where(Expense.receipt_hash == receipt_clean)
            .order_by(Expense.created_at.asc())
            .limit(1)
        )
        duplicate_id = (await db.execute(dup_stmt)).scalar_one_or_none()

    violations, exp_status, risk_level = evaluate_expense_rules(
        category=payload.category,
        tax_category=payload.tax_category,
        amount=amount_dec,
        expense_date=payload.expense_date,
        receipt_hash=receipt_clean,
        duplicate_expense_id=duplicate_id,
        settings=settings,
    )

    if exp_status == "auto_approved":
        ai_note = (
            "Auto-approved: passes receipt validation, category policy cap, and tax-category rules."
        )
    else:
        codes = ", ".join(v["rule_code"] for v in violations) or "MANUAL_REVIEW"
        llm_res = await llm_router.generate(
            prompt=(
                f"Employee {payload.employee_name} ({payload.department}) submitted "
                f"${amount_dec:.2f} at {payload.merchant} in category '{payload.category}' "
                f"(tax '{payload.tax_category}'). Rules triggered: {codes}."
            ),
            system_prompt="Provide a concise corporate expense audit summary.",
            task_type="expense_audit",
        )
        ai_note = llm_res.content

    expense = Expense(
        employee_name=payload.employee_name.strip(),
        employee_email=payload.employee_email.strip(),
        department=payload.department.strip(),
        merchant=payload.merchant.strip(),
        expense_date=payload.expense_date,
        category=payload.category.strip().lower(),
        tax_category=payload.tax_category.strip().lower(),
        amount=amount_dec,
        currency=payload.currency.strip().upper(),
        receipt_hash=receipt_clean,
        description=payload.description.strip(),
        status=exp_status,
        policy_violations_json=violations,
        ai_audit_note=ai_note,
    )
    db.add(expense)
    await db.flush()

    if exp_status != "auto_approved":
        codes = ", ".join(v["rule_code"] for v in violations)
        approval = await create_approval_request(
            db,
            entity_type="expense",
            entity_id=expense.id,
            action_requested="approve_expense",
            summary=(
                f"{expense.merchant} — {expense.employee_name} (${amount_dec:.2f}): "
                f"{codes or 'Review required'}"
            ),
            amount=amount_dec,
            risk_level=risk_level,
            requested_by=actor.email,
        )
        expense.approval_id = approval.id

    await record_audit_event(
        db,
        event_type="expense.audited",
        actor=actor,
        entity_type="expense",
        entity_id=expense.id,
        action=exp_status,
        details={
            "merchant": expense.merchant,
            "amount": float(amount_dec),
            "violations": [v["rule_code"] for v in violations],
        },
    )
    return expense


async def reaudit_existing_expense(
    db: AsyncSession,
    *,
    expense: Expense,
    llm_router: LLMRouter,
    settings: Settings,
    actor: Actor,
) -> Expense:
    """Re-run policy rules on an existing expense record."""
    duplicate_id: str | None = None
    if expense.receipt_hash:
        dup_stmt = (
            select(Expense.id)
            .where(Expense.receipt_hash == expense.receipt_hash, Expense.id != expense.id)
            .order_by(Expense.created_at.asc())
            .limit(1)
        )
        duplicate_id = (await db.execute(dup_stmt)).scalar_one_or_none()

    violations, exp_status, risk_level = evaluate_expense_rules(
        category=expense.category,
        tax_category=expense.tax_category,
        amount=quantize_money(expense.amount),
        expense_date=expense.expense_date,
        receipt_hash=expense.receipt_hash,
        duplicate_expense_id=duplicate_id,
        settings=settings,
    )

    expense.policy_violations_json = violations
    if expense.status not in {"approved", "rejected"}:
        expense.status = exp_status

    codes = ", ".join(v["rule_code"] for v in violations) or "NONE"
    llm_res = await llm_router.generate(
        prompt=(
            f"Re-audit expense at {expense.merchant} (${expense.amount:.2f}, "
            f"{expense.category}/{expense.tax_category}). Violations: {codes}."
        ),
        system_prompt="Provide a concise corporate expense audit summary.",
        task_type="expense_audit",
    )
    expense.ai_audit_note = llm_res.content

    if expense.status not in {"auto_approved", "approved", "rejected"}:
        existing_approval = (
            await db.get(ApprovalRequest, expense.approval_id)
            if expense.approval_id
            else None
        )
        if existing_approval is None or existing_approval.status != "pending":
            approval = await create_approval_request(
                db,
                entity_type="expense",
                entity_id=expense.id,
                action_requested="approve_expense",
                summary=f"{expense.merchant} — {expense.employee_name} (${expense.amount:.2f})",
                amount=quantize_money(expense.amount),
                risk_level=risk_level,
                requested_by=actor.email,
            )
            expense.approval_id = approval.id

    await record_audit_event(
        db,
        event_type="expense.reaudited",
        actor=actor,
        entity_type="expense",
        entity_id=expense.id,
        action=expense.status,
        details={"violations": [v["rule_code"] for v in violations]},
    )
    return expense
