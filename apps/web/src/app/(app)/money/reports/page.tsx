"use client";
import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { useState } from "react";
import { MoneyTabs } from "@/components/money-tabs";
import { money } from "@/components/receipt";
import { Badge, Card, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useLang } from "@/lib/i18n";
import { useActiveConnection } from "@/lib/queries";
import type { MoneyReport } from "@/lib/types";

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function period(kind: "month" | "last" | "year") {
  const now = new Date();
  if (kind === "month") return [iso(new Date(now.getFullYear(), now.getMonth(), 1)), iso(new Date(now.getFullYear(), now.getMonth() + 1, 0))] as const;
  if (kind === "last") return [iso(new Date(now.getFullYear(), now.getMonth() - 1, 1)), iso(new Date(now.getFullYear(), now.getMonth(), 0))] as const;
  return [iso(new Date(now.getFullYear(), 0, 1)), iso(new Date(now.getFullYear(), 11, 31))] as const;
}

function Section({ title, total, accounts, tone }: { title: string; total: number; accounts: MoneyReport["income"]["accounts"]; tone?: string }) {
  return (
    <div className="space-y-1">
      <p className="flex justify-between text-lg font-black"><span>{title}</span><span dir="ltr" className={tone}>{money(total)}</span></p>
      <ul className="text-sm text-soft">{accounts.map((a) => <li key={a.code} className="flex justify-between border-b border-line py-1 last:border-0"><span dir="auto">{a.code} {a.name}</span><span dir="ltr">{money(a.amount)}</span></li>)}</ul>
    </div>
  );
}

export default function ReportsPage() {
  const { t } = useLang();
  const cid = useActiveConnection().data?.id;
  const [kind, setKind] = useState<"month" | "last" | "year">("month");
  const [from, to] = period(kind);
  const r = useQuery({ queryKey: ["money-report", cid, from, to], queryFn: () => api<MoneyReport>(`/connections/${cid}/money/report?from=${from}&to=${to}`), enabled: !!cid });
  const d = r.data;
  return (
    <div className="rise space-y-5">
      <MoneyTabs />
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-3 text-3xl font-black"><BarChart3 className="size-8 text-brand" aria-hidden /> {t("rp_title")}</h1>
        <div role="radiogroup" aria-label={t("rp_period")} className="flex gap-2">
          {(["month", "last", "year"] as const).map((k) => <button key={k} role="radio" aria-checked={kind === k} onClick={() => setKind(k)} className={cn("min-h-11 rounded-2xl border-2 px-4 font-bold", kind === k ? "border-brand bg-brandsoft" : "border-line")}>{t(k === "month" ? "rp_month" : k === "last" ? "rp_last" : "rp_year")}</button>)}
        </div>
      </header>
      {r.isLoading && <Spinner label={t("loading")} />}
      {d && (
        <>
          {d.unclosed_sessions > 0 && <Card className="border-warn/40 bg-warnsoft font-bold">{t("rp_unclosed")} ({d.unclosed_sessions})</Card>}
          <Card className="space-y-4">
            <h2 className="text-xl font-black">{t("rp_income_stmt")} <span className="text-sm font-normal text-soft" dir="ltr">{d.date_from} → {d.date_to}</span></h2>
            <Section title={t("rp_income")} total={d.income.total} accounts={d.income.accounts} />
            <Section title={t("rp_cogs")} total={d.cogs.total} accounts={d.cogs.accounts} />
            <p className="flex justify-between border-t border-line pt-3 text-lg font-black"><span>{t("rp_gross")}</span><span dir="ltr">{money(d.gross_profit)}</span></p>
            <Section title={t("rp_expenses")} total={d.expenses.total} accounts={d.expenses.accounts} />
            <p className="flex items-center justify-between border-t-2 border-ink/20 pt-3 text-2xl font-black"><span>{t("rp_net")}</span><span dir="ltr" className={d.net_profit < 0 ? "text-bad" : "text-ok"}>{money(d.net_profit)} {d.currency}</span></p>
            <p className="text-xs text-soft">{t("rp_def")}</p>
          </Card>
          <Card className="space-y-3">
            <h2 className="text-xl font-black">{t("rp_cash_flow")}</h2>
            {d.cash_flow.length === 0 ? <p className="text-soft">{t("rp_no_flow")}</p> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[28rem] text-sm">
                  <thead className="text-xs text-soft"><tr><th className="py-1 text-start">{t("rp_journal")}</th><th>{t("rp_opening")}</th><th>{t("rp_in")}</th><th>{t("rp_out")}</th><th>{t("rp_closing")}</th></tr></thead>
                  <tbody>{d.cash_flow.map((f) => <tr key={f.journal} className="border-t border-line text-center"><td className="py-2 text-start font-bold" dir="auto">{f.journal} <Badge>{f.type}</Badge></td><td dir="ltr">{money(f.opening)}</td><td dir="ltr" className="text-ok">{money(f.in)}</td><td dir="ltr" className="text-bad">{money(f.out)}</td><td dir="ltr" className="font-black">{money(f.closing)}</td></tr>)}</tbody>
                </table>
              </div>
            )}
            <p className="text-xs text-soft">{t("rp_flow_def")}</p>
          </Card>
        </>
      )}
    </div>
  );
}
