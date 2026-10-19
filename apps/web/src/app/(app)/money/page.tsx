"use client";
import { Ban, Banknote, Landmark, Truck, Wallet } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { MoneyTabs } from "@/components/money-tabs";
import { money } from "@/components/receipt";
import { Badge, Card, Spinner } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useLang } from "@/lib/i18n";
import { useActiveConnection, useLedger, useMoneyOverview } from "@/lib/queries";

export default function MoneyPage() {
  const { t } = useLang();
  const cid = useActiveConnection().data?.id;
  const ov = useMoneyOverview(cid);
  const [kind, setKind] = useState<"cash" | "bank">("cash");
  const ledger = useLedger(cid, kind);
  if (!cid || ov.isLoading) return <Spinner label={t("loading")} />;
  const d = ov.data;
  return (
    <div className="rise space-y-5">
      <MoneyTabs />
      <h1 className="flex items-center gap-3 text-3xl font-black"><Landmark className="size-8 text-brand" aria-hidden /> {t("mn_title")}</h1>
      {d && (
        <>
          <section className="grid gap-4 sm:grid-cols-2" aria-label={t("mn_cash_bank")}>
            {d.accounts.map((a) => (
              <Card key={a.journal_id} className="flex items-start gap-3">
                <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-brandsoft text-brand">{a.type === "cash" ? <Wallet className="size-6" aria-hidden /> : <Landmark className="size-6" aria-hidden />}</div>
                <div><p className="font-bold">{a.type === "cash" ? t("mn_cash") : t("mn_bank")} · <span className="text-soft">{a.name}</span></p>
                  <p className={cn("text-3xl font-black", a.balance < 0 && "text-bad")} dir="ltr">{money(a.balance)} <span className="text-sm">{d.currency}</span></p>
                  <p className="mt-1 text-xs text-soft">{t("mn_balance_def")}</p></div>
              </Card>
            ))}
            <Card className="flex items-start gap-3">
              <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-warnsoft text-warn"><Truck className="size-6" aria-hidden /></div>
              <div><p className="font-bold">{t("mn_payables")}</p><p className="text-3xl font-black" dir="ltr">{money(d.payables.total)} <span className="text-sm">{d.currency}</span></p>
                <p className="mt-1 text-xs text-soft">{t("mn_payables_hint")}</p>
                {d.payables.top.slice(0, 3).map((p) => <p key={p.name} className="text-sm" dir="auto">{p.name}: <b dir="ltr">{money(p.owed)}</b></p>)}
                <Link href="/inventory/suppliers" className="mt-1 inline-block text-sm font-bold text-brand">{t("mn_go_suppliers")}</Link></div>
            </Card>
            <Card className="flex items-start gap-3 opacity-90">
              <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-surface2 text-soft"><Ban className="size-6" aria-hidden /></div>
              <div><p className="font-bold">{t("mn_net_profit")}</p><Badge>{t("mn_net_na")}</Badge><p className="mt-1 text-xs text-soft">{t("mn_np_reason")}</p></div>
            </Card>
          </section>

          <Card className="space-y-3">
            <div className="flex items-center justify-between"><h2 className="flex items-center gap-2 text-lg font-black"><Banknote className="size-5 text-accent" aria-hidden /> {t("mn_expenses_month")}</h2>
              <Link href="/money/expenses" className="text-sm font-bold text-brand">{t("mn_go_expenses")}</Link></div>
            <div className="grid grid-cols-3 gap-3 text-center">
              <div><p className="text-xs text-soft">{t("mn_incurred")}</p><p className="text-xl font-black" dir="ltr">{money(d.expenses_month.incurred)}</p></div>
              <div><p className="text-xs text-soft">{t("mn_paid")}</p><p className="text-xl font-black text-ok" dir="ltr">{money(d.expenses_month.paid)}</p></div>
              <div><p className="text-xs text-soft">{t("mn_still_owed")}</p><p className="text-xl font-black text-warn" dir="ltr">{money(d.expenses_month.still_owed)}</p></div>
            </div>
            {Object.keys(d.expenses_month.by_category).length > 0 && (
              <ul className="divide-y divide-line border-t border-line pt-2 text-sm">
                {Object.entries(d.expenses_month.by_category).map(([k, v]) => <li key={k} className="flex justify-between py-1.5"><span dir="auto">{k}</span><b dir="ltr">{money(v)}</b></li>)}
              </ul>
            )}
            <p className="text-xs text-soft">{t("mn_exp_def")}</p>
          </Card>

          <Card className="space-y-3">
            <div className="flex items-center justify-between"><h2 className="text-lg font-black">{t("mn_ledger")}</h2>
              <div role="tablist" className="flex gap-2">{(["cash", "bank"] as const).map((k) => <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)} className={cn("min-h-10 rounded-xl px-3 text-sm font-bold", kind === k ? "bg-brand text-brandink" : "bg-surface2 text-soft")}>{t(k === "cash" ? "mn_cash" : "mn_bank")}</button>)}</div></div>
            {ledger.data && ledger.data.items.length === 0 && <p className="text-soft">{t("mn_no_moves")}</p>}
            <ul className="divide-y divide-line">
              {ledger.data?.items.map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <div className="min-w-0"><p className="truncate font-bold" dir="auto">{r.label ?? r.name}</p><p className="text-xs text-soft" dir="ltr">{r.date} · {r.name}{r.partner ? ` · ${r.partner}` : ""}</p></div>
                  <span className={cn("font-black", r.amount < 0 ? "text-bad" : "text-ok")} dir="ltr">{money(r.amount)}</span>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
