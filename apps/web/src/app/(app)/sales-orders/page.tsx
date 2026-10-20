"use client";
import { useQuery } from "@tanstack/react-query";
import { FileText, Plus } from "lucide-react";
import Link from "next/link";
import { money } from "@/components/receipt";
import { Badge, Card, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { useActiveConnection } from "@/lib/queries";
import type { SalesOrder } from "@/lib/types";

export const SO_TONE = { done: "ok", waiting: "warn", none: "neutral" } as const;

export default function SalesOrdersPage() {
  const { t } = useLang();
  const cid = useActiveConnection().data?.id;
  const list = useQuery({ queryKey: ["sales-orders-list", cid], queryFn: () => api<{ total: number; items: SalesOrder[] }>(`/connections/${cid}/sales-orders?limit=50`), enabled: !!cid });
  return (
    <div className="rise space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="flex items-center gap-3 text-3xl font-black"><FileText className="size-8 text-brand" aria-hidden /> {t("so_title")}</h1><p className="text-soft">{t("so_sub")}</p></div>
        <Link href="/sales-orders/new" className="inline-flex min-h-11 items-center gap-2 rounded-2xl bg-brand px-4 text-sm font-bold text-brandink shadow-card"><Plus className="size-4" aria-hidden /> {t("so_new")}</Link>
      </header>
      {list.isLoading && <Spinner label={t("loading")} />}
      {list.data && list.data.total === 0 && <Card className="py-12 text-center"><p className="text-xl font-black">{t("so_none")}</p><p className="text-soft">{t("so_none_sub")}</p></Card>}
      <ul className="space-y-3">
        {list.data?.items.map((o) => (
          <li key={o.id}><Link href={`/sales-orders/${o.id}`} className="block"><Card className="flex flex-wrap items-center justify-between gap-3 p-4 transition hover:border-brand">
            <div><p className="text-lg font-black" dir="ltr">{o.name}</p><p className="text-sm text-soft" dir="auto">{o.partner} · <span dir="ltr">{o.date}</span></p></div>
            <div className="flex flex-wrap items-center gap-2">
              {o.state === "cancel" ? <Badge tone="bad">{t("so_cancelled")}</Badge> : <>
                <Badge tone={SO_TONE[o.delivery_status]}>{t(o.delivery_status === "done" ? "so_delivered" : "so_not_delivered")}</Badge>
                <Badge tone={o.invoice_status === "invoiced" ? "ok" : "warn"}>{t(o.invoice_status === "invoiced" ? "so_invoiced" : "so_not_invoiced")}</Badge></>}
              <span className="text-lg font-black" dir="ltr">{money(o.amount_total)}</span>
            </div>
          </Card></Link></li>
        ))}
      </ul>
    </div>
  );
}
