"use client";
import { ClipboardList, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { InventoryTabs } from "@/components/inv-tabs";
import { money } from "@/components/receipt";
import { Badge, Card, Spinner } from "@/components/ui";
import { useLang } from "@/lib/i18n";
import { useConnections, useMe, usePurchaseOrders } from "@/lib/queries";
import { receiptState } from "@/lib/purchasing";

export default function PurchasesPage() {
  const { t } = useLang();
  const me = useMe();
  const cid = useConnections().data?.find((c) => c.status === "active")?.id;
  const [offset, setOffset] = useState(0);
  const list = usePurchaseOrders(cid, offset);
  const canManage = !!me.data?.permissions.includes("purchasing.manage");
  return (
    <div className="rise space-y-5">
      <InventoryTabs />
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-3 text-3xl font-black"><ClipboardList className="size-8 text-brand" aria-hidden /> {t("po_title")}</h1>
        {canManage && <Link href="/inventory/purchases/new" className="inline-flex min-h-11 items-center gap-2 rounded-2xl bg-brand px-4 text-sm font-bold text-brandink shadow-card"><Plus className="size-4" aria-hidden /> {t("po_new")}</Link>}
      </header>
      {list.isLoading && <Spinner label={t("loading")} />}
      {list.data && list.data.total === 0 && <Card className="py-12 text-center text-xl font-black">{t("po_none")}</Card>}
      <ul className="space-y-3">
        {list.data?.items.map((o) => {
          const rs = receiptState(o);
          return (
            <li key={o.id}>
              <Link href={`/inventory/purchases/${o.id}`} className="block">
                <Card className="flex flex-wrap items-center justify-between gap-3 p-4 transition hover:border-brand">
                  <div><p className="font-black" dir="ltr">{o.name}</p><p className="text-sm text-soft">{o.partner}</p></div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={rs === "full" ? "ok" : rs === "part" ? "warn" : "neutral"}>{t(rs === "full" ? "po_st_full" : rs === "part" ? "po_st_part" : "po_st_none")}</Badge>
                    {o.invoice_status === "invoiced" ? <Badge tone="ok">{t("po_bill_done")}</Badge> : o.invoice_status === "to invoice" ? <Badge tone="warn">{t("po_bill_to")}</Badge> : null}
                    {o.amount_total !== undefined && <span className="font-black" dir="ltr">{money(o.amount_total)}</span>}
                  </div>
                </Card>
              </Link>
            </li>
          );
        })}
      </ul>
      {list.data && list.data.total > 20 && (
        <div className="flex justify-between">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))} className="min-h-11 rounded-2xl border border-line px-4 font-bold disabled:opacity-40">{t("prod_prev")}</button>
          <button disabled={offset + 20 >= list.data.total} onClick={() => setOffset(offset + 20)} className="min-h-11 rounded-2xl border border-line px-4 font-bold disabled:opacity-40">{t("prod_next")}</button>
        </div>
      )}
    </div>
  );
}
