# AI Finance Operations

> Open-source, self-hosted AI finance operations platform for invoice reconciliation, AP/AR matching, cash flow forecasting, and expense auditing.

**Roadmap Stage:** Phase 1 & Phase 2 Complete · **Status:** Production-Hardened Platform

## Core Capabilities

- **Document Ingestion (`POST /api/v1/ingestion/upload` & `/payload`):** Parses PDF, JSON, CSV (including QuickBooks/Xero/NetSuite column aliases), and OFX/QFX bank statements with SHA-256 duplicate-file blocking (`HTTP 409`).
- **Three-Way Invoice Reconciliation & Semantic GL Coding (`/api/v1/reconciliation/`):** Matches POs ↔ Goods Receipts ↔ Invoices using exact + vector-assisted fallback, detects price/qty variances, near-duplicates, and missing POs/receipts, and assigns Chart-of-Accounts GL codes.
- **AP/AR Matching (`/api/v1/reconciliation/ap-ar/propose`):** Normalizes bank/ledger memos and scores invoice settlement proposals behind Controller HITL approval gates.
- **13-Week Cash Flow Forecasting (`/api/v1/forecasting/cashflow`):** Projects 13 weekly cash buckets across open AR aging, AP payables, and recurring commitments with interactive scenario modeling (`POST /scenario`), buffer breach alerts, and AI commentary.
- **Expense Auditing, JWT Auth & SOX Audit (`/api/v1/audit/`, `/api/v1/auth/`):** Evaluates receipt hashes, category caps, and tax classifications; enforces PBKDF2-backed JWT login/refresh or dev RBAC; and chains every event into a concurrency-safe SHA-256 SOX audit log.
- **Async Jobs & Controller Exports (`/api/v1/jobs/`, `/api/v1/exports/`):** Dispatches batch reconciliation, AP/AR matching, and forecast snapshots (`inline`, `async`, or `redis` worker) and exports CSV/JSON controller close packets.

## Architecture & Engineering Standards

- **Backend (`backend/`):** Python 3.12+, FastAPI, SQLAlchemy 2.0 async (`asyncpg` / `aiosqlite`), reversible Alembic migrations, Redis/in-memory rate limiting, `structlog` JSON logging with secret scrubbing, optional OpenTelemetry tracing, and DB-backed `/api/v1/health/ready` probes.
- **Frontend (`frontend/`):** React 18, TypeScript, Vite, Tailwind CSS, React `ErrorBoundary`, Vitest + Testing Library unit tests, and Playwright Chromium E2E tests.
- **Containers & CI (`.github/workflows/ci.yml`):** Multi-stage non-root Dockerfiles with `.dockerignore`, PostgreSQL (`pgvector`) + Redis + optional `worker` Compose topology, Ruff + Mypy + Pytest, TypeScript + Vitest + Vite build, Playwright E2E, `npm audit`, and Trivy scanning.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/PRODUCTION_READINESS_AUDIT.md](docs/PRODUCTION_READINESS_AUDIT.md).

## Quickstart

### Backend (Local Dev & Tests)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
SEED_DEMO_DATA=true uvicorn app.main:app --reload --port 8000
```

Verify lint, strict types, and tests:

```bash
ruff check app tests
mypy app
pytest -v
```

### Frontend & Playwright E2E

```bash
cd frontend
npm ci
npm run dev
```

Verify typecheck, unit tests, production bundle, and Playwright E2E:

```bash
npx tsc --noEmit
npm run test
npm run build
npm run test:e2e
```

### Docker Compose

```bash
docker compose up --build
# Optional Redis background worker:
docker compose --profile worker up --build
```

- Frontend UI: `http://localhost:3000` (Demo accounts: `controller@acme-finops.local` / `ControllerDemo123!`, `analyst@acme-finops.local` / `AnalystDemo123!`)
- Backend API & OpenAPI Docs: `http://localhost:8000/docs`

---

## License

Licensed under the [MIT License](LICENSE).
