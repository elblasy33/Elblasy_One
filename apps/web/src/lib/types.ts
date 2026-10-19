// Hand-written mirror of the API contract (to be generated from OpenAPI into packages/api-client).
export type Lang = "ar" | "en";
export type Bilingual = Record<Lang, string>;

export interface Me { id: string; email: string; role: string; tenant_id: string; permissions: string[]; display_name?: string; active?: boolean; must_change_password?: boolean; last_login_at?: string }

export interface Connection {
  id: string; name: string; base_url: string; db_name: string; status: string;
  odoo_series: string | null; odoo_edition: string | null; compatibility_status: string;
  capabilities: Record<string, boolean> | null; last_health_ok_at: string | null;
}

export interface Question {
  id: string; kind: "choice" | "bool" | "number" | "multi"; text: Bilingual;
  options: string[]; default: unknown; answered: boolean;
}
export interface QuestionnaireOut { questions: Question[]; complete: boolean; profile: Record<string, unknown> | null }

export interface PlanStep {
  key: string; kind: string; title: Bilingual; params: Record<string, unknown>;
  status: "to_apply" | "satisfied" | "blocked"; required: boolean; depends_on: string[];
  approval: string[]; risk: "low" | "medium" | "high"; impact: string; recovery: string;
  blocked_reason: string | null; executable: boolean;
}
export interface PlanBody {
  template: { id: string; version: string }; environment: string; mode: string;
  features: string[]; profile: Record<string, unknown>;
  steps: PlanStep[]; existing_notes: { area: string; note: string }[];
  conflicts: { code: string; reason: string }[]; unsupported: { code: string; reason: string }[];
  required_approvals: string[]; summary: { to_apply: number; satisfied: number; blocked: number };
  applicable: boolean;
}
export type StepRunStatus = "executing" | "succeeded" | "needs_review" | "failed" | "skipped" | "manual_required";
export interface Execution {
  steps: Record<string, { status: StepRunStatus; error?: string; recovery?: string; verified?: boolean }>;
  verification?: { complete: boolean; remaining_steps: string[] };
  error?: string;
}
export interface Plan {
  id: string; connection_id: string; status: string; template: { id: string; version: string };
  approvals: { role: string; at: string }[]; plan: PlanBody; execution: Execution | null; updated_at: string;
}
export interface PlanListItem { id: string; status: string; template: string; created_at: string; summary: PlanBody["summary"] }

export interface Finding {
  id: string; severity: "critical" | "warning" | "info"; subsystem: string; classification: string;
  description: string; recommended_action: string;
}
export interface Readiness {
  environment: string; summary: { total: number; blocking_issues_absent: boolean; by_severity: Record<string, number> };
  findings: Finding[]; scanned_at: string;
}

export interface Product {
  template_id: number; name: string; sku?: string; barcode?: string; price: number; cost?: number;
  category?: string; uom: string; on_hand?: number; tracking: string; variant_count: number;
  by_weight: boolean; in_pos: boolean; managed: boolean; active?: boolean;
}
export interface ProductPage { total: number; items: Product[] }
export interface CreatedProduct { template_id: number; name: string; barcode?: string; variant_count: number; outcome: string; replayed: boolean }
export interface ImportValidation { import_id: string; valid: number; invalid: number; rows: { row: number; ok: boolean; errors: string[] }[] }
export interface ImportResult { created: number; replayed: number; skipped: number; failed: number; rows: { row: number; status: string; errors?: string[] }[] }

export interface SessionView {
  id: number; name: string; state: string; config_id: number; start_cash: number; expected_cash: number;
  counted_cash?: number; cash_difference?: number; opened_at?: string; closed_at?: string; order_count: number; move_state?: string;
}
export interface PosConfig {
  id: number; name: string; session?: SessionView; payment_methods: { id: number; name: string; is_cash: boolean; is_credit?: boolean }[];
}
export interface SalesState { configs: PosConfig[]; currency: string; currency_decimals: number; stock_updates?: string; company?: string }
export interface SaleProduct { product_id: number; name: string; barcode?: string; price: number; on_hand?: number; by_weight: boolean }
export interface QuoteLine { product_id: number; name: string; qty: number; price_unit: number; discount: number; subtotal_incl: number }
export interface Quote { lines: QuoteLine[]; total: number; tax: number; currency: string }
export interface OrderLine { id?: number; refunded_qty?: number; name: string; qty: number; price_unit: number; discount: number; subtotal_incl: number }
export interface OrderView {
  id: number; name: string; state: string; date_order: string; amount_total: number; amount_tax: number;
  amount_paid: number; amount_return: number; lines: OrderLine[]; payments: { method: string; amount: number; is_change: boolean }[];
  refund_of?: number;
}
export interface Receipt {
  company?: string; reference: string; date: string; cashier: string; lines: OrderLine[]; total: number; tax: number;
  paid: number; change: number; payments: { method: string; amount: number }[]; customer?: string; on_account?: number;
}
export interface SaleResult { order: OrderView; receipt: Receipt; stock_updated: boolean; replayed: boolean }
export interface CloseResult { session: SessionView; cash_difference: number; has_difference: boolean }
export interface DaySummary {
  day: string; orders: number; gross_sales: number; refunds: number; net_sales: number; cash_collected: number;
  currency: string; definition: Record<string, string>;
}

