import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';

function jsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  };
}

function buildApiMock() {
  const approvals = [
    {
      id: 'app-1',
      entity_type: 'invoice_match',
      entity_id: 'match-1',
      action_requested: 'approve_invoice_posting',
      summary: 'Invoice INV-CC-401 (CloudCore Infrastructure LLC) — matched',
      amount: 24000,
      risk_level: 'low',
      status: 'pending',
      requested_by: 'controller@acme-finops.local',
      decided_by: null,
      decision_notes: null,
      created_at: '2026-11-24T12:00:00Z',
      decided_at: null,
    },
  ];

  const matches = [
    {
      id: 'match-1',
      invoice_id: 'inv-1',
      invoice_number: 'INV-CC-401',
      counterparty_name: 'CloudCore Infrastructure LLC',
      invoice_total: 24000,
      po_id: 'po-1',
      po_number: 'PO-2026-1001',
      po_total: 24000,
      receipt_id: 'gr-1',
      receipt_number: 'GR-2026-9001',
      status: 'matched',
      confidence_score: 0.98,
      price_variance: 0,
      price_variance_pct: 0,
      qty_variance: 0,
      anomalies: [],
      ai_explanation: 'Clean 3-way match across PO, receipt, and invoice.',
      llm_provider_used: 'mock',
      approval_id: 'app-1',
      updated_at: '2026-11-24T12:00:00Z',
    },
    {
      id: 'match-2',
      invoice_id: 'inv-2',
      invoice_number: 'INV-APX-882',
      counterparty_name: 'Apex Logistics Group',
      invoice_total: 13140,
      po_id: 'po-2',
      po_number: 'PO-2026-1002',
      po_total: 12000,
      receipt_id: 'gr-2',
      receipt_number: 'GR-2026-9002',
      status: 'variance_flagged',
      confidence_score: 0.76,
      price_variance: 1140,
      price_variance_pct: 9.5,
      qty_variance: 0,
      anomalies: [
        {
          code: 'PRICE_VARIANCE',
          severity: 'medium',
          message: 'Invoiced $13140.00 vs PO $12000.00 (+9.50%).',
        },
      ],
      ai_explanation: 'Price exceeds PO tolerance.',
      llm_provider_used: 'mock',
      approval_id: null,
      updated_at: '2026-11-24T12:00:00Z',
    },
  ];

  const baseForecast = {
    as_of_date: '2026-11-24',
    starting_cash: 500000,
    ending_cash_week_13: 542000,
    lowest_cash_balance: 470000,
    lowest_cash_week: 4,
    total_inflows_13w: 390000,
    total_outflows_13w: 348000,
    average_weekly_net_flow: 3230.77,
    estimated_runway_weeks: null,
    buffer_breach_week: null,
    scenario: {
      ar_collection_rate_pct: 100,
      ar_delay_days: 0,
      ap_deferral_days: 0,
      revenue_growth_pct: 0,
      expense_shock_pct: 0,
      min_cash_buffer: 100000,
    },
    variance_vs_baseline: {
      ending_cash_delta: 0,
      lowest_cash_delta: 0,
      inflow_delta: 0,
      outflow_delta: 0,
    },
    ar_aging: {
      current: 84500,
      days_1_30: 42000,
      days_31_60: 0,
      days_61_90: 0,
      days_90_plus: 0,
      total_open_ar: 126500,
    },
    weeks: Array.from({ length: 13 }, (_, idx) => ({
      week_number: idx + 1,
      week_start: '2026-11-24',
      week_end: '2026-11-30',
      opening_cash: 500000,
      ar_inflows: idx === 0 ? 42000 : 0,
      recurring_inflows: 21000,
      ap_outflows: 0,
      recurring_outflows: 24000,
      net_cash_flow: idx === 0 ? 39000 : -3000,
      closing_cash: 500000 + idx * 3000,
    })),
    ai_narrative: 'Liquidity stays safely above minimum buffer.',
    llm_provider_used: 'mock',
  };

  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();

    if (url === '/api/v1/health') {
      return jsonResponse({
        status: 'ok',
        service: 'ai-finance-ops',
        app_name: 'AI Finance Operations',
        version: '0.1.0',
        environment: 'test',
        llm_provider: 'mock',
        database: 'ok',
      });
    }
    if (url === '/api/v1/overview') {
      return jsonResponse({
        total_cash: 500000,
        projected_week_13_cash: 542000,
        estimated_runway_weeks: null,
        open_ap_total: 89140,
        open_ar_total: 126500,
        pending_approvals_count: 1,
        flagged_matches_count: 1,
        matched_invoices_count: 1,
        flagged_expenses_count: 0,
        unallocated_transactions_count: 1,
        audit_events_count: 4,
        audit_chain_valid: true,
      });
    }
    if (url === '/api/v1/ingestion/documents') {
      return jsonResponse([]);
    }
    if (url === '/api/v1/reconciliation/matches') {
      return jsonResponse(matches);
    }
    if (url === '/api/v1/reconciliation/bank-transactions') {
      return jsonResponse([]);
    }
    if (url === '/api/v1/reconciliation/allocations') {
      return jsonResponse([]);
    }
    if (url === '/api/v1/audit/expenses') {
      return jsonResponse([]);
    }
    if (url === '/api/v1/audit/approvals') {
      return jsonResponse(approvals);
    }
    if (url === '/api/v1/audit/approvals/app-1/decide' && init?.method === 'POST') {
      approvals[0].status = 'approved';
      matches[0].status = 'approved';
      return jsonResponse(approvals[0]);
    }
    if (url === '/api/v1/audit/events') {
      return jsonResponse([
        {
          id: 'ev-1',
          sequence_no: 1,
          event_type: 'seed.loaded',
          actor_email: 'controller@acme-finops.local',
          actor_role: 'controller',
          entity_type: 'workspace',
          entity_id: 'demo-dataset',
          action: 'seeded',
          details: {},
          prev_hash: 'GENESIS',
          event_hash: 'abcdef1234567890abcdef1234567890',
          created_at: '2026-11-24T12:00:00Z',
        },
      ]);
    }
    if (url === '/api/v1/audit/events/verify') {
      return jsonResponse({
        valid: true,
        total_events: 1,
        head_hash: 'abcdef1234567890abcdef1234567890',
        broken_sequence_no: null,
        message: 'All 1 audit events verified intact.',
      });
    }
    if (url === '/api/v1/audit/pii/redact') {
      return jsonResponse({
        redacted_text: 'Send wire to [REDACTED_EMAIL], SSN [REDACTED_SSN].',
        findings: [{ category: 'email', count: 1, placeholder: '[REDACTED_EMAIL]' }],
        total_redactions: 2,
      });
    }
    if (url === '/api/v1/forecasting/cashflow') {
      return jsonResponse(baseForecast);
    }
    if (url === '/api/v1/forecasting/cashflow/scenario') {
      return jsonResponse({
        ...baseForecast,
        ending_cash_week_13: 485000,
        variance_vs_baseline: {
          ending_cash_delta: -57000,
          lowest_cash_delta: -57000,
          inflow_delta: -40000,
          outflow_delta: 17000,
        },
      });
    }
    if (url === '/api/v1/forecasting/commitments') {
      return jsonResponse([]);
    }
    if (url === '/api/v1/jobs') {
      return jsonResponse([]);
    }
    if (url === '/api/v1/reconciliation/gl-suggest') {
      return jsonResponse({
        gl_account: '6100-CLOUD',
        gl_name: 'Cloud & Infrastructure Hosting',
        confidence: 0.91,
        reason: 'Matched cloud hosting',
      });
    }
    if (url === '/api/v1/auth/login') {
      return jsonResponse({
        access_token: 'fake.jwt.token',
        refresh_token: 'fake.refresh.token',
        token_type: 'bearer',
        actor: {
          email: 'controller@acme-finops.local',
          role: 'controller',
          auth_method: 'bearer_token',
        },
      });
    }
    return jsonResponse({});
  });
}

