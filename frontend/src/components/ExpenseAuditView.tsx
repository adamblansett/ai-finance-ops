import { useState } from 'react';
import { Check, PlusCircle, X } from 'lucide-react';
import { decideApproval, formatCurrency, submitExpense } from '../api/client';
import type { ActorContext, ApprovalRequestItem, ExpenseItem } from '../types/finance';
import { StatusBadge } from './StatusBadge';

interface ExpenseAuditViewProps {
  actor: ActorContext;
  expenses: ExpenseItem[];
  approvals: ApprovalRequestItem[];
  onRefresh: () => Promise<void>;
  onNotify: (msg: string, isError?: boolean) => void;
}

export function ExpenseAuditView({
  actor,
  expenses,
  approvals,
  onRefresh,
  onNotify,
}: ExpenseAuditViewProps) {
  const [employeeName, setEmployeeName] = useState('Alex Mercer');
  const [employeeEmail, setEmployeeEmail] = useState('alex@acme-finops.local');
  const [merchant, setMerchant] = useState('Union Grill');
  const [category, setCategory] = useState('meals');
  const [taxCategory, setTaxCategory] = useState('deductible_50');
  const [amount, setAmount] = useState('185.00');
  const [receiptHash, setReceiptHash] = useState('rcpt-demo-2026-x1');
  const [description, setDescription] = useState('Client dinner');
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const approvalMap = new Map(approvals.map((a) => [a.id, a]));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const today = new Date().toISOString().slice(0, 10);
      const created = await submitExpense(actor, {
        employee_name: employeeName,
        employee_email: employeeEmail,
        department: 'Operations',
        merchant,
        expense_date: today,
        category,
        tax_category: taxCategory,
        amount: Number(amount),
        receipt_hash: receiptHash.trim() || null,
        description,
      });
      onNotify(
        `Expense audited (${created.status}) with ${created.policy_violations.length} rule flag(s).`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Expense submission failed', true);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDecision(approvalId: string, decision: 'approved' | 'rejected') {
    setBusyId(approvalId);
    try {
      await decideApproval(actor, approvalId, decision, `Expense ${decision}`);
      onNotify(`Expense ${decision}.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Decision failed', true);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <form
        onSubmit={handleSubmit}
        className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4"
      >
        <div className="flex items-center gap-2">
          <PlusCircle className="h-4 w-4 text-indigo-600" />
          <h2 className="text-sm font-semibold text-slate-900">
            Submit &amp; Audit Employee Expense
          </h2>
        </div>

        <div className="grid gap-3 sm:grid-cols-4">
          <label className="text-xs font-medium text-slate-700">
            Employee Name
            <input
              type="text"
              value={employeeName}
              onChange={(e) => setEmployeeName(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Merchant
            <input
              type="text"
              value={merchant}
              onChange={(e) => setMerchant(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Category
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs"
            >
              <option value="meals">Meals ($150 cap)</option>
              <option value="travel">Travel ($2,500 cap)</option>
              <option value="client_entertainment">Client Entertainment</option>
              <option value="software">Software ($1,000 cap)</option>
              <option value="hardware">Hardware ($3,000 cap)</option>
              <option value="office_supplies">Office Supplies ($500 cap)</option>
            </select>
          </label>
          <label className="text-xs font-medium text-slate-700">
            Tax Category
            <select
              value={taxCategory}
              onChange={(e) => setTaxCategory(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs"
            >
              <option value="deductible_100">100% Deductible</option>
              <option value="deductible_50">50% Deductible (Meals)</option>
              <option value="non_deductible">Non-Deductible (Entertainment)</option>
              <option value="capitalizable">Capitalizable (&gt;= $2,500 HW)</option>
            </select>
          </label>
        </div>

        <div className="grid gap-3 sm:grid-cols-4">
          <label className="text-xs font-medium text-slate-700">
            Amount (USD)
            <input
              type="number"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Receipt Hash (blank to test missing)
            <input
              type="text"
              value={receiptHash}
              onChange={(e) => setReceiptHash(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-xs"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Employee Email
            <input
              type="email"
              value={employeeEmail}
              onChange={(e) => setEmployeeEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
          </label>
          <label className="text-xs font-medium text-slate-700">
            Description
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
          </label>
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {submitting ? 'Auditing...' : 'Submit & Run Policy Engine'}
        </button>
      </form>

      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Audited Expenses ({expenses.length})
        </h3>
        {expenses.map((exp) => {
          const approval = exp.approval_id ? approvalMap.get(exp.approval_id) : undefined;
          const isPending = approval?.status === 'pending';

          return (
            <article
              key={exp.id}
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-2.5"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="text-sm font-semibold text-slate-900">{exp.merchant}</h4>
                    <span className="text-xs text-slate-500">
                      {exp.employee_name} · {exp.department}
                    </span>
                    <StatusBadge status={exp.status} />
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {exp.expense_date} · category: <span className="font-mono">{exp.category}</span>{' '}
                    · tax: <span className="font-mono">{exp.tax_category}</span>
                    {exp.receipt_hash ? ` · receipt: ${exp.receipt_hash}` : ' · no receipt hash'}
                  </p>
                </div>

                <div className="flex items-center gap-3">
                  <span className="font-mono text-sm font-bold text-slate-900">
                    {formatCurrency(exp.amount)}
                  </span>
                  {isPending && approval && (
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        disabled={busyId === approval.id}
                        onClick={() => handleDecision(approval.id, 'approved')}
                        aria-label={`Approve expense ${exp.merchant}`}
                        className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700"
                      >
                        <Check className="h-3.5 w-3.5" />
                        Approve
                      </button>
                      <button
                        type="button"
                        disabled={busyId === approval.id}
                        onClick={() => handleDecision(approval.id, 'rejected')}
                        aria-label={`Reject expense ${exp.merchant}`}
                        className="inline-flex items-center gap-1 rounded-lg border border-rose-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50"
                      >
                        <X className="h-3.5 w-3.5" />
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {exp.policy_violations.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {exp.policy_violations.map((v, idx) => (
                    <span
                      key={`${v.rule_code}-${idx}`}
                      className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] text-amber-900"
                    >
                      <strong>{v.rule_code}:</strong> {v.message}
                    </span>
                  ))}
                </div>
              )}

              <p className="text-xs text-slate-600">{exp.ai_audit_note}</p>
            </article>
          );
        })}
      </section>
    </div>
  );
}
