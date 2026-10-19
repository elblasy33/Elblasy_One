"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleDashed, Download, Loader2, PartyPopper, ShieldCheck, XCircle } from "lucide-react";
import { useParams } from "next/navigation";
import { useRef, useState, type ReactNode } from "react";
import { Badge, Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { errorText, keyed, useLang, type TKey } from "@/lib/i18n";
import { useConnections, useMe, usePlan } from "@/lib/queries";
import type { Plan, PlanStep, StepRunStatus } from "@/lib/types";

const RISK: Record<PlanStep["risk"], { tone: "ok" | "warn" | "bad"; key: TKey }> = {
  low: { tone: "ok", key: "risk_low" }, medium: { tone: "warn", key: "risk_medium" }, high: { tone: "bad", key: "risk_high" },
};
const RUN_KEY: Record<StepRunStatus, TKey> = {
  executing: "st_executing", succeeded: "st_succeeded", needs_review: "st_needs_review",
  failed: "st_failed", skipped: "st_skipped", manual_required: "st_manual_required",
};

function RunIcon({ s }: { s?: StepRunStatus }) {
  if (s === "executing") return <Loader2 className="size-5 animate-spin text-brand" aria-hidden />;
  if (s === "succeeded") return <CheckCircle2 className="pop size-5 text-ok" aria-hidden />;
  if (s === "failed") return <XCircle className="size-5 text-bad" aria-hidden />;
  if (s) return <AlertTriangle className="size-5 text-warn" aria-hidden />;
  return <CircleDashed className="size-5 text-soft" aria-hidden />;
}

function StepRow({ step, run }: { step: PlanStep; run?: { status: StepRunStatus; error?: string; recovery?: string } | undefined }) {
  const { t, tr } = useLang();
  const r = RISK[step.risk];
  return (
    <li className="flex gap-3 py-3">
      <div className="pt-0.5"><RunIcon s={run?.status} /></div>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-bold">{tr(step.title)}</span>
          {step.status === "to_apply" && <Badge tone={r.tone}>{t(r.key)}</Badge>}
          {run && <Badge tone={run.status === "succeeded" ? "ok" : run.status === "executing" ? "brand" : "warn"}>{t(RUN_KEY[run.status])}</Badge>}
        </div>
        {step.status !== "satisfied" && <p className="text-sm text-soft">{keyed(t, "impact", step.kind, step.impact)}</p>}
        {step.blocked_reason && (
          <p className="text-sm font-semibold text-bad">{t("blocked_generic")} <span className="font-normal opacity-80" dir="auto">— {step.blocked_reason}</span></p>
        )}
        {run?.error && <p className="text-sm font-semibold text-bad" dir="auto">{run.error}</p>}
        {run?.error && <p className="text-xs text-soft">{keyed(t, "recovery", step.kind, step.recovery)}</p>}
      </div>
    </li>
  );
}

function Section({ title, tone, children }: { title: string; tone?: "attention"; children: ReactNode }) {
  return (
    <Card className={tone === "attention" ? "border-warn/40" : ""}>
      <h2 className="mb-1 text-lg font-black">{title}</h2>
      <ul className="divide-y divide-line">{children}</ul>
    </Card>
  );
}

export default function PlanPage() {
  const { t, tr } = useLang();
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const me = useMe();
  const conns = useConnections();
  const cid = conns.data?.find((c) => c.status === "active")?.id;
  const [starting, setStarting] = useState(false);
  const plan = usePlan(cid, id, starting);
  const dialog = useRef<HTMLDialogElement>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["plan", cid, id] });
  const approve = useMutation({ mutationFn: () => api<Plan>(`/connections/${cid}/setup/plans/${id}/approve`, { method: "POST" }), onSuccess: refresh });
  const run = useMutation({
    mutationFn: () => api(`/connections/${cid}/setup/plans/${id}/execute`, { method: "POST" }),
    onMutate: () => { setStarting(true); dialog.current?.close(); },
    onSuccess: () => { void refresh(); setTimeout(() => setStarting(false), 4000); },
    onError: () => setStarting(false),
  });

  const p = plan.data;
  if (!p) return <Spinner label={t("loading")} />;
  const body = p.plan;
  const steps = body.steps;
  const runOf = (k: string) => p.execution?.steps?.[k];
  const myRole = me.data?.role;
  const approved = new Set(p.approvals.map((a) => a.role));
  const canApprove = p.status === "draft" && !!myRole && body.required_approvals.includes(myRole) && !approved.has(myRole);
  const toApply = steps.filter((s) => s.status === "to_apply");
  const satisfied = steps.filter((s) => s.status === "satisfied");
  const attention = steps.filter((s) => s.status === "blocked" || (s.status === "to_apply" && !s.executable));
  const doable = toApply.filter((s) => s.executable);
  const err = (approve.error ?? run.error) instanceof ApiError ? ((approve.error ?? run.error) as ApiError) : null;
  const executing = p.status === "executing";
  const finished = ["completed", "needs_review", "failed"].includes(p.status);
  const canRun = ["approved", "failed", "needs_review"].includes(p.status);

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <header className="rise flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-black">{t("plan_title")}</h1>
          <p className="mt-1 text-soft">{t("plan_sub")}</p>
        </div>
        <a href={`/api/connections/${cid}/setup/plans/${id}/export`} download className="inline-flex min-h-11 items-center gap-2 rounded-2xl border border-line px-4 text-sm font-bold hover:bg-surface2">
          <Download className="size-4" aria-hidden /> {t("export")}
        </a>
      </header>

      <Card className="space-y-1 bg-surface2 text-sm"><p><b>{t("rdy_env")}:</b> {t(`env_${body.environment}` as TKey)}</p><p className="text-soft">{t(`env_note_${body.environment}` as TKey)}</p></Card>

      {p.status === "completed" && (
        <Card className="rise flex items-center gap-4 border-ok/30 bg-oksoft">
          <PartyPopper className="size-10 text-ok" aria-hidden />
          <div><p className="text-xl font-black text-ok">{t("done_title")}</p><p className="text-sm text-ok/90">{t("done_sub")}</p></div>
        </Card>
      )}
      {(p.status === "needs_review" || p.status === "failed") && (
        <Card className="rise space-y-1 border-warn/40 bg-warnsoft">
          <p className="text-lg font-black text-warn">{p.status === "failed" ? t("failed_title") : t("review_title")}</p>
          <p className="text-sm">{t("rerun_hint")}</p>
          {p.execution?.error && <p className="text-sm font-semibold" dir="auto">{p.execution.error}</p>}
        </Card>
      )}
      {toApply.length === 0 && body.applicable && p.status === "draft" && (
        <Card className="flex items-center gap-3 border-ok/30 bg-oksoft"><CheckCircle2 className="size-6 text-ok" aria-hidden /><p className="font-bold text-ok">{t("nothing_to_do")}</p></Card>
      )}

      {body.required_approvals.length > 0 && !finished && (
        <Card className="flex flex-wrap items-center gap-3">
          <ShieldCheck className="size-5 text-brand" aria-hidden />
          <span className="font-bold">{t("approvals_needed")}:</span>
          {body.required_approvals.map((r) => (
            <Badge key={r} tone={approved.has(r) ? "ok" : "neutral"}>{approved.has(r) ? "✓ " : ""}{t(`role_${r}` as TKey)}</Badge>
          ))}
        </Card>
      )}

      {[...body.conflicts, ...body.unsupported].map((c) => (
        <ErrorBox key={c.code} message={keyed(t, "conflict", c.code, c.reason)} />
      ))}

      {toApply.length > 0 && (
        <Section title={t("to_add")}>
          {toApply.map((s) => <StepRow key={s.key} step={s} run={runOf(s.key)} />)}
        </Section>
      )}
      {attention.some((s) => s.status === "blocked") && (
        <Section title={t("needs_attention")} tone="attention">
          {attention.filter((s) => s.status === "blocked").map((s) => <StepRow key={s.key} step={s} run={runOf(s.key)} />)}
        </Section>
      )}
      {satisfied.length > 0 && (
        <details className="rounded-card border border-line bg-surface p-5 shadow-card">
          <summary className="cursor-pointer text-lg font-black">{t("already_ok")} ({satisfied.length})</summary>
          <ul className="mt-2 divide-y divide-line">
            {satisfied.map((s) => <li key={s.key} className="flex items-center gap-3 py-2"><CheckCircle2 className="size-5 text-ok" aria-hidden /><span className="font-semibold">{tr(s.title)}</span></li>)}
          </ul>
        </details>
      )}
      {body.existing_notes.length > 0 && (
        <Card className="space-y-1 bg-surface2 text-sm text-soft">
          {body.existing_notes.map((n, i) => <p key={i}>• {keyed(t, "note", n.area, n.note)}</p>)}
        </Card>
      )}

      {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}

      <div className="sticky bottom-20 z-10 flex flex-col gap-3 md:static">
        {canApprove && body.applicable && toApply.length > 0 && (
          <Button onClick={() => approve.mutate()} loading={approve.isPending} className="w-full">{t("approve")}</Button>
        )}
        {canRun && doable.length > 0 && (
          <Button onClick={() => dialog.current?.showModal()} loading={executing || run.isPending} className="w-full">
            {executing ? t("running") : t("run")}
          </Button>
        )}
      </div>

      <dialog ref={dialog} className="m-auto w-[min(92vw,28rem)] rounded-[1.5rem] border border-line bg-surface p-6 text-ink shadow-card backdrop:bg-black/40">
        <h2 className="text-xl font-black">{t("run")}</h2>
        <p className="mt-2 text-soft">{t("backup_note")}</p>
        <div className="mt-5 grid grid-cols-2 gap-3">
          <Button variant="ghost" onClick={() => dialog.current?.close()}>{t("cancel")}</Button>
          <Button onClick={() => run.mutate()}>{t("confirm_run")}</Button>
        </div>
      </dialog>
    </div>
  );
}
