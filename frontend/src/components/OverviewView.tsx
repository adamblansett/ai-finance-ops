import {
  AlertTriangle,
  ArrowRightLeft,
  CheckCircle2,
  Database,
  DollarSign,
  FileCheck2,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import { formatCurrency } from '../api/client';
import type { ApprovalRequestItem, OverviewSummary } from '../types/finance';
import { StatusBadge } from './StatusBadge';

interface OverviewViewProps {
  overview: OverviewSummary | null;
  approvals: ApprovalRequestItem[];
  onNavigate: (tab: string) => void;
  onLoadDemo: () => void;
  busy: boolean;
}

export function OverviewView({
  overview,
  approvals,
  onNavigate,
  onLoadDemo,
  busy,
}: OverviewViewProps) {
  const pendingApprovals = approvals.filter((a) => a.status === 'pending');

  return (
    <div className="space-y-6">
      {overview && overview.audit_events_count === 0 && (
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-indigo-200 bg-indigo-50 p-5">
          <div>
            <h2 className="text-sm font-semibold text-indigo-950">
              Workspace Ready — Load Realistic Phase 1 Finance Dataset
            </h2>
            <p className="mt-1 text-xs text-indigo-800">
              Populate vendors, POs, goods receipts, 3-way matched &amp; anomaly invoices, bank
              transactions, employee expenses, and 13-week cash commitments in one click.
            </p>
          </div>
          <button
            type="button"
            onClick={onLoadDemo}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
          >
            <Database className="h-4 w-4" />
            Load Demo Data
          </button>
        </div>
      )}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between text-xs font-medium text-slate-500">
            <span>Current Cash Position</span>
            <DollarSign className="h-4 w-4 text-emerald-600" />
          </div>
          <p className="mt-2 text-2xl font-bold text-slate-900">
            {overview ? formatCurrency(overview.total_cash) : '—'}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Wk 13 Proj:{' '}
            <span className="font-medium text-slate-700">
              {overview ? formatCurrency(overview.projected_week_13_cash) : '—'}
            </span>
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between text-xs font-medium text-slate-500">
            <span>Open AP / Open AR</span>
            <ArrowRightLeft className="h-4 w-4 text-indigo-600" />
          </div>
          <p className="mt-2 text-lg font-bold text-slate-900">
            {overview
              ? `${formatCurrency(overview.open_ap_total)} / ${formatCurrency(overview.open_ar_total)}`
              : '—'}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Unallocated bank lines: {overview?.unallocated_transactions_count ?? 0}
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between text-xs font-medium text-slate-500">
            <span>Controller HITL Queue</span>
            <AlertTriangle className="h-4 w-4 text-amber-600" />
          </div>
          <p className="mt-2 text-2xl font-bold text-slate-900">
            {overview?.pending_approvals_count ?? 0}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {overview?.flagged_matches_count ?? 0} flagged matches ·{' '}
            {overview?.flagged_expenses_count ?? 0} flagged expenses
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between text-xs font-medium text-slate-500">
            <span>SOX Hash-Chain Audit</span>
            <ShieldCheck className="h-4 w-4 text-emerald-600" />
          </div>
          <p className="mt-2 flex items-center gap-2 text-lg font-bold text-slate-900">
            <CheckCircle2
              className={`h-5 w-5 ${
                overview?.audit_chain_valid ? 'text-emerald-600' : 'text-rose-600'
              }`}
            />
            {overview?.audit_chain_valid ? 'Verified Intact' : 'Check Needed'}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {overview?.audit_events_count ?? 0} immutable chained events
          </p>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <button
          type="button"
          onClick={() => onNavigate('reconciliation')}
          className="rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-indigo-300"
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <FileCheck2 className="h-4 w-4 text-indigo-600" />
            Invoice Reconciliation
          </div>
          <p className="mt-1 text-xs text-slate-600">
            Three-way matching across POs, receipts, and vendor invoices with anomaly flags.
          </p>
        </button>

        <button
          type="button"
          onClick={() => onNavigate('apar')}
          className="rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-indigo-300"
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <ArrowRightLeft className="h-4 w-4 text-indigo-600" />
            AP/AR Matching
          </div>
          <p className="mt-1 text-xs text-slate-600">
            Ledger normalization and payment allocation suggestions with controller approval gates.
          </p>
        </button>

        <button
          type="button"
          onClick={() => onNavigate('forecast')}
          className="rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-indigo-300"
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <TrendingUp className="h-4 w-4 text-indigo-600" />
            Cash Flow Forecasting
          </div>
          <p className="mt-1 text-xs text-slate-600">
            Rolling 13-week projection across AR aging, commitments, and runway sensitivity.
          </p>
        </button>

        <button
          type="button"
          onClick={() => onNavigate('expenses')}
          className="rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-indigo-300"
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <ShieldCheck className="h-4 w-4 text-emerald-600" />
            Expense Auditing
          </div>
          <p className="mt-1 text-xs text-slate-600">
            Policy compliance checks, duplicate receipt detection, and tax-category validation.
          </p>
        </button>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-900">
            Pending Controller Approvals ({pendingApprovals.length})
          </h2>
          <button
            type="button"
            onClick={() => onNavigate('reconciliation')}
            className="text-xs font-medium text-indigo-600 hover:text-indigo-700"
          >
            Review in Queue →
          </button>
        </div>
        {pendingApprovals.length === 0 ? (
          <p className="px-5 py-6 text-xs text-slate-500">
            No pending approvals right now.
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {pendingApprovals.slice(0, 8).map((item) => (
              <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                <div>
                  <p className="text-xs font-semibold text-slate-900">{item.summary}</p>
                  <p className="text-[11px] text-slate-500">
                    {item.entity_type.replace(/_/g, ' ')} · requested by {item.requested_by}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-semibold text-slate-800">
                    {formatCurrency(item.amount)}
                  </span>
                  <StatusBadge status={item.risk_level} />
                  <StatusBadge status={item.status} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
