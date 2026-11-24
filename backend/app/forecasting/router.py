from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor, get_current_actor, require_roles
from app.db.base import quantize_money, utcnow
from app.db.models import CashAccountSnapshot, RecurringCommitment
from app.db.session import get_db
from app.forecasting.engine import build_13_week_forecast
from app.forecasting.schemas import (
    CashAccountOut,
    CashAccountUpdate,
    ForecastResponseOut,
    ForecastScenarioRequest,
    RecurringCommitmentCreate,
    RecurringCommitmentOut,
)
from app.llm.router import LLMRouter, get_llm_router

router = APIRouter(prefix="/forecasting", tags=["forecasting"])


@router.get("/cashflow", response_model=ForecastResponseOut)
async def get_baseline_cashflow(
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    _: Actor = Depends(get_current_actor),
) -> ForecastResponseOut:
    """Return baseline rolling 13-week cash flow forecast and AR aging."""
    return await build_13_week_forecast(
        db,
        llm_router=llm_router,
        scenario=ForecastScenarioRequest(),
    )


@router.post("/cashflow/scenario", response_model=ForecastResponseOut)
async def run_cashflow_scenario(
    scenario: ForecastScenarioRequest,
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
    _: Actor = Depends(get_current_actor),
) -> ForecastResponseOut:
    """Model a custom 13-week cash flow sensitivity scenario against baseline."""
    return await build_13_week_forecast(db, llm_router=llm_router, scenario=scenario)


@router.get("/commitments", response_model=list[RecurringCommitmentOut])
async def list_commitments(
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[RecurringCommitmentOut]:
    rows = (
        await db.execute(
            select(RecurringCommitment).order_by(RecurringCommitment.next_due_date.asc())
        )
    ).scalars().all()
    return [
        RecurringCommitmentOut(
            id=r.id,
            name=r.name,
            counterparty=r.counterparty,
            direction=r.direction,
            category=r.category,
            amount=float(r.amount),
            cadence=r.cadence,
            next_due_date=r.next_due_date,
            active=r.active,
        )
        for r in rows
    ]


@router.post(
    "/commitments",
    response_model=RecurringCommitmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_commitment(
    payload: RecurringCommitmentCreate,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_roles("analyst", "controller", "admin")),
) -> RecurringCommitmentOut:
    row = RecurringCommitment(
        name=payload.name.strip(),
        counterparty=payload.counterparty.strip(),
        direction=payload.direction,
        category=payload.category.strip().lower(),
        amount=quantize_money(payload.amount),
        cadence=payload.cadence,
        next_due_date=payload.next_due_date,
        active=payload.active,
    )
    db.add(row)
    await db.flush()
    await record_audit_event(
        db,
        event_type="forecasting.commitment_created",
        actor=actor,
        entity_type="recurring_commitment",
        entity_id=row.id,
        action="created",
        details={"name": row.name, "amount": float(row.amount), "cadence": row.cadence},
    )
    await db.commit()
    await db.refresh(row)
    return RecurringCommitmentOut(
        id=row.id,
        name=row.name,
        counterparty=row.counterparty,
        direction=row.direction,
        category=row.category,
        amount=float(row.amount),
        cadence=row.cadence,
        next_due_date=row.next_due_date,
        active=row.active,
    )


@router.get("/accounts", response_model=list[CashAccountOut])
async def list_cash_accounts(
    db: AsyncSession = Depends(get_db),
    _: Actor = Depends(get_current_actor),
) -> list[CashAccountOut]:
    rows = (
        await db.execute(
            select(CashAccountSnapshot).order_by(CashAccountSnapshot.account_name.asc())
        )
    ).scalars().all()
    return [
        CashAccountOut(
            id=r.id,
            account_name=r.account_name,
            as_of_date=r.as_of_date,
            balance=float(r.balance),
            currency=r.currency,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.put("/accounts", response_model=CashAccountOut)
async def upsert_cash_account(
    payload: CashAccountUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_roles("controller", "admin")),
) -> CashAccountOut:
    name = payload.account_name.strip()
    existing = (
        await db.execute(
            select(CashAccountSnapshot).where(CashAccountSnapshot.account_name == name)
        )
    ).scalar_one_or_none()
    as_of = payload.as_of_date or utcnow().date()
    bal = quantize_money(payload.balance)
    if existing is None:
        existing = CashAccountSnapshot(
            account_name=name,
            as_of_date=as_of,
            balance=bal,
            currency=payload.currency.upper(),
        )
        db.add(existing)
        await db.flush()
    else:
        existing.as_of_date = as_of
        existing.balance = bal
        existing.currency = payload.currency.upper()

    await record_audit_event(
        db,
        event_type="forecasting.account_updated",
        actor=actor,
        entity_type="cash_account",
        entity_id=existing.id,
        action="upserted",
        details={"account_name": name, "balance": float(bal)},
    )
    await db.commit()
    await db.refresh(existing)
    return CashAccountOut(
        id=existing.id,
        account_name=existing.account_name,
        as_of_date=existing.as_of_date,
        balance=float(existing.balance),
        currency=existing.currency,
        updated_at=existing.updated_at,
    )
