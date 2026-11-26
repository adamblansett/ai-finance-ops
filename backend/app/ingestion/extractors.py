import csv
import hashlib
import io
import json
import re
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from pypdf import PdfReader

from app.db.base import quantize_money, utcnow
from app.ingestion.schemas import DocType

_ERP_HEADER_ALIASES: dict[str, str] = {
    # QuickBooks / Xero / NetSuite invoice & bill headers
    "bill no": "invoice_number",
    "bill number": "invoice_number",
    "invoicenumber": "invoice_number",
    "invoice no": "invoice_number",
    "invoice #": "invoice_number",
    "supplier": "counterparty_name",
    "contactname": "counterparty_name",
    "vendor": "vendor_name",
    "customer": "counterparty_name",
    "po #": "po_number",
    "po no": "po_number",
    "purchase order": "po_number",
    "invoicedate": "issue_date",
    "bill date": "issue_date",
    "duedate": "due_date",
    "balance due": "total_amount",
    "total": "total_amount",
    "tax": "tax_amount",
    "memo": "description",
    "posting date": "transaction_date",
    "date": "transaction_date",
    "ref": "external_ref",
}


def sha256_bytes(data: bytes) -> str:
    """Compute hex SHA-256 digest for raw document bytes."""
    return hashlib.sha256(data).hexdigest()


def parse_money(value: Any, default: str = "0.00") -> Decimal:
    """Normalize currency-formatted values into 2-decimal Decimal amounts."""
    if value is None or value == "":
        return Decimal(default)
    if isinstance(value, Decimal):
        return quantize_money(value)
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    if not cleaned:
        return Decimal(default)
    return quantize_money(cleaned)


def parse_line_items(raw: Any, fallback_qty: Any = None) -> list[dict[str, Any]]:
    """Extract structured line-item arrays from JSON strings, lists, or qty columns."""
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                return [item for item in loaded if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
    if fallback_qty not in (None, ""):
        try:
            return [{"description": "Line item", "qty": float(fallback_qty)}]
        except (TypeError, ValueError):
            pass
    return []


def _normalize_erp_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_key, raw_val in row.items():
        if raw_key is None:
            continue
        key_clean = raw_key.strip()
        if not key_clean:
            continue
        mapped = _ERP_HEADER_ALIASES.get(key_clean.lower(), key_clean)
        val = raw_val.strip() if isinstance(raw_val, str) else raw_val
        normalized.setdefault(mapped, val)

    # Support separate Debit / Credit columns in bank/ERP CSVs
    if "amount" not in normalized and ("Debit" in row or "Credit" in row):
        debit = parse_money(row.get("Debit"), "0.00")
        credit = parse_money(row.get("Credit"), "0.00")
        if debit > Decimal("0.00"):
            normalized["amount"] = str(debit)
            normalized.setdefault("direction", "outflow")
        elif credit > Decimal("0.00"):
            normalized["amount"] = str(credit)
            normalized.setdefault("direction", "inflow")

    return normalized


def parse_csv_records(content: bytes) -> list[dict[str, Any]]:
    """Parse UTF-8 CSV bytes (including QBO/Xero/NetSuite column aliases) into dicts."""
    text = content.decode("utf-8-sig", errors="replace").strip()
    if not text:
        return []
    reader = csv.DictReader(io.StringIO(text))
    records: list[dict[str, Any]] = []
    for row in reader:
        cleaned = _normalize_erp_row(row)
        if any(v not in (None, "") for v in cleaned.values()):
            records.append(cleaned)
    return records


def parse_json_records(content: bytes) -> list[dict[str, Any]]:
    """Parse JSON bytes (object, array, or {'records': [...]}) into record dicts."""
    loaded = json.loads(content.decode("utf-8-sig"))
    if isinstance(loaded, list):
        return [r for r in loaded if isinstance(r, dict)]
    if isinstance(loaded, dict):
        if isinstance(loaded.get("records"), list):
            return [r for r in loaded["records"] if isinstance(r, dict)]
        return [loaded]
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="JSON payload must be an object, array of objects, or {'records': [...]}.",
    )


