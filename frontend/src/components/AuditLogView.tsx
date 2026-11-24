import { useState } from 'react';
import { Lock, ShieldCheck } from 'lucide-react';
import { redactPiiText, verifyAuditChain } from '../api/client';
import type {
  ActorContext,
  AuditChainVerify,
  AuditEventItem,
  PiiRedactResult,
} from '../types/finance';

interface AuditLogViewProps {
  actor: ActorContext;
  events: AuditEventItem[];
  chainStatus: AuditChainVerify | null;
  onChainVerified: (status: AuditChainVerify) => void;
  onNotify: (msg: string, isError?: boolean) => void;
}

export function AuditLogView({
  actor,
  events,
  chainStatus,
  onChainVerified,
  onNotify,
}: AuditLogViewProps) {
  const [piiInput, setPiiInput] = useState(
    'Send wire to vendor@example.com, SSN 123-45-6789, acct 9876543210, phone 415-555-0199.',
  );
  const [piiResult, setPiiResult] = useState<PiiRedactResult | null>(null);
  const [verifying, setVerifying] = useState(false);

  async function handleVerify() {
    setVerifying(true);
    try {
      const res = await verifyAuditChain(actor);
      onChainVerified(res);
      onNotify(res.message, !res.valid);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Verification failed', true);
    } finally {
      setVerifying(false);
    }
  }

  async function handleRedact(e: React.FormEvent) {
    e.preventDefault();
    try {
      const res = await redactPiiText(actor, piiInput);
      setPiiResult(res);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Redaction failed', true);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-start gap-3">
          <ShieldCheck
            className={`mt-0.5 h-5 w-5 ${
              chainStatus?.valid !== false ? 'text-emerald-600' : 'text-rose-600'
            }`}
          />
          <div>
            <h2 className="text-sm font-semibold text-slate-900">
              SOX Tamper-Evident Audit Chain
            </h2>
            <p className="mt-0.5 text-xs text-slate-600">
              {chainStatus
                ? `${chainStatus.message} (head: ${chainStatus.head_hash.slice(0, 16)}...)`
                : 'Click verify to recompute every SHA-256 chain link.'}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleVerify}
          disabled={verifying}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {verifying ? 'Verifying...' : 'Verify Hash Chain'}
        </button>
      </div>

      <form
        onSubmit={handleRedact}
        className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-3"
      >
        <div className="flex items-center gap-2">
          <Lock className="h-4 w-4 text-indigo-600" />
          <h3 className="text-sm font-semibold text-slate-900">
            Outbound Cloud PII Redaction Tester
          </h3>
        </div>
        <textarea
          rows={2}
          value={piiInput}
          onChange={(e) => setPiiInput(e.target.value)}
          className="w-full rounded-lg border border-slate-300 bg-slate-50 p-2.5 text-xs"
        />
        <div className="flex items-center gap-3">
          <button
            type="submit"
            className="rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
          >
            Preview Cloud Redaction
          </button>
          {piiResult && (
            <span className="text-xs text-slate-600">
              Scrubbed {piiResult.total_redactions} sensitive token(s)
            </span>
          )}
        </div>
        {piiResult && (
          <pre className="whitespace-pre-wrap rounded-lg border border-emerald-200 bg-emerald-50 p-3 font-mono text-[11px] text-emerald-900">
            {piiResult.redacted_text}
          </pre>
        )}
      </form>

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="border-b border-slate-200 px-5 py-3.5">
          <h3 className="text-sm font-semibold text-slate-900">
            Immutable Audit Events ({events.length})
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-xs">
            <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Seq</th>
                <th className="px-3 py-2">Event</th>
                <th className="px-3 py-2">Actor</th>
                <th className="px-3 py-2">Entity</th>
                <th className="px-3 py-2">Action</th>
                <th className="px-3 py-2">Event SHA-256</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {events.map((ev) => (
                <tr key={ev.id}>
                  <td className="px-3 py-2 font-mono text-slate-500">#{ev.sequence_no}</td>
                  <td className="px-3 py-2 font-semibold text-slate-900">{ev.event_type}</td>
                  <td className="px-3 py-2 text-slate-600">
                    {ev.actor_email} ({ev.actor_role})
                  </td>
                  <td className="px-3 py-2 text-slate-600">
                    {ev.entity_type}:{ev.entity_id.slice(0, 8)}
                  </td>
                  <td className="px-3 py-2 font-medium text-indigo-700">{ev.action}</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-slate-500">
                    {ev.event_hash.slice(0, 14)}...
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
