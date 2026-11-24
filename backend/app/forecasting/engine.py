from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import quantize_money, utcnow
from app.db.models import CashAccountSnapshot, Invoice, RecurringCommitment
from app.forecasting.schemas import (
    ArAgingSummaryOut,
    ForecastResponseOut,
    ForecastScenarioRequest,
    ForecastVarianceOut,
    WeeklyCashBucketOut,
)
from app.llm.router import LLMRouter

_CADENCE_DAYS: dict[str, int] = {
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
    "quarterly": 90,
}


def compute_13_week_projection(
    *,
    as_of: date,
    accounts: list[CashAccountSnapshot],
    invoices: list[Invoice],
    commitments: list[RecurringCommitment],
    scenario: ForecastScenarioRequest,
) -> tuple[list[WeeklyCashBucketOut], ArAgingSummaryOut, dict[str, Any]]:
    """Compute exact 13-week weekly cash buckets, AR aging, and liquidity KPIs."""
    starting_cash = quantize_money(sum((a.balance for a in accounts), Decimal("0.00")))

    ar_buckets = [Decimal("0.00") for _ in range(13)]
    rec_in_buckets = [Decimal("0.00") for _ in range(13)]
    ap_buckets = [Decimal("0.00") for _ in range(13)]
    rec_out_buckets = [Decimal("0.00") for _ in range(13)]

    aging_current = Decimal("0.00")
    aging_1_30 = Decimal("0.00")
    aging_31_60 = Decimal("0.00")
    aging_61_90 = Decimal("0.00")
    aging_90_plus = Decimal("0.00")

    ar_rate = Decimal(str(scenario.ar_collection_rate_pct)) / Decimal("100")
    rev_mult = Decimal("1") + (Decimal(str(scenario.revenue_growth_pct)) / Decimal("100"))
    exp_mult = Decimal("1") + (Decimal(str(scenario.expense_shock_pct)) / Decimal("100"))

    for inv in invoices:
        if inv.match_status == "rejected":
            continue
        remaining = quantize_money(inv.total_amount - inv.amount_paid)
        if remaining <= Decimal("0.00"):
            continue

        if inv.direction == "receivable":
            past_due = (as_of - inv.due_date).days
            if past_due <= 0:
                aging_current += remaining
            elif past_due <= 30:
                aging_1_30 += remaining
            elif past_due <= 60:
                aging_31_60 += remaining
            elif past_due <= 90:
                aging_61_90 += remaining
            else:
                aging_90_plus += remaining

            expected_dt = inv.due_date + timedelta(days=scenario.ar_delay_days)
            idx = 0 if expected_dt < as_of else (expected_dt - as_of).days // 7
            if 0 <= idx < 13:
                ar_buckets[idx] += quantize_money(remaining * ar_rate)

        elif inv.direction == "payable":
            expected_dt = inv.due_date + timedelta(days=scenario.ap_deferral_days)
            idx = 0 if expected_dt < as_of else (expected_dt - as_of).days // 7
            if 0 <= idx < 13:
                ap_buckets[idx] += remaining

    window_end = as_of + timedelta(days=13 * 7 - 1)
    for item in commitments:
        if not item.active:
            continue
        step_days = _CADENCE_DAYS.get(item.cadence, 30)
        occ = item.next_due_date
        while occ < as_of:
            occ += timedelta(days=step_days)
        while occ <= window_end:
            idx = (occ - as_of).days // 7
            if 0 <= idx < 13:
                if item.direction == "inflow":
                    rec_in_buckets[idx] += quantize_money(item.amount * rev_mult)
                else:
                    rec_out_buckets[idx] += quantize_money(item.amount * exp_mult)
            occ += timedelta(days=step_days)

    weeks: list[WeeklyCashBucketOut] = []
    running = starting_cash
    lowest_balance = starting_cash
    lowest_week = 1
    buffer_breach_week: int | None = None
    buffer_dec = quantize_money(scenario.min_cash_buffer)
    total_inflows = Decimal("0.00")
    total_outflows = Decimal("0.00")

    for i in range(13):
        wk_start = as_of + timedelta(days=7 * i)
        wk_end = wk_start + timedelta(days=6)
        opening = running
        ar_in = quantize_money(ar_buckets[i])
        rec_in = quantize_money(rec_in_buckets[i])
        ap_out = quantize_money(ap_buckets[i])
        rec_out = quantize_money(rec_out_buckets[i])
        net = quantize_money((ar_in + rec_in) - (ap_out + rec_out))
        closing = quantize_money(opening + net)

        total_inflows += ar_in + rec_in
        total_outflows += ap_out + rec_out

        if i == 0 or closing < lowest_balance:
            lowest_balance = closing
            lowest_week = i + 1
        if buffer_breach_week is None and closing < buffer_dec:
            buffer_breach_week = i + 1

        weeks.append(
            WeeklyCashBucketOut(
                week_number=i + 1,
                week_start=wk_start,
                week_end=wk_end,
                opening_cash=float(opening),
                ar_inflows=float(ar_in),
                recurring_inflows=float(rec_in),
                ap_outflows=float(ap_out),
                recurring_outflows=float(rec_out),
                net_cash_flow=float(net),
                closing_cash=float(closing),
            )
        )
        running = closing

    avg_net = quantize_money((total_inflows - total_outflows) / Decimal("13"))
    runway_weeks: float | None = None
    if avg_net < Decimal("0.00") and starting_cash > Decimal("0.00"):
        runway_weeks = round(float(starting_cash / abs(avg_net)), 1)
    elif avg_net < Decimal("0.00") and starting_cash <= Decimal("0.00"):
        runway_weeks = 0.0

    total_open_ar = quantize_money(
        aging_current + aging_1_30 + aging_31_60 + aging_61_90 + aging_90_plus
    )
    aging = ArAgingSummaryOut(
        current=float(aging_current),
        days_1_30=float(aging_1_30),
        days_31_60=float(aging_31_60),
        days_61_90=float(aging_61_90),
        days_90_plus=float(aging_90_plus),
        total_open_ar=float(total_open_ar),
    )
    summary = {
        "starting_cash": float(starting_cash),
        "ending_cash_week_13": float(running),
        "lowest_cash_balance": float(lowest_balance),
        "lowest_cash_week": lowest_week,
        "total_inflows_13w": float(quantize_money(total_inflows)),
        "total_outflows_13w": float(quantize_money(total_outflows)),
        "average_weekly_net_flow": float(avg_net),
        "estimated_runway_weeks": runway_weeks,
        "buffer_breach_week": buffer_breach_week,
    }
    return weeks, aging, summary