export interface Supplier { id: number; name: string; phone?: string; email?: string; balance?: number }
export interface PoLine { id: number; product_id: number; name: string; ordered: number; received: number; billed: number; price_unit?: number; subtotal?: number; tracking: string }
export interface BillBrief { id: number; name?: string; state: string; payment_state: string; amount_total: number; amount_residual: number; invoice_date?: string }
export interface PurchaseOrder {
  id: number; name: string; state: string; partner_id: number; partner: string; date_order: string;
  amount_total?: number; amount_tax?: number; invoice_status: string; lines: PoLine[];
  pickings: { id: number; name: string; state: string }[]; bills?: BillBrief[];
}
export interface StockLevel { on_hand: number; free: number; incoming: number; outgoing: number; forecast: number }
export interface PurchProduct { product_id: number; name: string; barcode?: string; cost?: number; on_hand?: number; tracking: string }
export interface Statement { supplier: Supplier; bills: BillBrief[]; payments: { id: number; name: string; date: string; amount: number; journal: string; state: string }[] }

export interface StockRow {
  product_id: number; name: string; barcode?: string; on_hand: number; free: number; incoming: number; outgoing: number;
  forecast: number; min?: number; max?: number; low: boolean; cost?: number; value?: number; tracking: string;
}
export interface Suggestion { product_id: number; name: string; forecast: number; on_hand: number; incoming: number; min: number; max: number; suggested_qty: number }
export interface PendingAdjustment { id: string; status: string; requested_by: string; created_at: string; reason?: string; note?: string; lines: number; value_change?: number }
export interface CountPreview { lines: { product_id: number; name: string; current: number; counted: number; diff: number; value_change: number }[]; value_change: number }

export interface ExpenseCategory { id: string; label: string; account_id: number; account: string }
export interface ExpenseRow { id: number; name?: string; state: string; date?: string; partner: string; ref?: string; description?: string; account?: string; amount_total: number; amount_residual: number; payment_state: string; managed: boolean }
export interface ExpenseSummary { from: string; to: string; count: number; incurred: number; paid: number; still_owed: number; by_category: Record<string, number>; currency: string; definition: string }
export interface MoneyOverview {
  currency: string; accounts: { journal_id: number; name: string; type: "cash" | "bank"; balance: number }[];
  payables: { total: number; top: { name: string; owed: number }[] }; definition: Record<string, string>;
  expenses_month: ExpenseSummary; net_profit: { available: boolean; reason: string }; receivables?: Receivables;
}
export interface LedgerRow { id: number; date: string; name: string; label?: string; partner?: string; amount: number; journal: string }
export interface PendingExpense { id: string; requested_by: string; created_at: string; amount?: number; description?: string; paid_now: boolean }

export interface AuditItem { id: number; ts: string; action: string; outcome: string; actor?: string; target_type?: string; target_id?: string; before?: Record<string, unknown>; after?: Record<string, unknown>; correlation_id?: string }
export interface OperationItem { id: string; type: string; status: string; actor: string; created_at: string; updated_at: string; safe_error?: string; verified: boolean; needs_attention: boolean }
export interface AlertItem { key: string; severity: "critical" | "warning" | "info"; count: number; permission: string; link: string; detail: Record<string, unknown> }

export interface Customer { id: number; name: string; phone?: string; email?: string; credit_limit?: number; receivable?: number; available_credit?: number | null }
export interface CustomerInvoice { id: number; name?: string; date?: string; due?: string; amount_total: number; amount_residual: number; payment_state: string; move_type: string }
export interface CustomerStatement { customer: Customer; invoices: CustomerInvoice[]; payments: { id: number; name: string; date: string; amount: number; journal: string }[] }
export interface Receivables { total: number; customers: number; top: { name: string; owed: number }[]; overdue: { count: number; amount: number }; currency: string }

export interface Recipe { template_id: number; name: string; yield: number; uom: string; on_hand: number; can_make: number; components: { template_id: number; name: string; per_unit: number; on_hand: number; uom: string }[] }
export interface ProductionRun { id: number; name: string; state: string; product: string; qty: number; qty_produced: number }

export interface InsightsData {
  currency: string; days: number; sales_by_day: { day: string; net: number }[];
  top_products: { name: string; qty: number; amount: number }[];
  slow_moving?: { days: number; count: number; items: { product_id: number; name: string; qty: number; value: number }[] };
  expiring?: { days: number; count: number; items: { product: string; lot: string; qty: number; expires: string; expired: boolean }[] };
}

export interface ReportSection { total: number; accounts: { code: string; name: string; amount: number }[] }
export interface MoneyReport {
  currency: string; date_from: string; date_to: string; income: ReportSection; cogs: ReportSection; expenses: ReportSection;
  gross_profit: number; net_profit: number; unclosed_sessions: number;
  cash_flow: { journal: string; type: string; opening: number; in: number; out: number; closing: number }[];
}