def parse_pdf_invoice(content: bytes, filename: str) -> list[dict[str, Any]]:
    """Extract structured invoice fields from PDF text using pypdf."""
    try:
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse PDF '{filename}': {exc}",
        ) from exc

    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"PDF '{filename}' contained no extractable text.",
        )

    def _find(pattern: str) -> str | None:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else None

    inv_num = _find(r"(?:Invoice\s*(?:Number|No|#)\s*[:#]?\s*)([A-Z0-9-]+)")
    if not inv_num:
        inv_num = f"PDF-{sha256_bytes(content)[:8].upper()}"
    po_num = _find(r"(?:PO\s*(?:Number|No|#)\s*[:#]?\s*)([A-Z0-9-]+)")
    vendor = _find(r"(?:Vendor|From|Supplier)\s*[:\-]\s*([^\n]+)") or "PDF Imported Vendor"
    issue_date = _find(r"(?:Issue\s*Date|Invoice\s*Date|Date)\s*[:\-]\s*(\d{4}-\d{2}-\d{2})")
    due_date = _find(r"(?:Due\s*Date)\s*[:\-]\s*(\d{4}-\d{2}-\d{2})")
    subtotal_raw = _find(r"(?:Subtotal)\s*[:\-]?\s*\$?([\d,]+\.\d{2})")
    tax_raw = _find(r"(?:Tax)\s*[:\-]?\s*\$?([\d,]+\.\d{2})")
    total_raw = _find(r"(?:Total\s*(?:Due|Amount)?)\s*[:\-]?\s*\$?([\d,]+\.\d{2})")
    qty_raw = _find(r"(?:Qty|Quantity)\s*[:\-]?\s*(\d+(?:\.\d+)?)")

    total = parse_money(total_raw or subtotal_raw, "0.00")
    subtotal = parse_money(subtotal_raw, str(total))
    tax = parse_money(tax_raw, "0.00")
    if total == Decimal("0.00") and subtotal > Decimal("0.00"):
        total = subtotal + tax

    record: dict[str, Any] = {
        "invoice_number": inv_num,
        "direction": "payable",
        "counterparty_name": vendor,
        "po_number": po_num,
        "issue_date": issue_date or utcnow().date().isoformat(),
        "due_date": due_date,
        "subtotal": str(subtotal),
        "tax_amount": str(tax),
        "total_amount": str(total),
    }
    if qty_raw:
        record["line_items"] = [{"description": f"Imported from {filename}", "qty": float(qty_raw)}]
    return [record]


def parse_ofx_bank_statement(content: bytes) -> list[dict[str, Any]]:
    """Parse SGML or XML OFX/QFX bank statement <STMTTRN> records."""
    text = content.decode("utf-8-sig", errors="replace")
    blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.IGNORECASE | re.DOTALL)
    if not blocks:
        # Handle SGML OFX blocks without closing </STMTTRN>
        parts = re.split(r"<STMTTRN>", text, flags=re.IGNORECASE)[1:]
        blocks = [p.split("</BANKTRANLIST>")[0] for p in parts]

    def _tag(block: str, name: str) -> str | None:
        m = re.search(rf"<{name}>\s*([^\r\n<]+)", block, re.IGNORECASE)
        return m.group(1).strip() if m else None

    records: list[dict[str, Any]] = []
    for block in blocks:
        amt_raw = _tag(block, "TRNAMT")
        if not amt_raw:
            continue
        try:
            signed_amt = Decimal(amt_raw)
        except Exception:
            continue
        trn_type = (_tag(block, "TRNTYPE") or "").upper()
        direction = (
            "inflow"
            if (signed_amt > 0 or trn_type in {"CREDIT", "DEP", "INT", "DIRECTDEP"})
            and signed_amt >= 0
            else "outflow"
        )
        dt_raw = _tag(block, "DTPOSTED") or ""
        iso_date = (
            f"{dt_raw[:4]}-{dt_raw[4:6]}-{dt_raw[6:8]}"
            if len(dt_raw) >= 8 and dt_raw[:8].isdigit()
            else utcnow().date().isoformat()
        )
        name = _tag(block, "NAME") or ""
        memo = _tag(block, "MEMO") or ""
        description = f"{name} {memo}".strip() or "OFX Bank Transaction"
        fitid = _tag(block, "FITID")
        records.append(
            {
                "external_ref": fitid or "",
                "transaction_date": iso_date,
                "description": description,
                "counterparty": name or memo or description,
                "direction": direction,
                "amount": str(abs(signed_amt)),
            }
        )
    return records


def extract_records(
    filename: str,
    content: bytes,
    content_type: str,
    doc_type: DocType,
) -> list[dict[str, Any]]:
    """Dispatch document bytes to the appropriate PDF, OFX, JSON, or CSV extractor."""
    lower_name = filename.lower()
    lower_ct = content_type.lower()
    stripped = content.lstrip()

    if lower_name.endswith(".pdf") or "pdf" in lower_ct or stripped.startswith(b"%PDF"):
        if doc_type != "invoice":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="PDF parsing is currently supported for 'invoice' documents.",
            )
        return parse_pdf_invoice(content, filename)

    if lower_name.endswith((".ofx", ".qfx")) or b"<OFX>" in content[:1024].upper():
        if doc_type != "bank_statement":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="OFX/QFX files are supported for 'bank_statement' documents.",
            )
        return parse_ofx_bank_statement(content)

    if lower_name.endswith(".json") or "json" in lower_ct or stripped[:1] in (b"{", b"["):
        return parse_json_records(content)

    return parse_csv_records(content)