async def build_13_week_forecast(
    db: AsyncSession,
    *,
    llm_router: LLMRouter,
    scenario: ForecastScenarioRequest,
) -> ForecastResponseOut:
    """Compute baseline + scenario 13-week cash forecast and generate AI variance narrative."""
    as_of = utcnow().date()
    accounts = list((await db.execute(select(CashAccountSnapshot))).scalars().all())
    invoices = list((await db.execute(select(Invoice))).scalars().all())
    commitments = list((await db.execute(select(RecurringCommitment))).scalars().all())

    baseline_req = ForecastScenarioRequest(min_cash_buffer=scenario.min_cash_buffer)
    _, _, base_sum = compute_13_week_projection(
        as_of=as_of,
        accounts=accounts,
        invoices=invoices,
        commitments=commitments,
        scenario=baseline_req,
    )
    weeks, aging, scen_sum = compute_13_week_projection(
        as_of=as_of,
        accounts=accounts,
        invoices=invoices,
        commitments=commitments,
        scenario=scenario,
    )

    variance = ForecastVarianceOut(
        ending_cash_delta=round(
            scen_sum["ending_cash_week_13"] - base_sum["ending_cash_week_13"], 2
        ),
        lowest_cash_delta=round(
            scen_sum["lowest_cash_balance"] - base_sum["lowest_cash_balance"], 2
        ),
        inflow_delta=round(
            scen_sum["total_inflows_13w"] - base_sum["total_inflows_13w"], 2
        ),
        outflow_delta=round(
            scen_sum["total_outflows_13w"] - base_sum["total_outflows_13w"], 2
        ),
    )

    breach_note = (
        f"breaches ${scenario.min_cash_buffer:,.0f} buffer in week {scen_sum['buffer_breach_week']}"
        if scen_sum["buffer_breach_week"]
        else f"stays above ${scenario.min_cash_buffer:,.0f} buffer"
    )
    llm_res = await llm_router.generate(
        prompt=(
            f"Starting cash ${scen_sum['starting_cash']:,.2f}, Week-13 ending cash "
            f"${scen_sum['ending_cash_week_13']:,.2f} (delta {variance.ending_cash_delta:+,.2f} vs "
            f"baseline), lowest cash ${scen_sum['lowest_cash_balance']:,.2f} in Week "
            f"{scen_sum['lowest_cash_week']}; {breach_note}. Open AR=${aging.total_open_ar:,.2f}."
        ),
        system_prompt="Provide an executive 13-week cash flow and variance commentary.",
        task_type="cashflow_variance",
    )

    return ForecastResponseOut(
        as_of_date=as_of,
        starting_cash=scen_sum["starting_cash"],
        ending_cash_week_13=scen_sum["ending_cash_week_13"],
        lowest_cash_balance=scen_sum["lowest_cash_balance"],
        lowest_cash_week=scen_sum["lowest_cash_week"],
        total_inflows_13w=scen_sum["total_inflows_13w"],
        total_outflows_13w=scen_sum["total_outflows_13w"],
        average_weekly_net_flow=scen_sum["average_weekly_net_flow"],
        estimated_runway_weeks=scen_sum["estimated_runway_weeks"],
        buffer_breach_week=scen_sum["buffer_breach_week"],
        scenario=scenario,
        variance_vs_baseline=variance,
        ar_aging=aging,
        weeks=weeks,
        ai_narrative=llm_res.content,
        llm_provider_used=llm_res.provider,
    )
