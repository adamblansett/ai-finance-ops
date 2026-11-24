from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DocType = Literal["invoice", "purchase_order", "goods_receipt", "bank_statement", "expense"]


class IngestedDocumentOut(BaseModel):
    id: str
    filename: str
    doc_type: str
    content_type: str
    content_sha256: str
    raw_size_bytes: int
    parsed_records_count: int
    duplicate_of_id: str | None
    status: str
    summary: dict[str, Any]
    uploaded_by: str
    created_at: datetime


class IngestionPayloadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    doc_type: DocType
    format: Literal["json", "csv"] = "json"
    content: str | list[dict[str, Any]] | dict[str, Any]
    auto_reconcile: bool = True


class IngestionResultOut(BaseModel):
    document: IngestedDocumentOut
    created_ids: list[str]
    reconciled_match_ids: list[str]
    message: str
