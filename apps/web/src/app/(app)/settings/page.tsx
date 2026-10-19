"use client";
import { ChevronLeft, ChevronRight, History, PlugZap, Wand2 } from "lucide-react";
import Link from "next/link";
import { Badge, Card } from "@/components/ui";
import { useLang } from "@/lib/i18n";
import { useConnections, usePlans } from "@/lib/queries";

export default function SettingsPage() {
  const { t, dir } = useLang();
  const conns = useConnections();
  const conn = conns.data?.find((c) => c.status === "active");
  const plans = usePlans(conn?.id);
  const Chev = dir === "rtl" ? ChevronLeft : ChevronRight;
  return (
    <div className="rise space-y-6">
      <h1 className="text-3xl font-black">{t("nav_settings")}</h1>
      <Card className="space-y-3">
        <div className="flex items-center gap-2 font-black"><PlugZap className="size-5 text-brand" aria-hidden /> {t("settings_conn")}</div>
        {conn ? (
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="ok">{conn.name}</Badge>
            <span className="text-sm text-soft" dir="ltr">{conn.base_url} · {conn.db_name}</span>
          </div>
        ) : (
          <Link href="/settings/connect" className="inline-flex font-bold text-brand">{t("go_connect")}</Link>
        )}
      </Card>
      {conn && (
        <Link href="/settings/setup" className="flex items-center justify-between rounded-card border border-line bg-surface p-5 shadow-card transition hover:border-brand">
          <span className="flex items-center gap-3 font-black"><Wand2 className="size-5 text-accent" aria-hidden /> {t("settings_setup")}</span>
          <Chev className="size-5 text-soft" aria-hidden />
        </Link>
      )}
      {!!plans.data?.length && (
        <Card className="space-y-2">
          <div className="flex items-center gap-2 font-black"><History className="size-5 text-soft" aria-hidden /> {t("settings_plans")}</div>
          <ul className="divide-y divide-line">
            {plans.data.map((p) => (
              <li key={p.id}>
                <Link href={`/settings/plans/${p.id}`} className="flex min-h-12 items-center justify-between gap-3 py-2">
                  <span className="text-sm" dir="ltr">{new Date(p.created_at).toLocaleString()}</span>
                  <Badge tone={p.status === "completed" ? "ok" : p.status === "superseded" ? "neutral" : "warn"}>{p.status}</Badge>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
