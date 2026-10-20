"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, FileText, Truck } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Modal } from "@/components/modal";
import { money } from "@/components/receipt";
import { Badge, Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { PAY_KEY } from "@/lib/purchasing";
import { useActiveConnection, useMe } from "@/lib/queries";
import type { SalesOrder } from "@/lib/types";

function msg(t: ReturnType<typeof useLang>["t"], e: unknown) {
  if (!(e instanceof ApiError)) return null;
  const base = e.code === "network" ? t("err_network") : errorText(t, e.code);
  return { text: ["sales_order_rejected", "credit_limit_exceeded", "stock_short", "tracked_delivery"].includes(e.code) ? `${base} ${e.message}` : base, ref: e.correlationId };
}

export default function SalesOrderPage() {
  const { t } = useLang();
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const cid = useActiveConnection().data?.id;
  const canOverride = !!useMe().data?.permissions.includes("customers.credit.override");
  const keyFor = useIdempotencyKey();
  const [flash, setFlash] = useState<string | null>(null);
  const [inv, setInv] = useState(false);
  const [days, setDays] = useState("30");
  const [override, setOverride] = useState(false);
  const q = useQuery({ queryKey: ["sales-order", cid, id], queryFn: () => api<{ order: SalesOrder }>(`/connections/${cid}/sales-orders/${id}`), enabled: !!cid });
  const done = (text: string) => { setFlash(text); setInv(false); void qc.invalidateQueries({ queryKey: ["sales-order"] }); void qc.invalidateQueries({ queryKey: ["sales-orders-list"] }); void qc.invalidateQueries({ queryKey: ["customers"] }); void qc.invalidateQueries({ queryKey: ["money-overview"] }); };
  const post = (path: string, body?: unknown) => api(`/connections/${cid}/sales-orders/${id}/${path}`, { method: "POST", ...(body !== undefined ? { body } : {}), headers: { "Idempotency-Key": keyFor({ id, path, body, at: q.data?.order.lines.map((l) => [l.delivered, l.invoiced]) }) } });
  const deliver = useMutation({ mutationFn: () => post("deliver"), onSuccess: () => done(t("so_delivered_ok")) });
  const invoice = useMutation({ mutationFn: () => post("invoice", { due_days: Number(days || 0), ...(override ? { override_credit_limit: true } : {}) }), onSuccess: () => done(t("so_invoiced_ok")) });
  const cancel = useMutation({ mutationFn: () => post("cancel"), onSuccess: () => done(t("so_cancelled_ok")) });
  if (!q.data) return <Spinner label={t("loading")} />;
  const o = q.data.order;
  const err = msg(t, deliver.error ?? invoice.error ?? cancel.error);
  const open = o.state !== "cancel";
  const canDeliver = open && o.delivery_status !== "done";
  const canInvoice = open && o.invoice_status === "to invoice";
  const canCancel = open && o.lines.every((l) => l.delivered === 0 && l.invoiced === 0);
  const limitHit = [deliver.error, invoice.error].some((e) => e instanceof ApiError && e.code === "credit_limit_exceeded");
  return (
    <div className="rise space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="text-3xl font-black" dir="ltr">{o.name}</h1><p className="text-soft" dir="auto">{o.partner} · <span dir="ltr">{o.date}</span></p></div>
        <div className="flex flex-wrap items-center gap-2">
          {o.state === "cancel" ? <Badge tone="bad">{t("so_cancelled")}</Badge> : <>
            <Badge tone={o.delivery_status === "done" ? "ok" : "warn"}>{t(o.delivery_status === "done" ? "so_delivered" : "so_not_delivered")}</Badge>
            <Badge tone={o.invoice_status === "invoiced" ? "ok" : "warn"}>{t(o.invoice_status === "invoiced" ? "so_invoiced" : "so_not_invoiced")}</Badge></>}
          <span className="text-2xl font-black" dir="ltr">{money(o.amount_total)}</span>
        </div>
      </header>
      {flash && <div role="status"><Card className="border-ok/30 bg-oksoft font-bold text-ok">{flash}</Card></div>}
      <Card className="space-y-3">
        <div className="hidden grid-cols-[1fr_repeat(3,5rem)_6rem] gap-2 text-xs font-bold text-soft sm:grid"><span>{t("so_item")}</span><span className="text-center">{t("po_ordered")}</span><span className="text-center">{t("so_delivered")}</span><span className="text-center">{t("so_invoiced")}</span><span className="text-center">{t("po_line_total")}</span></div>
        <ul className="divide-y divide-line">
          {o.lines.map((l) => (
            <li key={l.id} className="space-y-1 py-3">
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-[1fr_repeat(3,5rem)_6rem]">
                <span className="col-span-3 font-bold sm:col-span-1" dir="auto">{l.name}</span>
                <b className="text-center" dir="ltr">{l.qty}</b><b className="text-center" dir="ltr">{l.delivered}</b><b className="text-center" dir="ltr">{l.invoiced}</b>
                <b className="text-center" dir="ltr">{money(l.subtotal)}</b>
              </div>
              <p className="text-xs text-soft" dir="ltr">{money(l.price_unit)} × {l.qty}{l.discount ? ` − ${l.discount}%` : ""}</p>
            </li>
          ))}
        </ul>
        <p className="flex justify-between text-sm text-soft"><span>{t("so_untaxed")}</span><span dir="ltr">{money(o.amount_untaxed)}</span></p>
        <p className="flex justify-between text-sm text-soft"><span>{t("pos_tax")}</span><span dir="ltr">{money(o.amount_tax)}</span></p>
      </Card>
      <div className="flex flex-wrap gap-3">
        {canDeliver && <Button loading={deliver.isPending} onClick={() => deliver.mutate()}><Truck className="size-5" aria-hidden /> {t("so_deliver")}</Button>}
        {canInvoice && <Button variant="soft" onClick={() => setInv(true)}><FileText className="size-5" aria-hidden /> {t("so_invoice")}</Button>}
        {canCancel && <Button variant="ghost" loading={cancel.isPending} onClick={() => cancel.mutate()}><Ban className="size-5" aria-hidden /> {t("so_cancel")}</Button>}
      </div>
      {err && <ErrorBox message={err.text} reference={err.ref} />}
      {o.invoices.length > 0 && (
        <Card className="space-y-2">
          <h2 className="text-lg font-black">{t("so_invoices")}</h2>
          <ul className="divide-y divide-line">{o.invoices.map((b) => (
            <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
              <div><p className="font-bold" dir="ltr">{b.name ?? `#${b.id}`}</p><p className="text-xs text-soft" dir="ltr">{b.date} → {b.due}</p></div>
              <div className="flex items-center gap-3"><Badge tone={b.payment_state === "paid" ? "ok" : "warn"}>{t(PAY_KEY[b.payment_state] ?? "pay_st_not_paid")}</Badge><span className="font-black" dir="ltr">{money(b.amount_total)}</span></div>
            </li>))}</ul>
          <Link href={`/money/receivables/${o.partner_id}`} className="inline-block text-sm font-bold text-brand">{t("so_collect")}</Link>
        </Card>
      )}
      {inv && (
        <Modal title={t("so_invoice")} onClose={() => setInv(false)}>
          <div className="space-y-4">
            <label className="flex items-center gap-3 font-bold">{t("so_due_days")}
              <input autoFocus type="number" inputMode="numeric" min="0" max="365" value={days} onChange={(e) => setDays(e.target.value)} dir="ltr" className="min-h-12 w-24 rounded-xl border border-line bg-surface px-2 text-center text-lg" /> {t("so_days")}</label>
            {limitHit && canOverride && <label className="flex items-center gap-3 font-bold text-warn"><input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} className="size-5" /> {t("pos_override")}</label>}
            {invoice.error && <ErrorBox message={msg(t, invoice.error)?.text ?? t("err_generic")} />}
            <Button onClick={() => invoice.mutate()} loading={invoice.isPending} className="min-h-14 w-full">{t("so_invoice")}</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
