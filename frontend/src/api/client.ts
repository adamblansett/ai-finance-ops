import type {
  ActorContext,
  ApprovalRequestItem,
  AuditChainVerify,
  AuditEventItem,
  BankTransaction,
  CashAccount,
  DocType,
  ExpenseCreateInput,
  ExpenseItem,
  ForecastResponse,
  ForecastScenario,
  HealthStatus,
  IngestedDocument,
  IngestionResult,
  OverviewSummary,
  PaymentAllocation,
  PiiRedactResult,
  RecurringCommitment,
  SeedSummary,
  ThreeWayMatch,
} from '../types/finance';

export class ApiClientError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiClientError';
    this.status = status;
  }
}

async function requestJson<T>(
  path: string,
  actor: ActorContext,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('X-Actor-Email', actor.email);
  headers.set('X-Actor-Role', actor.role);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as {
        detail?: string | { message?: string };
      };
      if (typeof payload.detail === 'string') {
        message = payload.detail;
      } else if (payload.detail && typeof payload.detail.message === 'string') {
        message = payload.detail.message;
      }
    } catch {
      // ignore non-JSON error body
    }
    throw new ApiClientError(message, response.status);
  }
  return (await response.json()) as T;
}

export async function fetchHealth(): Promise<HealthStatus> {
  const response = await fetch('/api/v1/health');
  if (!response.ok) {
    throw new ApiClientError('API health check failed', response.status);
  }
  return (await response.json()) as HealthStatus;
}

export function fetchOverview(actor: ActorContext): Promise<OverviewSummary> {
  return requestJson<OverviewSummary>('/api/v1/overview', actor);
}

export function seedDemoData(actor: ActorContext, reset = false): Promise<SeedSummary> {
  return requestJson<SeedSummary>(`/api/v1/seed/demo?reset=${reset}`, actor, {
    method: 'POST',
  });
}

export function fetchDocuments(actor: ActorContext): Promise<IngestedDocument[]> {
  return requestJson<IngestedDocument[]>('/api/v1/ingestion/documents', actor);
}

export function uploadDocumentFile(
  actor: ActorContext,
  file: File,
  docType: DocType,
  autoReconcile = true,
): Promise<IngestionResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('doc_type', docType);
  form.append('auto_reconcile', String(autoReconcile));
  return requestJson<IngestionResult>('/api/v1/ingestion/upload', actor, {
    method: 'POST',
    body: form,
  });
}

export function ingestInlinePayload(
  actor: ActorContext,
  payload: {
    filename: string;
    doc_type: DocType;
    format: 'json' | 'csv';
    content: string | Record<string, unknown>[];
    auto_reconcile?: boolean;
  },
): Promise<IngestionResult> {
  return requestJson<IngestionResult>('/api/v1/ingestion/payload', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchMatches(actor: ActorContext): Promise<ThreeWayMatch[]> {
  return requestJson<ThreeWayMatch[]>('/api/v1/reconciliation/matches', actor);
}

export function runMatchAll(actor: ActorContext): Promise<{ processed_count: number }> {
  return requestJson<{ processed_count: number }>('/api/v1/reconciliation/match-all', actor, {
    method: 'POST',
  });
}

export function fetchBankTransactions(actor: ActorContext): Promise<BankTransaction[]> {
  return requestJson<BankTransaction[]>('/api/v1/reconciliation/bank-transactions', actor);
}

export function fetchAllocations(actor: ActorContext): Promise<PaymentAllocation[]> {
  return requestJson<PaymentAllocation[]>('/api/v1/reconciliation/allocations', actor);
}

export function proposeAllocations(actor: ActorContext): Promise<{ proposed_count: number }> {
  return requestJson<{ proposed_count: number }>('/api/v1/reconciliation/ap-ar/propose', actor, {
    method: 'POST',
  });
}

export function fetchExpenses(actor: ActorContext): Promise<ExpenseItem[]> {
  return requestJson<ExpenseItem[]>('/api/v1/audit/expenses', actor);
}

export function submitExpense(
  actor: ActorContext,
  payload: ExpenseCreateInput,
): Promise<ExpenseItem> {
  return requestJson<ExpenseItem>('/api/v1/audit/expenses', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchApprovals(actor: ActorContext): Promise<ApprovalRequestItem[]> {
  return requestJson<ApprovalRequestItem[]>('/api/v1/audit/approvals', actor);
}

export function decideApproval(
  actor: ActorContext,
  approvalId: string,
  decision: 'approved' | 'rejected',
  notes: string,
): Promise<ApprovalRequestItem> {
  return requestJson<ApprovalRequestItem>(`/api/v1/audit/approvals/${approvalId}/decide`, actor, {
    method: 'POST',
    body: JSON.stringify({ decision, notes }),
  });
}

export function fetchAuditEvents(actor: ActorContext): Promise<AuditEventItem[]> {
  return requestJson<AuditEventItem[]>('/api/v1/audit/events', actor);
}

export function verifyAuditChain(actor: ActorContext): Promise<AuditChainVerify> {
  return requestJson<AuditChainVerify>('/api/v1/audit/events/verify', actor);
}

export function redactPiiText(actor: ActorContext, text: string): Promise<PiiRedactResult> {
  return requestJson<PiiRedactResult>('/api/v1/audit/pii/redact', actor, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

export function fetchCashflowBaseline(actor: ActorContext): Promise<ForecastResponse> {
  return requestJson<ForecastResponse>('/api/v1/forecasting/cashflow', actor);
}

export function runCashflowScenario(
  actor: ActorContext,
  scenario: ForecastScenario,
): Promise<ForecastResponse> {
  return requestJson<ForecastResponse>('/api/v1/forecasting/cashflow/scenario', actor, {
    method: 'POST',
    body: JSON.stringify(scenario),
  });
}

export function fetchCommitments(actor: ActorContext): Promise<RecurringCommitment[]> {
  return requestJson<RecurringCommitment[]>('/api/v1/forecasting/commitments', actor);
}

export function createCommitment(
  actor: ActorContext,
  payload: Omit<RecurringCommitment, 'id' | 'active'>,
): Promise<RecurringCommitment> {
  return requestJson<RecurringCommitment>('/api/v1/forecasting/commitments', actor, {
    method: 'POST',
    body: JSON.stringify({ ...payload, active: true }),
  });
}

export function fetchCashAccounts(actor: ActorContext): Promise<CashAccount[]> {
  return requestJson<CashAccount[]>('/api/v1/forecasting/accounts', actor);
}

export function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(amount);
}
