"use client";
import { Download, ScrollText } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Badge, Card, Spinner } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useLang, type TKey } from "@/lib/i18n";
import { useAudit, useOperations } from "@/lib/queries";

const OUTCOME_TONE = { success: "ok", denied: "warn", failure: "bad" } as const;
const STATUSES = ["", "needs_review", "failed", "awaiting_approval", "executing", "succeeded", "rejected"] as const;

function Content() {
  const { t } = useLang();
  const sp = useSearchParams();
  const [tab, setTab] = useState<"log" | "ops">(sp.get("tab") === "operations" ? "ops" : "log");
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [status, setStatus] = useState(sp.get("status") ?? "");
  const [offset, setOffset] = useState(0);
  const q = new URLSearchParams({ limit: "30", offset: String(offset), ...(action ? { action } : {}), ...(outcome ? { outcome } : {}), ...(from ? { from } : {}), ...(to ? { to } : {}) });
  const log = useAudit(q.toString());
  const ops = useOperations(new URLSearchParams({ limit: "30", offset: String(offset), ...(status ? { status } : {}) }).toString());
  const exportQ = new URLSearchParams({ ...(action ? { action } : {}), ...(outcome ? { outcome } : {}), ...(from ? { from } : {}), ...(to ? { to } : {}) }).toString();
  const total = (tab === "log" ? log.data?.total : ops.data?.total) ?? 0;
  const input = "min-h-11 rounded-xl border border-line bg-surface px-3";
  return (
    <div className="rise space-y-5">
      <h1 className="flex items-center gap-3 text-3xl font-black"><ScrollText className="size-8 text-brand" aria-hidden /> {t("au_title")}</h1>
      <div role="tablist" className="flex gap-2">
        {(["log", "ops"] as const).map((k) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => { setTab(k); setOffset(0); }} className={cn("min-h-11 rounded-2xl px-4 font-bold", tab === k ? "bg-brand text-brandink" : "bg-surface2 text-soft")}>{t(k === "log" ? "au_tab_log" : "au_tab_ops")}</button>)}
      </div>
      {tab === "log" ? (
        <>
          <Card className="flex flex-wrap items-end gap-3">
            <label className="text-xs font-bold">{t("au_action")}<input value={action} onChange={(e) => { setAction(e.target.value); setOffset(0); }} placeholder={t("au_filter_action")} dir="ltr" className={cn(input, "mt-1 block w-44")} /></label>
            <label className="text-xs font-bold">{t("au_outcome")}<select value={outcome} onChange={(e) => { setOutcome(e.target.value); setOffset(0); }} className={cn(input, "mt-1 block")}><option value="">{t("au_all")}</option>{(["success", "denied", "failure"] as const).map((o) => <option key={o} value={o}>{t(`au_${o}` as TKey)}</option>)}</select></label>
            <label className="text-xs font-bold">{t("ex_date")} ←<input type="date" value={from} onChange={(e) => { setFrom(e.target.value); setOffset(0); }} className={cn(input, "mt-1 block")} dir="ltr" /></label>
            <label className="text-xs font-bold">→<input type="date" value={to} onChange={(e) => { setTo(e.target.value); setOffset(0); }} className={cn(input, "mt-1 block")} dir="ltr" /></label>
            <a href={`/api/audit/export?${exportQ}`} download className="ms-auto inline-flex min-h-11 items-center gap-2 rounded-2xl border border-line px-4 text-sm font-bold hover:bg-surface2"><Download className="size-4" aria-hidden /> {t("au_export")}</a>
          </Card>
          {log.isLoading && <Spinner label={t("loading")} />}
          {log.data?.items.length === 0 && <Card className="py-8 text-center text-soft">{t("au_none")}</Card>}
          <ul className="space-y-2">
            {log.data?.items.map((e) => (
              <li key={e.id}><Card className="space-y-1 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono font-bold" dir="ltr">{e.action}</span>
                  <span className="flex items-center gap-2"><Badge tone={OUTCOME_TONE[e.outcome as keyof typeof OUTCOME_TONE] ?? "neutral"}>{t(`au_${e.outcome}` as TKey)}</Badge><span className="text-xs text-soft" dir="ltr">{new Date(e.ts).toLocaleString()}</span></span></div>
                <p className="text-soft"><span dir="ltr">{e.actor ?? "—"}</span>{e.target_type && <> · {e.target_type} <span dir="ltr">{e.target_id}</span></>}</p>
                {e.after && Object.keys(e.after).length > 0 && <p className="break-all font-mono text-xs text-soft" dir="ltr">{JSON.stringify(e.after)}</p>}
                {e.correlation_id && <p className="font-mono text-[10px] text-soft" dir="ltr">{t("au_ref")}: {e.correlation_id}</p>}
              </Card></li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <Card className="flex flex-wrap items-end gap-3"><label className="text-xs font-bold">{t("au_status")}
            <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className={cn(input, "mt-1 block")}>{STATUSES.map((s) => <option key={s} value={s}>{s ? t(`op_s_${s}` as TKey) : t("au_all")}</option>)}</select></label></Card>
          {ops.isLoading && <Spinner label={t("loading")} />}
          {ops.data?.items.length === 0 && <Card className="py-8 text-center text-soft">{t("au_none")}</Card>}
          <ul className="space-y-2">
            {ops.data?.items.map((o) => (
              <li key={o.id}><Card className={cn("space-y-1 p-3 text-sm", o.needs_attention && "border-warn/50")}>
                <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono font-bold" dir="ltr">{o.type}</span>
                  <Badge tone={o.status === "succeeded" ? "ok" : o.needs_attention ? "bad" : "neutral"}>{t(`op_s_${o.status}` as TKey)}</Badge></div>
                <p className="text-soft"><span dir="ltr">{o.actor}</span> · <span dir="ltr">{new Date(o.created_at).toLocaleString()}</span>{o.verified && " · ✓"}</p>
                {o.safe_error && <p className="text-bad" dir="auto">{o.safe_error}</p>}
                {o.status === "needs_review" && <p className="text-xs text-soft">{t("au_needs_review_hint")}</p>}
              </Card></li>
            ))}
          </ul>
        </>
      )}
      {total > 30 && (
        <div className="flex justify-between">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 30))} className="min-h-11 rounded-2xl border border-line px-4 font-bold disabled:opacity-40">{t("prod_prev")}</button>
          <span className="self-center text-sm text-soft" dir="ltr">{offset + 1}–{Math.min(offset + 30, total)} / {total}</span>
          <button disabled={offset + 30 >= total} onClick={() => setOffset(offset + 30)} className="min-h-11 rounded-2xl border border-line px-4 font-bold disabled:opacity-40">{t("prod_next")}</button>
        </div>
      )}
    </div>
  );
}

export default function AuditPage() {
  return <Suspense fallback={<Spinner />}><Content /></Suspense>;
}
