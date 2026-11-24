export type ActorRole = 'viewer' | 'analyst' | 'controller' | 'admin';

export interface ActorContext {
  email: string;
  role: ActorRole;
}

export interface HealthStatus {
  status: string;
  service: string;
  app_name: string;
  version: string;
  environment: string;
  llm_provider: string;
  database?: string;
}

export interface OverviewSummary {
  total_cash: number;
  projected_week_13_cash: number;
  estimated_runway_weeks: number | null;
  open_ap_total: number;
  open_ar_total: number;
  pending_approvals_count: number;
  flagged_matches_count: number;
  matched_invoices_count: number;
  flagged_expenses_count: number;
  unallocated_transactions_count: number;
  audit_events_count: number;
  audit_chain_valid: boolean;
}

export type DocType =
  | 'invoice'
  | 'purchase_order'
  | 'goods_receipt'
  | 'bank_statement'
  | 'expense';

export interface IngestedDocument {
  id: string;
  filename: string;
  doc_type: string;
  content_type: string;
  content_sha256: string;
  raw_size_bytes: number;
  parsed_records_count: number;
  duplicate_of_id: string | null;
  status: string;
  summary: Record<string, unknown>;
  uploaded_by: string;
  created_at: string;
}

export interface IngestionResult {
  document: IngestedDocument;
  created_ids: string[];
  reconciled_match_ids: string[];
  message: string;
}

export interface MatchAnomaly {
  code: string;
  severity: 'low' | 'medium' | 'high';
  message: string;
}

export interface ThreeWayMatch {
  id: string;
  invoice_id: string;
  invoice_number: string | null;
  counterparty_name: string | null;
  invoice_total: number | null;
  po_id: string | null;
  po_number: string | null;
  po_total: number | null;
  receipt_id: string | null;
  receipt_number: string | null;
  status: string;
  confidence_score: number;
  price_variance: number;
  price_variance_pct: number;
  qty_variance: number;
  anomalies: MatchAnomaly[];
  ai_explanation: string;
  llm_provider_used: string;
  approval_id: string | null;
  updated_at: string;
}

export interface BankTransaction {
  id: string;
  external_ref: string;
  transaction_date: string;
  description: string;
  normalized_counterparty: string;
  direction: string;
  amount: number;
  currency: string;
  account_name: string;
  status: string;
}

export interface PaymentAllocation {
  id: string;
  bank_transaction_id: string;
  bank_ref: string | null;
  bank_description: string | null;
  invoice_id: string;
  invoice_number: string | null;
  counterparty_name: string | null;
  allocated_amount: number;
  confidence_score: number;
  match_reason: string;
  status: string;
  approval_id: string | null;
  created_at: string;
}

export interface PolicyViolation {
  rule_code: string;
  severity: 'low' | 'medium' | 'high';
  message: string;
}

export interface ExpenseItem {
  id: string;
  employee_name: string;
  employee_email: string;
  department: string;
  merchant: string;
  expense_date: string;
  category: string;
  tax_category: string;
  amount: number;
  currency: string;
  receipt_hash: string | null;
  description: string;
  status: string;
  policy_violations: PolicyViolation[];
  ai_audit_note: string;
  approval_id: string | null;
  created_at: string;
}

export interface ExpenseCreateInput {
  employee_name: string;
  employee_email: string;
  department: string;
  merchant: string;
  expense_date: string;
  category: string;
  tax_category: string;
  amount: number;
  receipt_hash: string | null;
  description: string;
}

export interface ApprovalRequestItem {
  id: string;
  entity_type: string;
  entity_id: string;
  action_requested: string;
  summary: string;
  amount: number;
  risk_level: string;
  status: string;
  requested_by: string;
  decided_by: string | null;
  decision_notes: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface AuditEventItem {
  id: string;
  sequence_no: number;
  event_type: string;
  actor_email: string;
  actor_role: string;
  entity_type: string;
  entity_id: string;
  action: string;
  details: Record<string, unknown>;
  prev_hash: string;
  event_hash: string;
  created_at: string;
}

export interface AuditChainVerify {
  valid: boolean;
  total_events: number;
  head_hash: string;
  broken_sequence_no: number | null;
  message: string;
}

export interface PiiFinding {
  category: string;
  count: number;
  placeholder: string;
}

export interface PiiRedactResult {
  redacted_text: string;
  findings: PiiFinding[];
  total_redactions: number;
}

export interface ForecastScenario {
  ar_collection_rate_pct: number;
  ar_delay_days: number;
  ap_deferral_days: number;
  revenue_growth_pct: number;
  expense_shock_pct: number;
  min_cash_buffer: number;
}

export interface WeeklyCashBucket {
  week_number: number;
  week_start: string;
  week_end: string;
  opening_cash: number;
  ar_inflows: number;
  recurring_inflows: number;
  ap_outflows: number;
  recurring_outflows: number;
  net_cash_flow: number;
  closing_cash: number;
}

export interface ArAgingSummary {
  current: number;
  days_1_30: number;
  days_31_60: number;
  days_61_90: number;
  days_90_plus: number;
  total_open_ar: number;
}

export interface ForecastVariance {
  ending_cash_delta: number;
  lowest_cash_delta: number;
  inflow_delta: number;
  outflow_delta: number;
}

export interface ForecastResponse {
  as_of_date: string;
  starting_cash: number;
  ending_cash_week_13: number;
  lowest_cash_balance: number;
  lowest_cash_week: number;
  total_inflows_13w: number;
  total_outflows_13w: number;
  average_weekly_net_flow: number;
  estimated_runway_weeks: number | null;
  buffer_breach_week: number | null;
  scenario: ForecastScenario;
  variance_vs_baseline: ForecastVariance;
  ar_aging: ArAgingSummary;
  weeks: WeeklyCashBucket[];
  ai_narrative: string;
  llm_provider_used: string;
}

export interface RecurringCommitment {
  id: string;
  name: string;
  counterparty: string;
  direction: 'inflow' | 'outflow';
  category: string;
  amount: number;
  cadence: 'weekly' | 'biweekly' | 'monthly' | 'quarterly';
  next_due_date: string;
  active: boolean;
}

export interface CashAccount {
  id: string;
  account_name: string;
  as_of_date: string;
  balance: number;
  currency: string;
  updated_at: string;
}

export interface SeedSummary {
  seeded: boolean;
  vendors: number;
  purchase_orders: number;
  goods_receipts: number;
  invoices: number;
  three_way_matches: number;
  bank_transactions: number;
  payment_allocations: number;
  expenses: number;
  cash_accounts: number;
  recurring_commitments: number;
  pending_approvals: number;
  message: string;
}
