"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Hourglass, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { InventoryTabs } from "@/components/inv-tabs";
import { Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useHydrated } from "@/lib/hydrated";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang, type TKey } from "@/lib/i18n";
import { useActiveConnection } from "@/lib/queries";
import type { StockRow } from "@/lib/types";

const REASONS = ["count_correction", "damaged", "expired", "lost", "found", "theft"] as const;
interface Line { product_id: number; name: string; system: number; counted: string; tracking: string; lot: string }

function CountForm() {
  const preload = useSearchParams().get("product");
  const { t } = useLang();
  const hydrated = useHydrated();
  const cid = useActiveConnection().data?.id;
  const keyFor = useIdempotencyKey();
  const [text, setText] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [reason, setReason] = useState<(typeof REASONS)[number]>("count_correction");
  const [note, setNote] = useState("");
  const found = useQuery({ queryKey: ["count-search", cid, text.trim()], queryFn: () => api<{ items: StockRow[] }>(`/connections/${cid}/stock/overview?q=${encodeURIComponent(text.trim())}&limit=8`), enabled: !!cid && text.trim().length >= 2 });
  // arriving from a stock row: preload that product
  useEffect(() => {
    if (!preload || !cid) return;
    const id = preload;
    void api<{ items: StockRow[] }>(`/connections/${cid}/stock/overview?limit=100`).then((r) => {
      const p = r.items.find((x) => String(x.product_id) === id);
      if (p) setLines((l) => (l.some((x) => x.product_id === p.product_id) ? l : [...l, { product_id: p.product_id, name: p.name, system: p.on_hand, counted: String(p.on_hand), tracking: p.tracking, lot: "" }]));
    }).catch(() => undefined);
  }, [cid, preload]);
  const payload = { reason, ...(note.trim() ? { note: note.trim() } : {}), lines: lines.map((l) => ({ product_id: l.product_id, counted_qty: Number(l.counted), ...(l.lot.trim() ? { lot_name: l.lot.trim() } : {}) })) };
  const m = useMutation({ mutationFn: () => api<{ status?: string; value_change?: number }>(`/connections/${cid}/stock/adjustments`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }) });
  const err = m.error instanceof ApiError ? m.error : null;
  const valid = lines.length > 0 && lines.every((l) => l.counted !== "" && Number(l.counted) >= 0 && (l.tracking === "none" || !!l.lot.trim()));

  if (m.isSuccess) {
    const waiting = m.data?.status === "awaiting_approval";
    return (
      <div className="rise mx-auto max-w-xl space-y-4">
        <Card className={cn("space-y-2 text-center", waiting ? "border-warn/40 bg-warnsoft" : "border-ok/30 bg-oksoft")}>
          {waiting ? <Hourglass className="mx-auto size-12 text-warn" aria-hidden /> : <CheckCircle2 className="pop mx-auto size-12 text-ok" aria-hidden />}
          <p className="text-xl font-black">{waiting ? t("ct_waiting") : t("ct_applied")}</p>
        </Card>
        <Link href="/inventory/stock" className="inline-flex min-h-12 w-full items-center justify-center rounded-2xl bg-brand font-bold text-brandink">{t("st_title")}</Link>
      </div>
    );
  }
  return (
    <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate(); }} className="rise mx-auto max-w-2xl space-y-5">
      <InventoryTabs />
      <header><h1 className="text-3xl font-black">{t("ct_title")}</h1><p className="mt-1 text-soft">{t("ct_sub")}</p></header>
      <Card className="space-y-3">
        <label className="block text-sm font-bold">{t("ct_search")}
          <input value={text} onChange={(e) => setText(e.target.value)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-4 text-base outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" /></label>
        {text.trim().length >= 2 && found.data && (
          <ul className="divide-y divide-line rounded-2xl border border-line">
            {found.data.items.filter((p) => !lines.some((l) => l.product_id === p.product_id)).map((p) => (
              <li key={p.product_id}><button type="button" onClick={() => { setLines([...lines, { product_id: p.product_id, name: p.name, system: p.on_hand, counted: String(p.on_hand), tracking: p.tracking, lot: "" }]); setText(""); }} className="flex min-h-12 w-full items-center justify-between px-4 text-start hover:bg-surface2">
                <span className="font-bold" dir="auto">{p.name}</span><span className="flex items-center gap-2 text-sm text-soft">{p.on_hand}<Plus className="size-5 text-brand" aria-hidden /></span></button></li>
            ))}
          </ul>
        )}
      </Card>
      {lines.length > 0 && (
        <Card className="space-y-3">
          {lines.map((l, i) => {
            const diff = l.counted === "" ? 0 : Math.round((Number(l.counted) - l.system) * 1000) / 1000;
            return (
              <div key={l.product_id} className="space-y-2 rounded-2xl bg-surface2 p-3">
                <div className="flex items-center justify-between gap-2"><span className="font-bold" dir="auto">{l.name}</span>
                  <button type="button" aria-label="remove" onClick={() => setLines(lines.filter((_, j) => j !== i))} className="grid size-10 place-items-center rounded-xl text-bad hover:bg-badsoft"><Trash2 className="size-4" aria-hidden /></button></div>
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <span>{t("ct_system")}: <b dir="ltr">{l.system}</b></span>
                  <label className="flex items-center gap-2">{t("ct_counted")}
                    <input type="number" inputMode="decimal" min="0" step="any" value={l.counted} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, counted: e.target.value } : x)))} dir="ltr" className="min-h-11 w-24 rounded-xl border border-line bg-surface px-2 text-center text-lg font-bold" /></label>
                  <span className={cn("font-black", diff < 0 && "text-bad", diff > 0 && "text-ok")}>{t("ct_diff")}: <span dir="ltr">{diff > 0 ? `+${diff}` : diff}</span></span>
                  {l.tracking !== "none" && <input aria-label={t("ct_lot")} placeholder={t("ct_lot")} value={l.lot} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, lot: e.target.value } : x)))} dir="ltr" className="min-h-11 flex-1 rounded-xl border border-line bg-surface px-3" />}
                </div>
              </div>
            );
          })}
          <label className="block text-sm font-bold">{t("ct_reason")}
            <select value={reason} onChange={(e) => setReason(e.target.value as (typeof REASONS)[number])} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-3 text-base">
              {REASONS.map((r) => <option key={r} value={r}>{t(`rs_${r}` as TKey)}</option>)}
            </select></label>
          <label className="block text-sm font-bold">{t("ct_note")}
            <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-4 text-base" /></label>
        </Card>
      )}
      {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${/_rejected$/.test(err.code) ? err.message : ""}`} reference={err.correlationId} />}
      <Button type="submit" disabled={!hydrated || !valid} loading={m.isPending} className="w-full">{t("ct_submit")}</Button>
    </form>
  );
}

export default function CountPage() {
  return <Suspense fallback={<Spinner />}><CountForm /></Suspense>;
}
