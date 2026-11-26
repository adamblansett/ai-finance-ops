from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

JobType = Literal["reconcile_batch", "ap_ar_match", "forecast_snapshot"]


class BackgroundJobOut(BaseModel):
    id: str
    job_type: str
    status: str
    progress_pct: int
    payload: dict[str, Any]
    result: dict[str, Any]
    error_message: str | None
    created_by: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
