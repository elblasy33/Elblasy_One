"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, Trash2, UserRound } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { CustomerPicker } from "@/components/customer-picker";
import { money } from "@/components/receipt";
import { Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useHydrated } from "@/lib/hydrated";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useMe } from "@/lib/queries";
import type { Customer, SalesOrder } from "@/lib/types";

interface Line { product_id: number; name: string; qty: string; price: string; discount: string; on_hand: number | null }
interface Found { product_id: number; name: string; price: number; on_hand: number | null }

export default function NewSalesOrderPage() {
  const { t } = useLang();
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const cid = useActiveConnection().data?.id;
  const canOverride = !!useMe().data?.permissions.includes("customers.credit.override");
  const keyFor = useIdempotencyKey();
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [picking, setPicking] = useState(false);
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const [deliver, setDeliver] = useState(true);
  const [invoice, setInvoice] = useState(true);
  const [days, setDays] = useState("30");
  const [override, setOverride] = useState(false);
  const found = useQuery({ queryKey: ["so-products", cid, text.trim()], queryFn: () => api<{ items: Found[] }>(`/connections/${cid}/sales-orders/products?q=${encodeURIComponent(text.trim())}&limit=10`), enabled: !!cid && text.trim().length >= 2 });
  const body = lines.map((l) => ({ product_id: l.product_id, qty: Number(l.qty), price_unit: Number(l.price), discount: Number(l.discount || 0) }));
  const valid = !!customer && lines.length > 0 && lines.every((l) => Number(l.qty) > 0 && l.price !== "" && Number(l.price) >= 0);
  const quote = useQuery({ queryKey: ["so-quote", cid, JSON.stringify(body)], queryFn: () => api<{ untaxed: number; total: number; currency: string }>(`/connections/${cid}/sales-orders/quote`, { body: { lines: body, ...(customer ? { partner_id: customer.id } : {}) } }), enabled: !!cid && valid, placeholderData: (p) => p, retry: false });
  const payload = { partner_id: customer?.id ?? 0, lines: body, deliver_now: deliver, invoice_now: invoice, ...(invoice ? { due_days: Number(days || 0) } : {}), ...(override ? { override_credit_limit: true } : {}) };
  const m = useMutation({
    mutationFn: () => api<{ order: SalesOrder }>(`/connections/${cid}/sales-orders`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["sales-orders-list"] }); void qc.invalidateQueries({ queryKey: ["customers"] }); void qc.invalidateQueries({ queryKey: ["money-overview"] }); },
  });
  const err = m.error instanceof ApiError ? m.error : null;
  const limitHit = err?.code === "credit_limit_exceeded";
  const set = (i: number, k: keyof Line, v: string) => setLines(lines.map((x, j) => (j === i ? { ...x, [k]: v } : x)));

  if (m.data)
    return (
      <div className="rise mx-auto max-w-xl space-y-4">
        <Card className="space-y-2 border-ok/30 bg-oksoft text-center"><CheckCircle2 className="pop mx-auto size-12 text-ok" aria-hidden /><p className="text-2xl font-black text-ok">{t("so_created")}</p><p className="font-bold" dir="ltr">{m.data.order.name} · {money(m.data.order.amount_total)}</p></Card>
        <Link href={`/sales-orders/${m.data.order.id}`} className="inline-flex min-h-12 w-full items-center justify-center rounded-2xl bg-brand font-bold text-brandink">{t("so_open")}</Link>
      </div>
    );
  return (
    <>
    <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate(); }} className="rise mx-auto max-w-2xl space-y-5">
      <h1 className="text-3xl font-black">{t("so_new")}</h1>
      <button type="button" onClick={() => setPicking(true)} className="flex min-h-14 w-full items-center justify-between rounded-2xl border-2 border-line bg-surface px-4 font-bold hover:bg-surface2">
        <span className="flex items-center gap-2"><UserRound className="size-5 text-brand" aria-hidden /> {customer ? customer.name : t("so_pick_customer")}</span>
        {customer?.receivable !== undefined && <span className="text-sm text-soft">{t("cu_owes")}: <b dir="ltr">{money(customer.receivable)}</b></span>}
      </button>
      <Card className="space-y-3">
        <label className="block text-sm font-bold">{t("po_search_product")}
          <input value={text} onChange={(e) => setText(e.target.value)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-4 outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" /></label>
        {text.trim().length >= 2 && found.data && (
          <ul className="divide-y divide-line rounded-2xl border border-line">
            {found.data.items.filter((p) => !lines.some((l) => l.product_id === p.product_id)).map((p) => (
              <li key={p.product_id}><button type="button" onClick={() => { setLines([...lines, { product_id: p.product_id, name: p.name, qty: "1", price: String(p.price), discount: "", on_hand: p.on_hand }]); setText(""); }} className="flex min-h-12 w-full items-center justify-between px-4 text-start hover:bg-surface2">
                <span className="font-bold" dir="auto">{p.name}</span><span className="flex items-center gap-3 text-sm text-soft"><span dir="ltr">{money(p.price)}</span>{p.on_hand !== null && <span dir="ltr">{t("prod_stock")}: {p.on_hand}</span>}<Plus className="size-5 text-brand" aria-hidden /></span></button></li>
            ))}
          </ul>
        )}
      </Card>
      {lines.length > 0 && (
        <Card className="space-y-3">
          <div className="hidden grid-cols-[1fr_5.5rem_7rem_4.5rem_6rem_2.75rem] gap-2 px-1 text-xs font-bold text-soft sm:grid"><span>{t("so_item")}</span><span className="text-center">{t("po_qty")}</span><span className="text-center">{t("so_unit_price")}</span><span className="text-center">{t("pos_discount")} %</span><span className="text-center">{t("po_line_total")}</span><span /></div>
          {lines.map((l, i) => (
            <div key={l.product_id} className="grid grid-cols-2 items-center gap-2 sm:grid-cols-[1fr_5.5rem_7rem_4.5rem_6rem_2.75rem]">
              <span className="col-span-2 min-w-0 sm:col-span-1"><span className="block truncate font-bold" dir="auto">{l.name}</span>{l.on_hand !== null && Number(l.qty) > l.on_hand && <span className="text-xs font-bold text-warn">{t("so_stock_low")} ({l.on_hand})</span>}</span>
              <input aria-label={t("po_qty")} type="number" inputMode="decimal" min="0" step="any" value={l.qty} onChange={(e) => set(i, "qty", e.target.value)} dir="ltr" className="min-h-11 w-full rounded-xl border border-line bg-surface px-2 text-center" />
              <input aria-label={t("so_unit_price")} type="number" inputMode="decimal" min="0" step="any" value={l.price} onChange={(e) => set(i, "price", e.target.value)} dir="ltr" className="min-h-11 w-full rounded-xl border border-line bg-surface px-2 text-center" />
              <input aria-label={t("pos_discount")} type="number" inputMode="decimal" min="0" max="100" step="any" placeholder="0" value={l.discount} onChange={(e) => set(i, "discount", e.target.value)} dir="ltr" className="min-h-11 w-full rounded-xl border border-line bg-surface px-2 text-center" />
              <span className="text-center font-black" dir="ltr">{money(Number(l.qty || 0) * Number(l.price || 0) * (1 - Number(l.discount || 0) / 100))}</span>
              <button type="button" aria-label="remove" onClick={() => setLines(lines.filter((_, j) => j !== i))} className="grid size-11 place-items-center rounded-xl text-bad hover:bg-badsoft"><Trash2 className="size-5" aria-hidden /></button>
            </div>
          ))}
          <div className="space-y-1 border-t border-line pt-3">
            <p className="flex justify-between text-sm text-soft"><span>{t("so_untaxed")}</span><span dir="ltr">{quote.data && valid ? money(quote.data.untaxed) : "…"}</span></p>
            <p className="flex items-baseline justify-between text-2xl font-black"><span>{t("pos_total")}</span><span dir="ltr">{quote.data && valid ? money(quote.data.total) : "…"}</span></p>
            <p className="text-xs text-soft">{t("so_total_note")}</p>
          </div>
        </Card>
      )}
      <Card className="space-y-3">
        <label className="flex items-center gap-3 font-bold"><input type="checkbox" checked={deliver} onChange={(e) => setDeliver(e.target.checked)} className="size-5" /> {t("so_deliver_now")}</label>
        <label className="flex items-center gap-3 font-bold"><input type="checkbox" checked={invoice} onChange={(e) => setInvoice(e.target.checked)} className="size-5" /> {t("so_invoice_now")}</label>
        {invoice && <label className="flex items-center gap-3 text-sm font-bold">{t("so_due_days")}
          <input type="number" inputMode="numeric" min="0" max="365" value={days} onChange={(e) => setDays(e.target.value)} dir="ltr" className="min-h-11 w-24 rounded-xl border border-line bg-surface px-2 text-center" /> {t("so_days")}</label>}
        {limitHit && canOverride && <label className="flex items-center gap-3 font-bold text-warn"><input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} className="size-5" /> {t("pos_override")}</label>}
      </Card>
      {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${["sales_order_rejected", "credit_limit_exceeded", "stock_short", "tracked_delivery"].includes(err.code) ? err.message : ""}`} reference={err.correlationId} />}
      {!hydrated && <Spinner />}
      <Button type="submit" disabled={!hydrated || !valid} loading={m.isPending} className="min-h-14 w-full text-lg">{t("so_create")}</Button>
    </form>
    {picking && cid && <CustomerPicker cid={cid} onPick={(c) => { setCustomer(c); setPicking(false); }} onClose={() => setPicking(false)} />}
    </>
  );
}
