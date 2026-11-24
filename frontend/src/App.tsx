import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  ArrowRightLeft,
  Database,
  FileCheck2,
  FileUp,
  LayoutDashboard,
  Receipt,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import {
  fetchAllocations,
  fetchApprovals,
  fetchAuditEvents,
  fetchBankTransactions,
  fetchCashflowBaseline,
  fetchCommitments,
  fetchDocuments,
  fetchExpenses,
  fetchHealth,
  fetchMatches,
  fetchOverview,
  seedDemoData,
  verifyAuditChain,
} from './api/client';
import { ApArView } from './components/ApArView';
import { AuditLogView } from './components/AuditLogView';
import { ExpenseAuditView } from './components/ExpenseAuditView';
import { ForecastView } from './components/ForecastView';
import { IngestionView } from './components/IngestionView';
import { OverviewView } from './components/OverviewView';
import { ReconciliationView } from './components/ReconciliationView';
import type {
  ActorContext,
  ApprovalRequestItem,
  AuditChainVerify,
  AuditEventItem,
  BankTransaction,
  ExpenseItem,
  ForecastResponse,
  HealthStatus,
  IngestedDocument,
  OverviewSummary,
  PaymentAllocation,
  RecurringCommitment,
  ThreeWayMatch,
} from './types/finance';

