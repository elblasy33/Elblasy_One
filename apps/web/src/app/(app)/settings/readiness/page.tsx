"use client";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, RefreshCw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { Badge, Button, Card, Spinner } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useLang, type TKey } from "@/lib/i18n";
import { useConnections, useReadiness } from "@/lib/queries";
import type { Finding } from "@/lib/types";

const SEV = { critical: "bad", warning: "warn", info: "neutral" } as const;
const SUBS = ["core", "accounting", "inventory", "pos"] as const;
type Rich = Finding & { evidence?: Record<string, unknown>; confidence?: string; verification?: string; auto_remediation_safe?: boolean };

export default function ReadinessPage() {
  const { t } = useLang();
  const qc = useQueryClient();
  const conn = useConnections().data?.find((c) => c.status === "active");
  const cid = conn?.id;
  const r = useReadiness(cid);
  if (!cid || r.isLoading) return <Spinner label={t("loading")} />;
  const d = r.data;
  const findings = (d?.findings ?? []) as Rich[];
  return (
    <div className="rise space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="flex items-center gap-3 text-3xl font-black"><ShieldCheck className="size-8 text-brand" aria-hidden /> {t("rdy_title")}</h1><p className="mt-1 text-soft">{t("rdy_sub")}</p></div>
        <Button variant="soft" loading={r.isFetching} onClick={() => void qc.invalidateQueries({ queryKey: ["readiness", cid] })}><RefreshCw className="size-4" aria-hidden /> {t("rdy_rescan")}</Button>
      </header>
      {d && (
        <>
          <Card className="space-y-2">
            <div className="flex flex-wrap items-center gap-2"><span className="font-bold">{t("rdy_env")}:</span><Badge tone="brand">{t(`env_${d.environment}` as TKey)}</Badge>
              <Badge tone={d.summary.blocking_issues_absent ? "ok" : "bad"}>{d.summary.blocking_issues_absent ? t("rdy_ok") : t("rdy_blocking")}</Badge></div>
            <p className="text-sm text-soft">{t(`env_note_${d.environment}` as TKey)}</p>
          </Card>
          {conn?.mode === "existing" && (
            <Card className="flex flex-wrap items-center justify-between gap-3 border-brand/30 bg-brandsoft">
              <div><p className="font-black">{t("rdy_existing_title")}</p><p className="text-sm text-soft">{t("rdy_existing_sub")}</p></div>
              <Link href="/settings/setup" className="inline-flex min-h-11 items-center gap-2 rounded-2xl bg-brand px-4 font-bold text-brandink hover:brightness-110">{t("rdy_existing_go")} <ArrowRight className="size-4 rtl:rotate-180" aria-hidden /></Link>
            </Card>
          )}
          {findings.length === 0 && <Card className="py-8 text-center text-soft">{t("rdy_none")}</Card>}
          {SUBS.map((sub) => {
            const rows = findings.filter((f) => f.subsystem === sub);
            if (rows.length === 0) return null;
            return (
              <section key={sub} className="space-y-2">
                <h2 className="text-lg font-black">{t(`sub_${sub}` as TKey)}</h2>
                <ul className="space-y-3">
                  {rows.map((f) => (
                    <li key={f.id}><Card className={cn("space-y-2 p-4", f.severity === "critical" && "border-bad/40")}>
                      <div className="flex flex-wrap items-center gap-2"><Badge tone={SEV[f.severity]}>{f.severity}</Badge><Badge>{t(`cls_${f.classification}` as TKey)}</Badge><span className="font-mono text-xs text-soft" dir="ltr">{f.id}</span></div>
                      <p className="font-bold">{f.description}</p>
                      {f.evidence && Object.keys(f.evidence).length > 0 && <p className="break-all rounded-xl bg-surface2 p-2 font-mono text-xs" dir="ltr"><b className="font-sans">{t("rdy_evidence")}: </b>{JSON.stringify(f.evidence)}</p>}
                      <p className="text-sm"><b>{t("rdy_action")}:</b> {f.recommended_action}</p>
                      {f.verification && <p className="text-xs text-soft"><b>{t("rdy_verify")}:</b> {f.verification}</p>}
                      <p className="text-xs text-soft">{t("rdy_conf")}: {f.confidence} · {t("rdy_auto")}: {f.auto_remediation_safe ? "✓" : "✗"}</p>
                    </Card></li>
                  ))}
                </ul>
              </section>
            );
          })}
        </>
      )}
    </div>
  );
}
