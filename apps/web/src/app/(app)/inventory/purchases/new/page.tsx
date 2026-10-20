"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { InventoryTabs } from "@/components/inv-tabs";
import { money } from "@/components/receipt";
import { Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useHydrated } from "@/lib/hydrated";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useMe, useSuppliers } from "@/lib/queries";
import type { PurchaseOrder, PurchProduct } from "@/lib/types";

interface Line { product_id: number; name: string; qty: string; price: string }

function Gate() {
  const prefill = useSearchParams().get("prefill") !== null;
  return useHydrated() ? <NewPurchase prefill={prefill} /> : <Spinner />;
}

export default function NewPurchasePage() {
  return <Suspense fallback={<Spinner />}><Gate /></Suspense>;
}

/** Suggestions from the stock screen arrive as a draft only: the user still picks the supplier and confirms. */
function loadPrefill(wanted: boolean): Line[] {
  if (!wanted) return [];
  try {
    const raw = sessionStorage.getItem("po-prefill");
    sessionStorage.removeItem("po-prefill");
    return raw ? (JSON.parse(raw) as { product_id: number; name: string; qty: string }[]).map((x) => ({ ...x, price: "" })) : [];
  } catch {
    return [];
  }
}

function NewPurchase({ prefill }: { prefill: boolean }) {
  const { t } = useLang();
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const me = useMe();
  const cid = useActiveConnection().data?.id;
  const canPrice = !!me.data?.permissions.includes("products.cost.view");
  const suppliers = useSuppliers(cid, "");
  const [partner, setPartner] = useState<number | null>(null);
  const [lines, setLines] = useState<Line[]>(() => loadPrefill(prefill));
  const [text, setText] = useState("");
  const keyFor = useIdempotencyKey();
  const found = useQuery({
    queryKey: ["po-products", cid, text.trim()],
    queryFn: () => api<{ items: PurchProduct[] }>(`/connections/${cid}/purchasing/products?q=${encodeURIComponent(text.trim())}&limit=10`),
    enabled: !!cid && text.trim().length >= 2,
  });
  const payload = { partner_id: partner ?? 0, lines: lines.map((l) => ({ product_id: l.product_id, qty: Number(l.qty), ...(canPrice && l.price !== "" ? { price_unit: Number(l.price) } : {}) })) };
  const m = useMutation({
    mutationFn: () => api<{ order: PurchaseOrder }>(`/connections/${cid}/purchasing/orders`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["purchase-orders"] }),
  });
  const err = m.error instanceof ApiError ? m.error : null;
  const anyBad = lines.some((l) => !(Number(l.price) > 0));
  const total = lines.reduce((sum, l) => sum + Number(l.qty || 0) * Number(l.price || 0), 0);
  const valid = !!partner && lines.length > 0 && lines.every((l) => Number(l.qty) > 0) && (!canPrice || !anyBad);

  if (m.data)
    return (
      <div className="rise mx-auto max-w-xl space-y-4">
        <Card className="space-y-2 border-ok/30 bg-oksoft text-center"><CheckCircle2 className="pop mx-auto size-12 text-ok" aria-hidden /><p className="text-2xl font-black text-ok">{t("po_created")}</p><p className="font-bold" dir="ltr">{m.data.order.name}</p></Card>
        <Link href={`/inventory/purchases/${m.data.order.id}`} className="inline-flex min-h-12 w-full items-center justify-center rounded-2xl bg-brand font-bold text-brandink">{t("po_receive")}</Link>
      </div>
    );
  return (
    <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate(); }} className="rise mx-auto max-w-2xl space-y-5">
      <InventoryTabs />
      <h1 className="text-3xl font-black">{t("po_new")}</h1>
      <Card className="space-y-3">
        <label className="block text-sm font-bold">{t("po_supplier")}
          <select value={partner ?? ""} onChange={(e) => setPartner(Number(e.target.value) || null)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-3 text-base">
            <option value="">{t("po_pick_supplier")}</option>
            {suppliers.data?.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        {suppliers.data?.total === 0 && <Link href="/inventory/suppliers" className="text-sm font-bold text-brand">{t("sup_add")}</Link>}
      </Card>
      <Card className="space-y-3">
        <label className="block text-sm font-bold">{t("po_search_product")}
          <input value={text} onChange={(e) => setText(e.target.value)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-4 text-base outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
        </label>
        {text.trim().length >= 2 && found.data && (
          <ul className="divide-y divide-line rounded-2xl border border-line">
            {found.data.items.filter((p) => !lines.some((l) => l.product_id === p.product_id)).map((p) => (
              <li key={p.product_id}><button type="button" onClick={() => { setLines([...lines, { product_id: p.product_id, name: p.name, qty: "1", price: p.cost !== undefined ? String(p.cost) : "" }]); setText(""); }} className="flex min-h-12 w-full items-center justify-between px-4 text-start hover:bg-surface2">
                <span className="font-bold" dir="auto">{p.name}</span><Plus className="size-5 text-brand" aria-hidden /></button></li>
            ))}
          </ul>
        )}
      </Card>
      {lines.length > 0 && (
        <Card className="space-y-3">
          <div className="hidden grid-cols-[1fr_6rem_7rem_6rem_2.75rem] gap-2 px-1 text-xs font-bold text-soft sm:grid">
            <span>{t("po_title")}</span><span className="text-center">{t("po_qty")}</span>{canPrice && <span className="text-center">{t("po_price")}</span>}<span className="text-center">{t("po_line_total")}</span><span />
          </div>
          {lines.map((l, i) => {
            const bad = canPrice && !(Number(l.price) > 0);
            return (
              <div key={l.product_id} className="grid grid-cols-2 items-center gap-2 sm:grid-cols-[1fr_6rem_7rem_6rem_2.75rem]">
                <span className="col-span-2 min-w-0 truncate font-bold sm:col-span-1" dir="auto">{l.name}</span>
                <label className="text-[10px] text-soft sm:text-[0px]"><span className="sm:hidden">{t("po_qty")}</span>
                  <input aria-label={t("po_qty")} type="number" inputMode="decimal" min="0" step="any" value={l.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} dir="ltr" className="min-h-11 w-full rounded-xl border border-line bg-surface px-2 text-center text-base text-ink" /></label>
                {canPrice && <label className="text-[10px] text-soft sm:text-[0px]"><span className="sm:hidden">{t("po_price")}</span>
                  <input aria-label={t("po_price")} aria-invalid={bad} type="number" inputMode="decimal" min="0" step="any" placeholder="0.00" value={l.price} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, price: e.target.value } : x)))} dir="ltr" className={`min-h-11 w-full rounded-xl border bg-surface px-2 text-center text-base text-ink ${bad ? "border-bad" : "border-line"}`} /></label>}
                <span className="text-center font-black" dir="ltr">{canPrice ? money(Number(l.qty || 0) * Number(l.price || 0)) : "—"}</span>
                <button type="button" aria-label="remove" onClick={() => setLines(lines.filter((_, j) => j !== i))} className="grid size-11 place-items-center rounded-xl text-bad hover:bg-badsoft"><Trash2 className="size-5" aria-hidden /></button>
              </div>
            );
          })}
          {canPrice && <p className="flex items-baseline justify-between border-t border-line pt-3 text-xl font-black"><span>{t("po_order_total")}</span><span dir="ltr">{money(total)}</span></p>}
          {canPrice && anyBad && <p role="alert" className="text-sm font-bold text-bad">{t("po_price_required")}</p>}
        </Card>
      )}
      {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${err.code === "order_rejected" ? err.message : ""}`} reference={err.correlationId} />}
      <Button type="submit" disabled={!hydrated || !valid} loading={m.isPending} className="w-full">{t("po_create")}</Button>
    </form>
  );
}