describe('AI Finance Operations workspace', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders live API health, overview KPIs, and navigates across core modules', async () => {
    const mockFetch = buildApiMock();
    vi.stubGlobal('fetch', mockFetch);

    render(<App />);

    expect(screen.getByRole('heading', { name: 'AI Finance Operations' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/API Healthy \(mock\)/i)).toBeInTheDocument();
    });
    expect(screen.getByText('$500,000.00')).toBeInTheDocument();
    expect(screen.getByText('Verified Intact')).toBeInTheDocument();

    // Navigate to 3-Way Match and approve INV-CC-401
    fireEvent.click(screen.getByRole('button', { name: /3-Way Match/i }));
    await waitFor(() => {
      expect(screen.getByText('INV-CC-401')).toBeInTheDocument();
    });
    expect(screen.getByText(/PRICE_VARIANCE:/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Approve INV-CC-401/i }));
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/audit/approvals/app-1/decide',
        expect.objectContaining({ method: 'POST' }),
      );
    });

    // Switch role to Analyst and run 13-week cash flow scenario
    fireEvent.change(screen.getByLabelText('Actor Role'), { target: { value: 'analyst' } });
    fireEvent.click(screen.getByRole('button', { name: /13-Week Cash Flow/i }));
    await waitFor(() => {
      expect(screen.getByRole('img', { name: '13-week cash flow chart' })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Run Scenario/i }));
    await waitFor(() => {
      expect(screen.getByText('$485,000.00')).toBeInTheDocument();
    });

    // Navigate to Jobs & Exports and test GL suggestion
    fireEvent.click(screen.getByRole('button', { name: /Jobs & Exports/i }));
    await waitFor(() => {
      expect(screen.getByText(/Semantic GL Account Coder/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /Suggest GL Code/i }));
    await waitFor(() => {
      expect(screen.getByText('6100-CLOUD')).toBeInTheDocument();
    });

    // Navigate to SOX Audit & PII and test redaction preview
    fireEvent.click(screen.getByRole('button', { name: /SOX Audit & PII/i }));
    await waitFor(() => {
      expect(screen.getByText('seed.loaded')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /Preview Cloud Redaction/i }));
    await waitFor(() => {
      expect(screen.getByText(/\[REDACTED_EMAIL\]/i)).toBeInTheDocument();
    });
  });
});
