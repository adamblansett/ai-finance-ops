import { useState } from 'react';
import { Check, RefreshCw, Search, X } from 'lucide-react';
import { decideApproval, formatCurrency, runMatchAll } from '../api/client';
import type { ActorContext, ApprovalRequestItem, ThreeWayMatch } from '../types/finance';
import { StatusBadge } from './StatusBadge';

interface ReconciliationViewProps {
  actor: ActorContext;
  matches: ThreeWayMatch[];
  approvals: ApprovalRequestItem[];
  onRefresh: () => Promise<void>;
  onNotify: (msg: string, isError?: boolean) => void;
}

export function ReconciliationView({
  actor,
  matches,
  approvals,
  onRefresh,
  onNotify,
}: ReconciliationViewProps) {
  const [filter, setFilter] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [notesById, setNotesById] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [runningBatch, setRunningBatch] = useState(false);

  const approvalMap = new Map(approvals.map((a) => [a.id, a]));
  const canDecide = actor.role === 'controller' || actor.role === 'admin';

  const filtered = matches.filter((m) => {
    if (filter !== 'all' && m.status !== filter) return false;
    if (searchTerm.trim()) {
      const q = searchTerm.trim().toLowerCase();
      const hay = `${m.invoice_number || ''} ${m.counterparty_name || ''} ${m.po_number || ''}`.toLowerCase();
      return hay.includes(q);
    }
    return true;
  });

  async function handleRunMatchAll() {
    setRunningBatch(true);
    try {
      const res = await runMatchAll(actor);
      onNotify(`Re-evaluated ${res.processed_count} open AP invoice(s).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Batch match failed', true);
    } finally {
      setRunningBatch(false);
    }
  }

  async function handleDecision(approvalId: string, decision: 'approved' | 'rejected') {
    setBusyId(approvalId);
    try {
      const noteText =
        notesById[approvalId]?.trim() || `${decision} in 3-way reconciliation queue`;
      await decideApproval(actor, approvalId, decision, noteText);
      onNotify(`Invoice match ${decision}.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Approval failed', true);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          {['all', 'matched', 'variance_flagged', 'missing_po', 'missing_receipt', 'duplicate_flagged', 'approved', 'rejected'].map(
            (st) => (
              <button
                key={st}
                type="button"
                onClick={() => setFilter(st)}
                className={`rounded-full px-3 py-1 text-xs font-medium capitalize ${
                  filter === st
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                {st.replace(/_/g, ' ')}
              </button>
            ),
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-400" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search invoice or vendor..."
              aria-label="Search reconciliation matches"
              className="rounded-lg border border-slate-300 py-1.5 pl-8 pr-3 text-xs"
            />
          </div>
          <button
            type="button"
            onClick={handleRunMatchAll}
            disabled={runningBatch}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${runningBatch ? 'animate-spin' : ''}`} />
            Run 3-Way Match All
          </button>
        </div>
      </div>

      {!canDecide && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-800">
          Viewing as <strong>{actor.role}</strong>: controller approval buttons remain active to
          test RBAC enforcement (API rejects non-controllers with HTTP 403).
        </div>
      )}

      {filtered.length === 0 ? (
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-xs text-slate-500">
          No three-way match records match this filter. Load demo data or ingest invoices to begin.
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((m) => {
            const approval = m.approval_id ? approvalMap.get(m.approval_id) : undefined;
            const isPending = approval?.status === 'pending';

            return (
              <article
                key={m.id}
                className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-bold text-slate-900">
                        {m.invoice_number || m.invoice_id}
                      </h3>
                      <span className="text-xs font-medium text-slate-600">
                        {m.counterparty_name}
                      </span>
                      <StatusBadge status={m.status} />
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      PO: <span className="font-mono">{m.po_number || 'None'}</span>
                      {' · '}Receipt:{' '}
                      <span className="font-mono">{m.receipt_number || 'None'}</span>
                      {' · '}Confidence:{' '}
                      <span className="font-semibold text-slate-800">
                        {Math.round(m.confidence_score * 100)}%
                      </span>
                    </p>
                  </div>

                  <div className="text-right">
                    <p className="font-mono text-sm font-bold text-slate-900">
                      {m.invoice_total !== null ? formatCurrency(m.invoice_total) : '—'}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      Price Δ: {formatCurrency(m.price_variance)} ({m.price_variance_pct >= 0 ? '+' : ''}
                      {m.price_variance_pct}%) · Qty Δ: {m.qty_variance >= 0 ? '+' : ''}
                      {m.qty_variance}
                    </p>
                  </div>
                </div>

                {m.anomalies.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {m.anomalies.map((a, idx) => (
                      <div
                        key={`${a.code}-${idx}`}
                        className="rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1 text-[11px] text-rose-800"
                      >
                        <span className="font-semibold">{a.code}:</span> {a.message}
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
                  <p className="max-w-3xl text-xs text-slate-600">
                    <span className="font-semibold text-slate-700">
                      AI ({m.llm_provider_used}):
                    </span>{' '}
                    {m.ai_explanation}
                  </p>

                  {isPending && approval && (
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        type="text"
                        value={notesById[approval.id] || ''}
                        onChange={(e) =>
                          setNotesById({ ...notesById, [approval.id]: e.target.value })
                        }
                        placeholder="Decision note (optional)"
                        aria-label={`Decision note for ${m.invoice_number}`}
                        className="rounded-lg border border-slate-300 px-2.5 py-1 text-xs"
                      />
                      <button
                        type="button"
                        disabled={busyId === approval.id}
                        onClick={() => handleDecision(approval.id, 'approved')}
                        aria-label={`Approve ${m.invoice_number}`}
                        className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                      >
                        <Check className="h-3.5 w-3.5" />
                        Approve
                      </button>
                      <button
                        type="button"
                        disabled={busyId === approval.id}
                        onClick={() => handleDecision(approval.id, 'rejected')}
                        aria-label={`Reject ${m.invoice_number}`}
                        className="inline-flex items-center gap-1 rounded-lg border border-rose-300 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                      >
                        <X className="h-3.5 w-3.5" />
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
