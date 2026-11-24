from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import CONTROLLER_HEADERS, make_test_app


@pytest.mark.asyncio
async def test_13_week_cashflow_math_and_scenario_sensitivity(tmp_path: Path) -> None:
    app = make_test_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/v1/seed/demo", headers=CONTROLLER_HEADERS)

        base_res = await client.get("/api/v1/forecasting/cashflow", headers=CONTROLLER_HEADERS)
        assert base_res.status_code == 200
        base = base_res.json()
        assert len(base["weeks"]) == 13
        assert base["starting_cash"] == 500000.0
        assert base["ar_aging"]["total_open_ar"] == 126500.0
        assert base["ar_aging"]["current"] == 84500.0
        assert base["ar_aging"]["days_1_30"] == 42000.0

        # Verify week-to-week roll-forward arithmetic
        for idx, wk in enumerate(base["weeks"]):
            inflows = wk["ar_inflows"] + wk["recurring_inflows"]
            outflows = wk["ap_outflows"] + wk["recurring_outflows"]
            assert round(inflows - outflows, 2) == wk["net_cash_flow"]
            assert round(wk["opening_cash"] + wk["net_cash_flow"], 2) == wk["closing_cash"]
            if idx > 0:
                assert wk["opening_cash"] == base["weeks"][idx - 1]["closing_cash"]

        # Stress scenario: lower AR collections + 30% expense shock -> lower ending cash
        stress_res = await client.post(
            "/api/v1/forecasting/cashflow/scenario",
            headers=CONTROLLER_HEADERS,
            json={
                "ar_collection_rate_pct": 60.0,
                "ar_delay_days": 14,
                "ap_deferral_days": 0,
                "revenue_growth_pct": -15.0,
                "expense_shock_pct": 30.0,
                "min_cash_buffer": 450000.0,
            },
        )
        assert stress_res.status_code == 200
        stress = stress_res.json()
        assert stress["ending_cash_week_13"] < base["ending_cash_week_13"]
        assert stress["variance_vs_baseline"]["ending_cash_delta"] < 0
        assert stress["buffer_breach_week"] is not None
