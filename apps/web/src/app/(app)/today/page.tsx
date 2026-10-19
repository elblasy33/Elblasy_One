"use client";
import { ArrowLeft, ArrowRight, BadgeDollarSign, CheckCircle2, HandCoins, PackageMinus, PlugZap, ShieldCheck, Wallet, Wrench } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Badge, Card, Spinner } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useLang } from "@/lib/i18n";
import { useConnections, useHealth, useMe, usePlans, useReadiness } from "@/lib/queries";

function Kpi({ icon, label }: { icon: ReactNode; label: string }) {
  const { t } = useLang();
  return (
    <Card className="flex items-start gap-3 opacity-80">
      <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-surface2 text-soft">{icon}</div>
      <div>
        <p className="font-bold">{label}</p>
        <p className="mt-1 text-xs text-soft">{t("kpi_na")}</p>
      </div>
    </Card>
  );
}

export default function TodayPage() {
  const { t, dir } = useLang();
  const me = useMe();
  const isAdmin = !!me.data?.permissions.some((p) => p === "connections.manage" || p === "config.manage");
  const conns = useConnections(isAdmin);
  const conn = conns.data?.find((c) => c.status === "active");
  const health = useHealth(conn?.id);
  const ready = useReadiness(conn?.id);
  const plans = usePlans(conn?.id);
  const latest = plans.data?.find((p) => p.status !== "superseded");
  const Arrow = dir === "rtl" ? ArrowLeft : ArrowRight;

  let next: { href: string; label: string } | null = null;
  if (isAdmin && conns.isSuccess) {
    if (!conn) next = { href: "/settings/connect", label: t("go_connect") };
    else if (plans.isSuccess && !latest) next = { href: "/settings/setup", label: t("go_setup") };
    else if (latest && latest.status !== "completed") next = { href: `/settings/plans/${latest.id}`, label: t("go_plan") };
  }
  const loading = isAdmin && (conns.isLoading || (!!conn && (plans.isLoading || health.isLoading)));
  const setupDone = latest?.status === "completed";

  return (
    <div className="space-y-6">
      <header className="rise">
        <h1 className="text-3xl font-black">{t("welcome")} 👋</h1>
        <p className="text-soft">{t("today_sub")}</p>
      </header>

      {loading && <Spinner label={t("loading")} />}

      {isAdmin && !loading && (
        <section className="grid gap-4 md:grid-cols-3">
          <Card className="rise space-y-2">
            <div className="flex items-center gap-2 text-soft"><PlugZap className="size-5" aria-hidden /><span className="font-bold">{t("card_connection")}</span></div>
            {conn ? (
              <>
                <Badge tone={health.data?.ok ? "ok" : "bad"}>{health.data?.ok ? t("ok") : t("problem")}</Badge>
                <p className="text-sm text-soft" dir="ltr">Odoo {conn.odoo_series} · {conn.odoo_edition}</p>
              </>
            ) : <Badge tone="warn">—</Badge>}
          </Card>
          <Card className="rise space-y-2">
            <div className="flex items-center gap-2 text-soft"><ShieldCheck className="size-5" aria-hidden /><span className="font-bold">{t("card_ready")}</span></div>
            {ready.data ? (
              <>
                <Badge tone={ready.data.summary.blocking_issues_absent ? "ok" : "bad"}>
                  {ready.data.summary.blocking_issues_absent ? t("no_issues") : t("blocking")}
                </Badge>
                <p className="text-sm text-soft">{t("issues")}: {ready.data.summary.total}</p>
              </>
            ) : <p className="text-sm text-soft">{conn ? t("loading") : "—"}</p>}
          </Card>
          <Card className="rise space-y-2">
            <div className="flex items-center gap-2 text-soft"><Wrench className="size-5" aria-hidden /><span className="font-bold">{t("card_setup")}</span></div>
            <Badge tone={setupDone ? "ok" : latest ? "warn" : "neutral"}>{setupDone ? t("all_set") : latest ? latest.status : "—"}</Badge>
          </Card>
        </section>
      )}

      {next && (
        <Link href={next.href} className={cn("rise pop group flex items-center justify-between gap-4 rounded-card bg-brand p-6 text-brandink shadow-card transition hover:brightness-110")}>
          <div>
            <p className="text-sm font-bold opacity-80">{t("next_step")}</p>
            <p className="text-2xl font-black">{next.label}</p>
          </div>
          <Arrow className="size-8 transition group-hover:translate-x-1 rtl:group-hover:-translate-x-1" aria-hidden />
        </Link>
      )}
      {setupDone && (
        <Card className="rise flex items-center gap-3 border-ok/30 bg-oksoft">
          <CheckCircle2 className="size-7 text-ok" aria-hidden />
          <p className="font-bold text-ok">{t("done_title")}</p>
        </Card>
      )}

      <section className="grid gap-4 sm:grid-cols-2" aria-label="KPIs">
        <Kpi icon={<BadgeDollarSign className="size-6" aria-hidden />} label={t("kpi_sales")} />
        <Kpi icon={<Wallet className="size-6" aria-hidden />} label={t("kpi_cash")} />
        <Kpi icon={<PackageMinus className="size-6" aria-hidden />} label={t("kpi_stock")} />
        <Kpi icon={<HandCoins className="size-6" aria-hidden />} label={t("kpi_payables")} />
      </section>
    </div>
  );
}
