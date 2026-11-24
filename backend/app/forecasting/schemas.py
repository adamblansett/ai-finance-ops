from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ForecastScenarioRequest(BaseModel):
    ar_collection_rate_pct: float = Field(default=100.0, ge=0.0, le=125.0)
    ar_delay_days: int = Field(default=0, ge=-30, le=90)
    ap_deferral_days: int = Field(default=0, ge=-30, le=90)
    revenue_growth_pct: float = Field(default=0.0, ge=-80.0, le=200.0)
    expense_shock_pct: float = Field(default=0.0, ge=-50.0, le=200.0)
    min_cash_buffer: float = Field(default=100000.0, ge=0.0)


class WeeklyCashBucketOut(BaseModel):
    week_number: int
    week_start: date
    week_end: date
    opening_cash: float
    ar_inflows: float
    recurring_inflows: float
    ap_outflows: float
    recurring_outflows: float
    net_cash_flow: float
    closing_cash: float


class ArAgingSummaryOut(BaseModel):
    current: float
    days_1_30: float
    days_31_60: float
    days_61_90: float
    days_90_plus: float
    total_open_ar: float


class ForecastVarianceOut(BaseModel):
    ending_cash_delta: float
    lowest_cash_delta: float
    inflow_delta: float
    outflow_delta: float


class ForecastResponseOut(BaseModel):
    as_of_date: date
    starting_cash: float
    ending_cash_week_13: float
    lowest_cash_balance: float
    lowest_cash_week: int
    total_inflows_13w: float
    total_outflows_13w: float
    average_weekly_net_flow: float
    estimated_runway_weeks: float | None
    buffer_breach_week: int | None
    scenario: ForecastScenarioRequest
    variance_vs_baseline: ForecastVarianceOut
    ar_aging: ArAgingSummaryOut
    weeks: list[WeeklyCashBucketOut]
    ai_narrative: str
    llm_provider_used: str


class RecurringCommitmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    counterparty: str = Field(min_length=1, max_length=200)
    direction: Literal["inflow", "outflow"]
    category: str = Field(min_length=1, max_length=64)
    amount: float = Field(gt=0)
    cadence: Literal["weekly", "biweekly", "monthly", "quarterly"]
    next_due_date: date
    active: bool = True


class RecurringCommitmentOut(BaseModel):
    id: str
    name: str
    counterparty: str
    direction: str
    category: str
    amount: float
    cadence: str
    next_due_date: date
    active: bool


class CashAccountUpdate(BaseModel):
    account_name: str = Field(min_length=1, max_length=120)
    balance: float
    as_of_date: date | None = None
    currency: str = Field(default="USD", max_length=8)


class CashAccountOut(BaseModel):
    id: str
    account_name: str
    as_of_date: date
    balance: float
    currency: str
    updated_at: datetime
