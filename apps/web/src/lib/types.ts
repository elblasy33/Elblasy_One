// Hand-written mirror of the API contract (to be generated from OpenAPI into packages/api-client).
export type Lang = "ar" | "en";
export type Bilingual = Record<Lang, string>;

export interface Me { id: string; email: string; role: string; tenant_id: string; permissions: string[] }

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