const NAV_TABS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'ingestion', label: 'Ingestion', icon: FileUp },
  { id: 'reconciliation', label: '3-Way Match', icon: FileCheck2 },
  { id: 'apar', label: 'AP/AR Matching', icon: ArrowRightLeft },
  { id: 'expenses', label: 'Expense Audit', icon: Receipt },
  { id: 'forecast', label: '13-Week Cash Flow', icon: TrendingUp },
  { id: 'audit', label: 'SOX Audit & PII', icon: ShieldCheck },
] as const;

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [offline, setOffline] = useState(false);
  const [activeTab, setActiveTab] = useState<string>('overview');
  const [actor, setActor] = useState<ActorContext>({
    email: 'controller@acme-finops.local',
    role: 'controller',
  });
  const [banner, setBanner] = useState<{ text: string; isError: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const [overview, setOverview] = useState<OverviewSummary | null>(null);
  const [documents, setDocuments] = useState<IngestedDocument[]>([]);
  const [matches, setMatches] = useState<ThreeWayMatch[]>([]);
  const [bankTxs, setBankTxs] = useState<BankTransaction[]>([]);
  const [allocations, setAllocations] = useState<PaymentAllocation[]>([]);
  const [expenses, setExpenses] = useState<ExpenseItem[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequestItem[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEventItem[]>([]);
  const [chainStatus, setChainStatus] = useState<AuditChainVerify | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [commitments, setCommitments] = useState<RecurringCommitment[]>([]);

  const notify = useCallback((text: string, isError = false) => {
    setBanner({ text, isError });
  }, []);

  const refreshWorkspace = useCallback(async () => {
    try {
      const [ov, docs, ms, txs, allocs, exps, apps, evs, chain, fc, comms] =
        await Promise.all([
          fetchOverview(actor),
          fetchDocuments(actor),
          fetchMatches(actor),
          fetchBankTransactions(actor),
          fetchAllocations(actor),
          fetchExpenses(actor),
          fetchApprovals(actor),
          fetchAuditEvents(actor),
          verifyAuditChain(actor),
          fetchCashflowBaseline(actor),
          fetchCommitments(actor),
        ]);
      setOverview(ov);
      setDocuments(docs);
      setMatches(ms);
      setBankTxs(txs);
      setAllocations(allocs);
      setExpenses(exps);
      setApprovals(apps);
      setAuditEvents(evs);
      setChainStatus(chain);
      setForecast(fc);
      setCommitments(comms);
    } catch {
      // Keep UI resilient if secondary APIs are unavailable during offline preview
    }
  }, [actor]);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const h = await fetchHealth();
        if (!cancelled) {
          setHealth(h);
          setOffline(false);
        }
        await refreshWorkspace();
      } catch {
        if (!cancelled) {
          setOffline(true);
        }
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [refreshWorkspace]);

  async function handleLoadDemo(reset = false) {
    setBusy(true);
    try {
      const res = await seedDemoData(actor, reset);
      notify(res.message);
      await refreshWorkspace();
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Demo seed failed', true);
    } finally {
      setBusy(false);
    }
  }

  function handleRoleChange(role: 'controller' | 'analyst') {
    const email =
      role === 'controller'
        ? 'controller@acme-finops.local'
        : 'analyst@acme-finops.local';
    setActor({ email, role });
    notify(`Switched active actor to ${email} (${role}).`);
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">
              Phase 1 — Core Professional &amp; Enterprise Operations
            </p>
            <h1 className="mt-0.5 text-xl font-bold tracking-tight text-slate-900">
              AI Finance Operations
            </h1>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <label className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700">
              <span>Role:</span>
              <select
                aria-label="Actor Role"
                value={actor.role}
                onChange={(e) =>
                  handleRoleChange(e.target.value as 'controller' | 'analyst')
                }
                className="bg-transparent font-semibold text-indigo-700 focus:outline-none"
              >
                <option value="controller">Controller</option>
                <option value="analyst">Analyst</option>
              </select>
            </label>

            <button
              type="button"
              onClick={() => handleLoadDemo(true)}
              disabled={busy || offline}
              className="inline-flex items-center gap-1.5 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
            >
              <Database className="h-3.5 w-3.5" />
              {busy ? 'Loading...' : 'Reset Demo Data'}
            </button>

            <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3.5 py-1.5 text-xs font-medium">
              <Activity
                className={`h-3.5 w-3.5 ${
                  health?.status === 'ok'
                    ? 'text-emerald-600'
                    : offline
                    ? 'text-amber-600'
                    : 'text-slate-400'
                }`}
              />
              <span>
                {health?.status === 'ok'
                  ? `API Healthy (${health.llm_provider})`
                  : offline
                  ? 'Offline Starter Preview'
                  : 'Checking API...'}
              </span>
            </div>
          </div>
        </div>

        <nav
          aria-label="Finance Operations Modules"
          className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-6 pb-2"
        >
          {NAV_TABS.map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition ${
                  active
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {tab.label}
              </button>
            );
          })}
        </nav>
      </header>

      <main className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        {banner && (
          <div
            role="status"
            className={`flex items-center justify-between rounded-xl border px-4 py-2.5 text-xs font-medium ${
              banner.isError
                ? 'border-rose-200 bg-rose-50 text-rose-800'
                : 'border-emerald-200 bg-emerald-50 text-emerald-800'
            }`}
          >
            <span>{banner.text}</span>
            <button
              type="button"
              onClick={() => setBanner(null)}
              className="ml-4 text-xs underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {activeTab === 'overview' && (
          <OverviewView
            overview={overview}
            approvals={approvals}
            onNavigate={setActiveTab}
            onLoadDemo={() => handleLoadDemo(false)}
            busy={busy}
          />
        )}

        {activeTab === 'ingestion' && (
          <IngestionView
            actor={actor}
            documents={documents}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'reconciliation' && (
          <ReconciliationView
            actor={actor}
            matches={matches}
            approvals={approvals}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'apar' && (
          <ApArView
            actor={actor}
            transactions={bankTxs}
            allocations={allocations}
            approvals={approvals}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'expenses' && (
          <ExpenseAuditView
            actor={actor}
            expenses={expenses}
            approvals={approvals}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'forecast' && (
          <ForecastView
            actor={actor}
            forecast={forecast}
            commitments={commitments}
            onForecastUpdate={setForecast}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'audit' && (
          <AuditLogView
            actor={actor}
            events={auditEvents}
            chainStatus={chainStatus}
            onChainVerified={setChainStatus}
            onNotify={notify}
          />
        )}
      </main>
    </div>
  );
}
