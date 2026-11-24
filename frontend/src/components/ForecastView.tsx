import { useState } from 'react';
import { RefreshCw, RotateCcw } from 'lucide-react';
import { createCommitment, formatCurrency, runCashflowScenario } from '../api/client';
import type {
  ActorContext,
  ForecastResponse,
  ForecastScenario,
  RecurringCommitment,
} from '../types/finance';

interface ForecastViewProps {
  actor: ActorContext;
  forecast: ForecastResponse | null;
  commitments: RecurringCommitment[];
  onForecastUpdate: (next: ForecastResponse) => void;
  onRefresh: () => Promise<void>;
  onNotify: (msg: string, isError?: boolean) => void;
}

const DEFAULT_SCENARIO: ForecastScenario = {
  ar_collection_rate_pct: 100,
  ar_delay_days: 0,
  ap_deferral_days: 0,
  revenue_growth_pct: 0,
  expense_shock_pct: 0,
  min_cash_buffer: 100000,
};

export function ForecastView({
  actor,
  forecast,
  commitments,
  onForecastUpdate,
  onRefresh,
  onNotify,
}: ForecastViewProps) {
  const [scenario, setScenario] = useState<ForecastScenario>(
    forecast?.scenario || DEFAULT_SCENARIO,
  );
  const [loading, setLoading] = useState(false);

  const [newName, setNewName] = useState('SaaS Renewal Cohort B');
  const [newCounterparty, setNewCounterparty] = useState('Enterprise Customers');
  const [newDirection, setNewDirection] = useState<'inflow' | 'outflow'>('inflow');
  const [newAmount, setNewAmount] = useState('15000');
  const [newCadence, setNewCadence] = useState<'weekly' | 'biweekly' | 'monthly' | 'quarterly'>(
    'monthly',
  );

  async function applyScenario(next: ForecastScenario) {
    setScenario(next);
    setLoading(true);
    try {
      const updated = await runCashflowScenario(actor, next);
      onForecastUpdate(updated);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Scenario modeling failed', true);
    } finally {
      setLoading(false);
    }
  }

  async function handleAddCommitment(e: React.FormEvent) {
    e.preventDefault();
    try {
      const due = new Date(Date.now() + 7 * 86400 * 1000).toISOString().slice(0, 10);
      await createCommitment(actor, {
        name: newName,
        counterparty: newCounterparty,
        direction: newDirection,
        category: newDirection === 'inflow' ? 'revenue' : 'operating_expense',
        amount: Number(newAmount),
        cadence: newCadence,
        next_due_date: due,
      });
      onNotify(`Added recurring ${newDirection} commitment '${newName}'.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to create commitment', true);
    }
  }

  const weeks = forecast?.weeks || [];
  const chartValues = weeks.map((w) => w.closing_cash);
  const minVal = Math.min(0, scenario.min_cash_buffer, ...chartValues);
  const maxVal = Math.max(1, scenario.min_cash_buffer * 1.1, ...chartValues);
  const span = Math.max(1, maxVal - minVal);

  const svgWidth = 680;
  const svgHeight = 200;
  const padX = 28;
  const padY = 18;
  const plotW = svgWidth - padX * 2;
  const plotH = svgHeight - padY * 2;

  const yFor = (val: number) => padY + plotH - ((val - minVal) / span) * plotH;
  const xFor = (idx: number) =>
    weeks.length > 1 ? padX + (idx / (weeks.length - 1)) * plotW : padX;

  const linePath = weeks
    .map((w, idx) => `${idx === 0 ? 'M' : 'L'} ${xFor(idx).toFixed(1)} ${yFor(w.closing_cash).toFixed(1)}`)
    .join(' ');
  const bufferY = yFor(scenario.min_cash_buffer);

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">
              Rolling 13-Week Cash Flow Sensitivity Controls
            </h2>
            <p className="text-xs text-slate-500">
              Adjust collection timing, AP deferral, and burn shocks to stress-test runway.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => applyScenario(DEFAULT_SCENARIO)}
              disabled={loading}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reset Baseline
            </button>
            <button
              type="button"
              onClick={() => applyScenario(scenario)}
              disabled={loading}
              className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
              Run Scenario
            </button>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <label className="text-xs font-medium text-slate-700">
            AR Collection ({scenario.ar_collection_rate_pct}%)
            <input
              type="range"
              min={40}
              max={115}
              step={5}
              value={scenario.ar_collection_rate_pct}
              onChange={(e) =>
                setScenario({ ...scenario, ar_collection_rate_pct: Number(e.target.value) })
              }
              className="mt-1.5 w-full accent-indigo-600"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            AR Delay ({scenario.ar_delay_days}d)
            <input
              type="range"
              min={-14}
              max={45}
              step={7}
              value={scenario.ar_delay_days}
              onChange={(e) =>
                setScenario({ ...scenario, ar_delay_days: Number(e.target.value) })
              }
              className="mt-1.5 w-full accent-indigo-600"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            AP Deferral ({scenario.ap_deferral_days}d)
            <input
              type="range"
              min={-14}
              max={45}
              step={7}
              value={scenario.ap_deferral_days}
              onChange={(e) =>
                setScenario({ ...scenario, ap_deferral_days: Number(e.target.value) })
              }
              className="mt-1.5 w-full accent-indigo-600"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Rev Growth ({scenario.revenue_growth_pct}%)
            <input
              type="range"
              min={-40}
              max={50}
              step={5}
              value={scenario.revenue_growth_pct}
              onChange={(e) =>
                setScenario({ ...scenario, revenue_growth_pct: Number(e.target.value) })
              }
              className="mt-1.5 w-full accent-indigo-600"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Expense Shock ({scenario.expense_shock_pct}%)
            <input
              type="range"
              min={-25}
              max={50}
              step={5}
              value={scenario.expense_shock_pct}
              onChange={(e) =>
                setScenario({ ...scenario, expense_shock_pct: Number(e.target.value) })
              }
              className="mt-1.5 w-full accent-indigo-600"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Min Cash Buffer
            <input
              type="number"
              step={10000}
              value={scenario.min_cash_buffer}
              onChange={(e) =>
                setScenario({ ...scenario, min_cash_buffer: Number(e.target.value) })
              }
              className="mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1 text-xs"
            />
          </label>
        </div>
      </section>

      {forecast && (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs text-slate-500">Week 13 Ending Cash</p>
              <p className="mt-1 text-xl font-bold text-slate-900">
                {formatCurrency(forecast.ending_cash_week_13)}
              </p>
              <p className="mt-0.5 text-[11px] text-slate-500">
                vs Baseline:{' '}
                <span
                  className={
                    forecast.variance_vs_baseline.ending_cash_delta >= 0
                      ? 'font-semibold text-emerald-700'
                      : 'font-semibold text-rose-700'
                  }
                >
                  {forecast.variance_vs_baseline.ending_cash_delta >= 0 ? '+' : ''}
                  {formatCurrency(forecast.variance_vs_baseline.ending_cash_delta)}
                </span>
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs text-slate-500">Lowest Cash Trough</p>
              <p className="mt-1 text-xl font-bold text-slate-900">
                {formatCurrency(forecast.lowest_cash_balance)}
              </p>
              <p className="mt-0.5 text-[11px] text-slate-500">
                Week {forecast.lowest_cash_week} ·{' '}
                {forecast.buffer_breach_week
                  ? `Breaches buffer in Wk ${forecast.buffer_breach_week}`
                  : 'Buffer safe all 13 weeks'}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs text-slate-500">Estimated Runway</p>
              <p className="mt-1 text-xl font-bold text-slate-900">
                {forecast.estimated_runway_weeks !== null
                  ? `${forecast.estimated_runway_weeks} wks`
                  : 'Cash Flow Positive'}
              </p>
              <p className="mt-0.5 text-[11px] text-slate-500">
                Avg weekly net: {formatCurrency(forecast.average_weekly_net_flow)}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs text-slate-500">Open AR Aging Total</p>
              <p className="mt-1 text-xl font-bold text-slate-900">
                {formatCurrency(forecast.ar_aging.total_open_ar)}
              </p>
              <p className="mt-0.5 text-[11px] text-slate-500">
                Current: {formatCurrency(forecast.ar_aging.current)} · Past due:{' '}
                {formatCurrency(
                  forecast.ar_aging.total_open_ar - forecast.ar_aging.current,
                )}
              </p>
            </div>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-900">
                13-Week Closing Cash Trajectory
              </h3>
              <span className="text-[11px] text-slate-500">
                Dashed line = {formatCurrency(scenario.min_cash_buffer)} min buffer
              </span>
            </div>
            <svg
              viewBox={`0 0 ${svgWidth} ${svgHeight}`}
              className="h-52 w-full rounded-lg bg-slate-50"
              role="img"
              aria-label="13-week cash flow chart"
            >
              <line
                x1={padX}
                y1={bufferY}
                x2={svgWidth - padX}
                y2={bufferY}
                stroke="#f59e0b"
                strokeWidth="1.5"
                strokeDasharray="5 4"
              />
              {linePath && (
                <path
                  d={linePath}
                  fill="none"
                  stroke="#4f46e5"
                  strokeWidth="2.5"
                  strokeLinejoin="round"
                />
              )}
              {weeks.map((w, idx) => (
                <g key={w.week_number}>
                  <circle
                    cx={xFor(idx)}
                    cy={yFor(w.closing_cash)}
                    r="3.5"
                    fill={w.closing_cash < scenario.min_cash_buffer ? '#e11d48' : '#4f46e5'}
                  />
                  <text
                    x={xFor(idx)}
                    y={svgHeight - 3}
                    textAnchor="middle"
                    fontSize="9"
                    fill="#64748b"
                  >
                    W{w.week_number}
                  </text>
                </g>
              ))}
            </svg>
            <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
              <strong className="text-slate-900">
                AI Variance Commentary ({forecast.llm_provider_used}):
              </strong>{' '}
              {forecast.ai_narrative}
            </p>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-slate-200 px-5 py-3">
              <h3 className="text-sm font-semibold text-slate-900">Weekly Projection Ledger</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-xs">
                <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Week</th>
                    <th className="px-3 py-2">Window</th>
                    <th className="px-3 py-2">Opening</th>
                    <th className="px-3 py-2">Inflows</th>
                    <th className="px-3 py-2">Outflows</th>
                    <th className="px-3 py-2">Net Flow</th>
                    <th className="px-3 py-2">Closing</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {weeks.map((w) => (
                    <tr key={w.week_number}>
                      <td className="px-3 py-2 font-semibold">W{w.week_number}</td>
                      <td className="px-3 py-2 text-slate-500">
                        {w.week_start} → {w.week_end}
                      </td>
                      <td className="px-3 py-2 font-mono">{formatCurrency(w.opening_cash)}</td>
                      <td className="px-3 py-2 font-mono text-emerald-700">
                        +{formatCurrency(w.ar_inflows + w.recurring_inflows)}
                      </td>
                      <td className="px-3 py-2 font-mono text-rose-700">
                        -{formatCurrency(w.ap_outflows + w.recurring_outflows)}
                      </td>
                      <td className="px-3 py-2 font-mono">
                        {w.net_cash_flow >= 0 ? '+' : ''}
                        {formatCurrency(w.net_cash_flow)}
                      </td>
                      <td className="px-3 py-2 font-mono font-semibold text-slate-900">
                        {formatCurrency(w.closing_cash)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        <h3 className="text-sm font-semibold text-slate-900">
          Recurring Commitments ({commitments.length})
        </h3>
        <form onSubmit={handleAddCommitment} className="grid gap-3 sm:grid-cols-6">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Commitment name"
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs sm:col-span-2"
          />
          <input
            type="text"
            value={newCounterparty}
            onChange={(e) => setNewCounterparty(e.target.value)}
            placeholder="Counterparty"
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
          />
          <select
            value={newDirection}
            onChange={(e) => setNewDirection(e.target.value as 'inflow' | 'outflow')}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
          >
            <option value="inflow">Inflow</option>
            <option value="outflow">Outflow</option>
          </select>
          <select
            value={newCadence}
            onChange={(e) =>
              setNewCadence(
                e.target.value as 'weekly' | 'biweekly' | 'monthly' | 'quarterly',
              )
            }
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
          >
            <option value="weekly">Weekly</option>
            <option value="biweekly">Biweekly</option>
            <option value="monthly">Monthly</option>
            <option value="quarterly">Quarterly</option>
          </select>
          <div className="flex gap-2">
            <input
              type="number"
              value={newAmount}
              onChange={(e) => setNewAmount(e.target.value)}
              className="w-24 rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs"
            />
            <button
              type="submit"
              className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
            >
              Add
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
