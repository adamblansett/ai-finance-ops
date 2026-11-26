import { useState } from 'react';
import { Download, Play, RefreshCw, Sparkles } from 'lucide-react';
import {
  downloadExportFile,
  enqueueApArJob,
  enqueueForecastJob,
  enqueueReconcileJob,
  semanticSearch,
  suggestGlAccount,
} from '../api/client';
import type {
  ActorContext,
  BackgroundJobItem,
  GLSuggestion,
  SemanticSearchHit,
} from '../types/finance';
import { StatusBadge } from './StatusBadge';

interface JobsExportsViewProps {
  actor: ActorContext;
  jobs: BackgroundJobItem[];
  onRefresh: () => Promise<void>;
  onNotify: (msg: string, isError?: boolean) => void;
}

export function JobsExportsView({
  actor,
  jobs,
  onRefresh,
  onNotify,
}: JobsExportsViewProps) {
  const [busyJob, setBusyJob] = useState<string | null>(null);
  const [glVendor, setGlVendor] = useState('CloudCore Infrastructure LLC');
  const [glDesc, setGlDesc] = useState('GPU compute cluster monthly hosting');
  const [glResult, setGlResult] = useState<GLSuggestion | null>(null);
  const [searchQuery, setSearchQuery] = useState('GPU compute cloud infrastructure');
  const [searchHits, setSearchHits] = useState<SemanticSearchHit[]>([]);

  async function handleEnqueue(kind: 'reconcile' | 'apar' | 'forecast') {
    setBusyJob(kind);
    try {
      const job =
        kind === 'reconcile'
          ? await enqueueReconcileJob(actor)
          : kind === 'apar'
            ? await enqueueApArJob(actor)
            : await enqueueForecastJob(actor);
      onNotify(`Job ${job.job_type} (${job.status}, ${job.progress_pct}%).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Job enqueue failed', true);
    } finally {
      setBusyJob(null);
    }
  }

  async function handleDownload(path: string, filename: string) {
    try {
      await downloadExportFile(actor, path, filename);
      onNotify(`Downloaded ${filename}.`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Export download failed', true);
    }
  }

  async function handleGlSuggest(e: React.FormEvent) {
    e.preventDefault();
    try {
      const res = await suggestGlAccount(actor, glVendor, glDesc);
      setGlResult(res);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'GL suggestion failed', true);
    }
  }

  async function handleSemanticSearch(e: React.FormEvent) {
    e.preventDefault();
    try {
      const hits = await semanticSearch(actor, searchQuery, 'invoice');
      setSearchHits(hits);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Semantic search failed', true);
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">
              Async Worker Queue &amp; Batch Jobs
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Trigger batch 3-way reconciliation, AP/AR matching, or 13-week liquidity snapshots.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busyJob !== null}
              onClick={() => handleEnqueue('reconcile')}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              <Play className="h-3.5 w-3.5" />
              Run Batch Reconcile Job
            </button>
            <button
              type="button"
              disabled={busyJob !== null}
              onClick={() => handleEnqueue('apar')}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Run AP/AR Job
            </button>
            <button
              type="button"
              disabled={busyJob !== null}
              onClick={() => handleEnqueue('forecast')}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Snapshot 13W Forecast
            </button>
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">
              Controller Close &amp; SOX Exports
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Download audit-ready CSV packets and consolidated JSON close bundles.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() =>
                handleDownload('/api/v1/exports/reconciliation-packet.csv', 'reconciliation-packet.csv')
              }
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50"
            >
              <Download className="h-3.5 w-3.5 text-indigo-600" />
              Reconciliation CSV
            </button>
            <button
              type="button"
              onClick={() =>
                handleDownload('/api/v1/exports/audit-log.csv', 'sox-audit-log.csv')
              }
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50"
            >
              <Download className="h-3.5 w-3.5 text-emerald-600" />
              SOX Audit Log CSV
            </button>
            <button
              type="button"
              onClick={() =>
                handleDownload('/api/v1/exports/cashflow-13w.csv', 'cashflow-13-week.csv')
              }
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50"
            >
              <Download className="h-3.5 w-3.5 text-indigo-600" />
              13-Week Cash CSV
            </button>
            <button
              type="button"
              onClick={() =>
                handleDownload('/api/v1/exports/controller-pack.json', 'controller-pack.json')
              }
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800"
            >
              <Download className="h-3.5 w-3.5" />
              Controller Pack JSON
            </button>
          </div>
        </section>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <form
          onSubmit={handleGlSuggest}
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-3"
        >
          <h3 className="text-sm font-semibold text-slate-900">
            Semantic GL Account Coder
          </h3>
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              type="text"
              value={glVendor}
              onChange={(e) => setGlVendor(e.target.value)}
              placeholder="Vendor name"
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
            <input
              type="text"
              value={glDesc}
              onChange={(e) => setGlDesc(e.target.value)}
              placeholder="Line item description"
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
          </div>
          <button
            type="submit"
            className="rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700"
          >
            Suggest GL Code
          </button>
          {glResult && (
            <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-xs text-indigo-950">
              <strong>{glResult.gl_account}</strong> — {glResult.gl_name} (
              {Math.round(glResult.confidence * 100)}% confidence)
            </div>
          )}
        </form>

        <form
          onSubmit={handleSemanticSearch}
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-3"
        >
          <h3 className="text-sm font-semibold text-slate-900">
            Vector Semantic Invoice Search
          </h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search invoices semantically..."
              className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
            <button
              type="submit"
              className="rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
            >
              Search
            </button>
          </div>
          {searchHits.length > 0 && (
            <ul className="space-y-1.5 text-xs">
              {searchHits.map((hit) => (
                <li
                  key={hit.entity_id}
                  className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-1.5"
                >
                  <span className="truncate text-slate-800">{hit.source_text}</span>
                  <span className="ml-2 font-mono font-semibold text-indigo-700">
                    {Math.round(hit.score * 100)}%
                  </span>
                </li>
              ))}
            </ul>
          )}
        </form>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="border-b border-slate-200 px-5 py-3.5">
          <h3 className="text-sm font-semibold text-slate-900">
            Background Jobs History ({jobs.length})
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-xs">
            <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2.5">Job Type</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Progress</th>
                <th className="px-4 py-2.5">Requested By</th>
                <th className="px-4 py-2.5">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {jobs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                    No background jobs executed yet.
                  </td>
                </tr>
              ) : (
                jobs.map((job) => (
                  <tr key={job.id}>
                    <td className="px-4 py-2.5 font-semibold text-slate-900">{job.job_type}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="px-4 py-2.5 font-mono">{job.progress_pct}%</td>
                    <td className="px-4 py-2.5 text-slate-600">{job.created_by}</td>
                    <td className="px-4 py-2.5 font-mono text-[11px] text-slate-600">
                      {JSON.stringify(job.result)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
