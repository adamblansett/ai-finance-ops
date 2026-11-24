import { useState } from 'react';
import { ArrowRightLeft, Check, Sparkles, X } from 'lucide-react';
import { decideApproval, formatCurrency, proposeAllocations } from '../api/client';
import type {
  ActorContext,
  ApprovalRequestItem,
  BankTransaction,
  PaymentAllocation,
} from '../types/finance';
import { StatusBadge } from './StatusBadge';

interface ApArViewProps {
  actor: ActorContext;
  transactions: BankTransaction[];
  allocations: PaymentAllocation[];
  approvals: ApprovalRequestItem[];
  onRefresh: () => Promise<void>;
  onNotify: (msg: string, isError?: boolean) => void;
}

export function ApArView({
  actor,
  transactions,
  allocations,
  approvals,
  onRefresh,
  onNotify,
}: ApArViewProps) {
  const [proposing, setProposing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const approvalMap = new Map(approvals.map((a) => [a.id, a]));

  async function handlePropose() {
    setProposing(true);
    try {
      const res = await proposeAllocations(actor);
      onNotify(`Proposed ${res.proposed_count} new AP/AR payment allocation(s).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Auto-allocation failed', true);
    } finally {
      setProposing(false);
    }
  }

  async function handleDecision(approvalId: string, decision: 'approved' | 'rejected') {
    setBusyId(approvalId);
    try {
      await decideApproval(actor, approvalId, decision, `AP/AR allocation ${decision}`);
      onNotify(`Payment allocation ${decision}.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Approval decision failed', true);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">
            AP/AR Payment Allocation &amp; Ledger Normalization
          </h2>
          <p className="text-xs text-slate-500">
            Normalizes bank memos and suggests invoice settlements gated by controller approval.
          </p>
        </div>
        <button
          type="button"
          onClick={handlePropose}
          disabled={proposing}
          className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          <Sparkles className="h-3.5 w-3.5" />
          {proposing ? 'Matching...' : 'Run Auto-Allocation'}
        </button>
      </div>

      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Suggested Payment Allocations ({allocations.length})
        </h3>
        {allocations.length === 0 ? (
          <div className="rounded-xl border border-slate-200 bg-white p-6 text-xs text-slate-500">
            No payment allocations proposed yet.
          </div>
        ) : (
          allocations.map((alloc) => {
            const approval = alloc.approval_id ? approvalMap.get(alloc.approval_id) : undefined;
            const isPending = approval?.status === 'pending';

            return (
              <div
                key={alloc.id}
                className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
              >
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <ArrowRightLeft className="h-3.5 w-3.5 text-indigo-600" />
                    <span className="font-mono text-xs font-semibold text-slate-900">
                      {alloc.bank_ref}
                    </span>
                    <span className="text-xs text-slate-400">→</span>
                    <span className="font-mono text-xs font-semibold text-indigo-700">
                      {alloc.invoice_number}
                    </span>
                    <span className="text-xs text-slate-600">{alloc.counterparty_name}</span>
                    <StatusBadge status={alloc.status} />
                  </div>
                  <p className="text-xs text-slate-600">{alloc.match_reason}</p>
                  <p className="text-[11px] text-slate-500">
                    Confidence: {Math.round(alloc.confidence_score * 100)}%
                  </p>
                </div>

                <div className="flex items-center gap-3">
                  <span className="font-mono text-sm font-bold text-slate-900">
                    {formatCurrency(alloc.allocated_amount)}
                  </span>
                  {isPending && approval && (
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        disabled={busyId === approval.id}
                        onClick={() => handleDecision(approval.id, 'approved')}
                        aria-label={`Approve allocation ${alloc.bank_ref}`}
                        className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700"
                      >
                        <Check className="h-3.5 w-3.5" />
                        Approve
                      </button>
                      <button
                        type="button"
                        disabled={busyId === approval.id}
                        onClick={() => handleDecision(approval.id, 'rejected')}
                        aria-label={`Reject allocation ${alloc.bank_ref}`}
                        className="inline-flex items-center gap-1 rounded-lg border border-rose-300 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50"
                      >
                        <X className="h-3.5 w-3.5" />
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="border-b border-slate-200 px-5 py-3.5">
          <h3 className="text-sm font-semibold text-slate-900">
            Bank &amp; Ledger Feed ({transactions.length})
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-xs">
            <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2.5">Ref</th>
                <th className="px-4 py-2.5">Date</th>
                <th className="px-4 py-2.5">Normalized Counterparty</th>
                <th className="px-4 py-2.5">Raw Bank Memo</th>
                <th className="px-4 py-2.5">Direction</th>
                <th className="px-4 py-2.5">Amount</th>
                <th className="px-4 py-2.5">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {transactions.map((tx) => (
                <tr key={tx.id}>
                  <td className="px-4 py-2.5 font-mono font-medium text-slate-900">
                    {tx.external_ref}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600">{tx.transaction_date}</td>
                  <td className="px-4 py-2.5 font-medium text-slate-800">
                    {tx.normalized_counterparty}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">{tx.description}</td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`font-semibold ${
                        tx.direction === 'inflow' ? 'text-emerald-700' : 'text-slate-700'
                      }`}
                    >
                      {tx.direction}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-mono font-semibold text-slate-900">
                    {formatCurrency(tx.amount)}
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={tx.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
