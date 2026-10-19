"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { InventoryTabs } from "@/components/inv-tabs";
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
  const valid = !!partner && lines.length > 0 && lines.every((l) => Number(l.qty) > 0);

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
          {lines.map((l, i) => (
            <div key={l.product_id} className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 basis-40 truncate font-bold" dir="auto">{l.name}</span>
              <input aria-label={t("po_qty")} type="number" inputMode="decimal" min="0" step="any" value={l.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} dir="ltr" className="min-h-11 w-24 rounded-xl border border-line bg-surface px-2 text-center" />
              {canPrice && <input aria-label={t("po_price")} type="number" inputMode="decimal" min="0" step="any" value={l.price} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, price: e.target.value } : x)))} dir="ltr" className="min-h-11 w-28 rounded-xl border border-line bg-surface px-2 text-center" />}
              <button type="button" aria-label="remove" onClick={() => setLines(lines.filter((_, j) => j !== i))} className="grid size-11 place-items-center rounded-xl text-bad hover:bg-badsoft"><Trash2 className="size-5" aria-hidden /></button>
            </div>
          ))}
        </Card>
      )}
      {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${err.code === "order_rejected" ? err.message : ""}`} reference={err.correlationId} />}
      <Button type="submit" disabled={!hydrated || !valid} loading={m.isPending} className="w-full">{t("po_create")}</Button>
    </form>
  );
}
