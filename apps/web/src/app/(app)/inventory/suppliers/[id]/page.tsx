"use client";
import { useParams } from "next/navigation";
import { InventoryTabs } from "@/components/inv-tabs";
import { money } from "@/components/receipt";
import { Badge, Card, Spinner } from "@/components/ui";
import { useLang } from "@/lib/i18n";
import { PAY_KEY } from "@/lib/purchasing";
import { useConnections, useStatement } from "@/lib/queries";

export default function StatementPage() {
  const { t } = useLang();
  const { id } = useParams<{ id: string }>();
  const cid = useConnections().data?.find((c) => c.status === "active")?.id;
  const st = useStatement(cid, id);
  if (!st.data) return <Spinner label={t("loading")} />;
  const s = st.data;
  return (
    <div className="rise space-y-5">
      <InventoryTabs />
      <header><h1 className="text-3xl font-black">{s.supplier.name}</h1><p className="text-soft">{t("sup_statement")}</p></header>
      <Card className="flex items-baseline justify-between"><span className="font-bold">{t("sup_owed")}</span><span className="text-3xl font-black" dir="ltr">{money(s.supplier.balance ?? 0)}</span></Card>
      <Card className="space-y-2">
        <h2 className="text-lg font-black">{t("sup_bills")}</h2>
        {s.bills.length === 0 ? <p className="text-soft">{t("sup_no_bills")}</p> : (
          <ul className="divide-y divide-line">
            {s.bills.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                <div><p className="font-bold" dir="ltr">{b.name ?? `#${b.id}`}</p><p className="text-xs text-soft" dir="ltr">{b.invoice_date}</p></div>
                <div className="flex items-center gap-3"><Badge tone={b.payment_state === "paid" ? "ok" : "warn"}>{t(PAY_KEY[b.payment_state] ?? "pay_st_not_paid")}</Badge>
                  <span className="font-black" dir="ltr">{money(b.amount_total)}</span>{b.amount_residual > 0 && <span className="text-sm text-soft">({t("po_residual")}: <span dir="ltr">{money(b.amount_residual)}</span>)</span>}</div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="space-y-2">
        <h2 className="text-lg font-black">{t("sup_payments")}</h2>
        {s.payments.length === 0 ? <p className="text-soft">{t("sup_no_pay")}</p> : (
          <ul className="divide-y divide-line">
            {s.payments.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-2 py-3"><div><p className="font-bold" dir="ltr">{p.name}</p><p className="text-xs text-soft" dir="ltr">{p.date} · {p.journal}</p></div><span className="font-black" dir="ltr">{money(p.amount)}</span></li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
