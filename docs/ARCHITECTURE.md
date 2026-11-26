# AI Finance Operations — Architecture Blueprint

## Overview

Open-source, self-hosted AI finance operations platform for invoice reconciliation, AP/AR matching, cash flow forecasting, and expense auditing.

## Implemented Domain Modules (`backend/app/`)

- **`core/`** — Pydantic settings with production fail-fast checks, PBKDF2-HMAC-SHA256 user passwords, HMAC-SHA256 access/refresh JWTs & dev RBAC (`viewer`, `analyst`, `controller`, `admin`), Redis-backed + in-memory `RateLimitMiddleware`, secret-scrubbing `structlog` JSON logging, OpenTelemetry spans, counterparty normalization, and ASGI security headers.
- **`db/` & `alembic/`** — Async SQLAlchemy 2.0 ORM (`asyncpg` for PostgreSQL, `aiosqlite` for local dev/CI), `Decimal` money precision, 16 tables (`users`, `background_jobs`, `semantic_embeddings`, plus core finance/SOX tables), and reversible Alembic migrations (`0001_initial_schema` → `0002_phase2_hardening`).
- **`llm/`** — `LLMRouter` (`mock` → `ollama` → `gemini` fallback chain) with outbound cloud PII redaction (`redact_pii`) and `EmbeddingService` (deterministic feature-hashing or Ollama `/api/embeddings`) for semantic search, PO matching, and GL coding.
- **`ingestion/`** — Modular `extractors.py` + `parsers.py` supporting PDF (`pypdf`), CSV (with QBO/Xero/NetSuite header aliases), JSON, and OFX/QFX `<STMTTRN>` bank statements with SHA-256 duplicate-document blocking (`409 Conflict`).
- **`reconciliation/`** — Deterministic + semantic 3-way matching (PO ↔ Goods Receipt ↔ Invoice) with near-duplicate invoice detection and automated Chart-of-Accounts GL coding (`gl_coding.py`), plus AP/AR payment allocation scoring and paginated `.in_()`-hydrated endpoints.
- **`forecasting/`** — Rolling 13-week cash flow projection engine combining open AR aging, AP commitments, recurring inflows/outflows, interactive sensitivity sliders, runway calculation, and AI variance commentary.
- **`audit/`** — Configurable expense policy engine, Controller HITL approval state machine, and concurrency-safe (`pg_advisory_xact_lock` + async lock) SHA-256 hash-chained SOX audit trail (`verify_audit_chain`).
- **`jobs/` & `exports/`** — Async `BackgroundJob` queue (`inline`, `async`, or `redis` + `python -m app.jobs.worker`) and audit/controller CSV + JSON close packet exports.
- **`seed/`** — Idempotent demo dataset loader (`POST /api/v1/seed/demo`) including demo controller/analyst login accounts, embeddings, and Phase 1/2 finance fixtures.

See [PRODUCTION_READINESS_AUDIT.md](PRODUCTION_READINESS_AUDIT.md) for the 4-Pillar readiness evaluation.
