# AI Finance Operations — Architecture Blueprint

## Overview

Open-source, self-hosted AI finance operations platform for invoice reconciliation, AP/AR matching, cash flow forecasting, and expense auditing.

## Implemented Domain Modules (`backend/app/`)

- **`core/`** — Pydantic settings with production fail-fast checks, HMAC-SHA256 bearer auth & dev actor RBAC (`viewer`, `analyst`, `controller`, `admin`), counterparty normalization, and ASGI security-header middleware.
- **`db/` & `alembic/`** — Async SQLAlchemy 2.0 ORM (`asyncpg` for PostgreSQL, `aiosqlite` for local dev/CI), `Decimal` money precision, 13 domain/governance tables, and Alembic async migrations (`0001_initial_schema`).
- **`llm/`** — `LLMRouter` (`mock` → `ollama` → `gemini` fallback chain) with outbound cloud PII redaction (`redact_pii`) covering SSNs, EINs, emails, phone numbers, Luhn-validated payment cards, IBANs, bank accounts, and routing numbers.
- **`ingestion/`** — Multipart PDF (`pypdf`), CSV, and JSON upload + inline payload ingestion with SHA-256 duplicate-document blocking (`409 Conflict`) and automatic AP 3-way reconciliation / expense policy evaluation.
- **`reconciliation/`** — Deterministic + semantic 3-way matching (PO ↔ Goods Receipt ↔ Invoice) flagging price/quantity variances, math mismatches, missing POs/receipts, and duplicate invoices, plus AP/AR bank transaction normalization and payment allocation scoring.
- **`forecasting/`** — Rolling 13-week cash flow projection engine combining open AR aging, AP commitments, recurring inflows/outflows, interactive sensitivity sliders, runway calculation, and AI variance commentary.
- **`audit/`** — Configurable expense policy engine (category caps, duplicate receipt hashes, missing receipts, tax-category validation, weekend checks), Controller HITL approval state machine, and tamper-evident SHA-256 hash-chained SOX audit trail (`verify_audit_chain`).
- **`seed/`** — Idempotent demo dataset loader (`POST /api/v1/seed/demo`) covering clean matches, variances, missing POs/receipts, duplicate invoices, bank allocations, expense violations, and 13-week cash commitments.

## Security & Operational Invariants

1. **Fail-Fast Production Validation:** `validate_production_security()` refuses startup in `APP_ENV=production` if default dev secrets or wildcard CORS origins remain active.
2. **Cloud PII Redaction:** Outbound cloud LLM adapters run PII scrubbing when `LLM_REDACT_PII_FOR_CLOUD=true`.
3. **Human-in-the-Loop Approvals & RBAC:** High-impact ledger mutations (invoice match posting, payment allocations, flagged expenses) require `controller` or `admin` approval and append SHA-256 chained `AuditEvent` records.
4. **Non-Root Containers:** Both the FastAPI API image and Nginx frontend image run as non-root users with `/api/v1/health/live` and `/api/v1/health/ready` (DB connectivity) probes.
