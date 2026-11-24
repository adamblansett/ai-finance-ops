interface StatusBadgeProps {
  status: string;
}

const STYLE_MAP: Record<string, string> = {
  ok: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  matched: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  approved: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  auto_approved: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  allocated: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  paid: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  parsed: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  low: 'bg-slate-100 text-slate-700 border-slate-200',
  pending: 'bg-amber-50 text-amber-800 border-amber-200',
  pending_review: 'bg-amber-50 text-amber-800 border-amber-200',
  proposed: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  medium: 'bg-amber-50 text-amber-800 border-amber-200',
  unallocated: 'bg-slate-100 text-slate-700 border-slate-200',
  variance_flagged: 'bg-amber-50 text-amber-800 border-amber-200',
  missing_receipt: 'bg-orange-50 text-orange-800 border-orange-200',
  missing_po: 'bg-rose-50 text-rose-700 border-rose-200',
  duplicate_flagged: 'bg-rose-50 text-rose-700 border-rose-200',
  duplicate_blocked: 'bg-rose-50 text-rose-700 border-rose-200',
  flagged: 'bg-rose-50 text-rose-700 border-rose-200',
  rejected: 'bg-rose-50 text-rose-700 border-rose-200',
  high: 'bg-rose-50 text-rose-700 border-rose-200',
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const normalized = status.toLowerCase();
  const classes =
    STYLE_MAP[normalized] || 'bg-slate-100 text-slate-700 border-slate-200';
  const label = normalized.replace(/_/g, ' ');
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-semibold capitalize ${classes}`}
    >
      {label}
    </span>
  );
}
