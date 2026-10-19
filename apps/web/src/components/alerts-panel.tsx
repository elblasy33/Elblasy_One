"use client";
import { AlertOctagon, AlertTriangle, BellRing, CheckCircle2, Info } from "lucide-react";
import Link from "next/link";
import { Card } from "@/components/ui";
import { money } from "@/components/receipt";
import { cn } from "@/lib/cn";
import { useLang, type TKey } from "@/lib/i18n";
import { useAlerts } from "@/lib/queries";

const ICON = { critical: AlertOctagon, warning: AlertTriangle, info: Info } as const;
const TONE = { critical: "border-bad/40 bg-badsoft text-bad", warning: "border-warn/40 bg-warnsoft text-warn", info: "border-line bg-surface2 text-soft" } as const;

export function AlertsPanel() {
  const { t } = useLang();
  const a = useAlerts();
  if (!a.data) return null;
  return (
    <section aria-label={t("al_title")} className="space-y-3">
      <h2 className="flex items-center gap-2 text-lg font-black"><BellRing className="size-5 text-accent" aria-hidden /> {t("al_title")}</h2>
      {a.data.items.length === 0 ? (
        <Card className="flex items-center gap-3 text-soft"><CheckCircle2 className="size-5 text-ok" aria-hidden /> {t("al_none")}</Card>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {a.data.items.map((x) => {
            const Icon = ICON[x.severity];
            const amount = typeof x.detail.amount === "number" ? ` · ${money(x.detail.amount)} ${String(x.detail.currency ?? "")}` : "";
            return (
              <li key={x.key}>
                <Link href={x.link} className={cn("flex min-h-16 items-center gap-3 rounded-card border p-4 transition hover:brightness-95", TONE[x.severity])}>
                  <Icon className="size-6 shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1 font-bold text-ink">{t(`al_${x.key}` as TKey)}<span className="block text-xs font-normal text-soft">{x.count}{amount}</span></span>
                  <span className="text-sm font-bold">{t("al_open")}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
