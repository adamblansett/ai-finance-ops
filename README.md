# AI Finance Operations

> Open-source, self-hosted AI finance operations platform for invoice reconciliation, AP/AR matching, cash flow forecasting, and expense auditing.

**Roadmap Stage:** Phase 1 — Core Professional & Enterprise Operations · **Status:** End-to-End Phase 1 Platform Implemented

## Core Capabilities

- **Document Ingestion (`POST /api/v1/ingestion/upload` & `/payload`):** Parses PDF, CSV, and JSON invoices, purchase orders, goods receipts, bank statements, and expense batches with SHA-256 duplicate-file blocking (`HTTP 409`).
- **Three-Way Invoice Reconciliation (`/api/v1/reconciliation/matches`):** Matches POs ↔ Goods Receipts ↔ Invoices (exact PO + semantic vendor/amount fallback), detecting price variances, short-delivery quantity variances, missing POs/receipts, and duplicate invoices with AI explanations.
- **AP/AR Matching (`/api/v1/reconciliation/ap-ar/propose`):** Normalizes bank/ledger memos (`ACH DEBIT`, `WIRE TRANSFER`, etc.) and scores invoice settlement proposals behind Controller HITL approval gates.
- **13-Week Cash Flow Forecasting (`/api/v1/forecasting/cashflow`):** Projects 13 weekly cash buckets across open AR aging, AP payables, and recurring commitments with interactive scenario modeling (`POST /scenario`), buffer breach detection, and AI variance narrative.
- **Expense Auditing & SOX Trail (`/api/v1/audit/`):** Evaluates receipt hashes, category caps, and IRS/GAAP tax classifications; enforces Controller RBAC (`X-Actor-Role` or signed Bearer token); and chains every mutation into a verifiable SHA-256 SOX audit log.

## Architecture & Engineering Standards

- **Backend (`backend/`):** Python 3.12+, FastAPI, SQLAlchemy 2.0 async (`asyncpg` / `aiosqlite`), Alembic migrations, Pydantic v2, `pypdf`, pure ASGI security-header middleware, and DB-backed `/api/v1/health/ready` probes.
- **Frontend (`frontend/`):** React 18, TypeScript, Vite, Tailwind CSS, and Vitest + Testing Library console across Overview, Ingestion, 3-Way Match, AP/AR Matching, Expense Audit, 13-Week Cash Flow, and SOX Audit & PII views.
- **Privacy & AI Guardrails:** Offline deterministic `mock` mode for CI/dev, local-first Ollama support, and cloud PII redaction enabled by default (`LLM_REDACT_PII_FOR_CLOUD=true`).
- **Containers & CI (`.github/workflows/ci.yml`):** Multi-stage non-root Dockerfiles, PostgreSQL (`pgvector`) + Redis Compose topology, Ruff + Mypy + Pytest checks, TypeScript + Vitest + Vite build, `npm audit`, and Trivy scanning.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for module details.

## Quickstart

### Backend (Local Dev & Tests)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head       # Optional: apply SQLite/Postgres schema migrations
SEED_DEMO_DATA=true uvicorn app.main:app --reload --port 8000
```

Verify lint, strict types, and tests:

```bash
ruff check app tests
mypy app
pytest -v
```

### Frontend (Local Dev & Tests)

```bash
cd frontend
npm ci
npm run dev
```

Verify typecheck, unit tests, and production bundle:

```bash
npx tsc --noEmit
npm run test
npm run build
```

### Docker Compose

```bash
docker compose up --build
```

- Frontend UI: `http://localhost:3000` (includes a one-click **Reset Demo Data** button and `Controller` / `Analyst` role switcher)
- Backend API & OpenAPI Docs: `http://localhost:8000/docs`

---

## License

Licensed under the [MIT License](LICENSE).
