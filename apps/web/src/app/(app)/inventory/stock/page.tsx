"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ClipboardCheck, FileUp, Lightbulb, Package, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { InventoryTabs } from "@/components/inv-tabs";
import { money } from "@/components/receipt";
import { Badge, Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useHydrated } from "@/lib/hydrated";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useMe, usePendingAdjustments, useStock, useSuggestions } from "@/lib/queries";
import type { StockRow } from "@/lib/types";

function Cell({ label, v, tone }: { label: string; v: number | string; tone?: "bad" | "ok" | undefined }) {
  return <div className="text-center"><p className="text-[11px] text-soft">{label}</p><p className={cn("text-lg font-black", tone === "bad" && "text-bad", tone === "ok" && "text-ok")} dir="ltr">{v}</p></div>;
}

function MinEditor({ cid, row }: { cid: string; row: StockRow }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const keyFor = useIdempotencyKey();
  const [v, setV] = useState(row.min !== undefined ? String(row.min) : "");
  const payload = { min_qty: Number(v || 0) };
  const m = useMutation({
    mutationFn: () => api(`/connections/${cid}/stock/products/${row.product_id}/minimum`, { method: "PUT", body: payload, headers: { "Idempotency-Key": keyFor({ id: row.product_id, ...payload }) } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["stock"] }); void qc.invalidateQueries({ queryKey: ["stock-suggestions"] }); void qc.invalidateQueries({ queryKey: ["stock-low-count"] }); },
  });
  return (
    <div className="flex items-center gap-2">
      <input aria-label={`${t("st_set_min")} ${row.name}`} type="number" inputMode="decimal" min="0" step="any" value={v} onChange={(e) => setV(e.target.value)} dir="ltr" className="min-h-10 w-20 rounded-xl border border-line bg-surface px-2 text-center" />
      <button onClick={() => m.mutate()} disabled={v === "" || m.isPending} className="min-h-10 rounded-xl bg-brandsoft px-3 text-sm font-bold text-brand disabled:opacity-50">{t("st_save")}</button>
    </div>
  );
}

function Gate() {
  const lowFromUrl = useSearchParams().get("low") !== null;
  return useHydrated() ? <StockView lowFromUrl={lowFromUrl} /> : <Spinner />;
}

export default function StockPage() {
  return <Suspense fallback={<Spinner />}><Gate /></Suspense>;
}

function StockView({ lowFromUrl }: { lowFromUrl: boolean }) {
  const { t } = useLang();
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe();
  const cid = useActiveConnection().data?.id;
  const can = (p: string) => !!me.data?.permissions.includes(p);
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [low, setLow] = useState(lowFromUrl);
  const [offset, setOffset] = useState(0);
  useEffect(() => { const id = setTimeout(() => { setQ(text.trim()); setOffset(0); }, 300); return () => clearTimeout(id); }, [text]);
  const stock = useStock(cid, q, low, offset);
  const sugg = useSuggestions(cid, can("inventory.adjust") || can("purchasing.view"));
  const pending = usePendingAdjustments(cid, can("inventory.approve"));
  const keyFor = useIdempotencyKey();
  const decide = useMutation({
    mutationFn: ({ id, kind }: { id: string; kind: "approve" | "reject" }) => api(`/connections/${cid}/stock/adjustments/${id}/${kind}`, { method: "POST", ...(kind === "reject" ? { body: {} } : {}), headers: { "Idempotency-Key": keyFor({ id, kind }) } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["stock-pending"] }); void qc.invalidateQueries({ queryKey: ["stock"] }); void qc.invalidateQueries({ queryKey: ["stock-suggestions"] }); },
  });
  const err = decide.error instanceof ApiError ? decide.error : null;
  const prefill = () => {
    sessionStorage.setItem("po-prefill", JSON.stringify((sugg.data?.items ?? []).map((s) => ({ product_id: s.product_id, name: s.name, qty: String(s.suggested_qty) }))));
    router.push("/inventory/purchases/new?prefill=1");
  };
  const d = stock.data;
  const hasValue = d?.items.some((r) => r.value !== undefined);

  return (
    <div className="rise space-y-5">
      <InventoryTabs />
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-3 text-3xl font-black"><Package className="size-8 text-brand" aria-hidden /> {t("st_title")}</h1>
        <div className="flex gap-2">
          {can("inventory.adjust") && <Link href="/inventory/stock/count" className="inline-flex min-h-11 items-center gap-2 rounded-2xl bg-brand px-4 text-sm font-bold text-brandink shadow-card"><ClipboardCheck className="size-4" aria-hidden /> {t("st_count")}</Link>}
          {can("inventory.adjust") && <Link href="/inventory/stock/opening" className="inline-flex min-h-11 items-center gap-2 rounded-2xl border border-line px-4 text-sm font-bold hover:bg-surface2"><FileUp className="size-4" aria-hidden /> {t("st_opening")}</Link>}
        </div>
      </header>

      {pending.data && pending.data.items.length > 0 && (
        <Card className="space-y-3 border-warn/40 bg-warnsoft">
          <h2 className="flex items-center gap-2 text-lg font-black text-warn"><ShieldCheck className="size-5" aria-hidden /> {t("st_pending")}</h2>
          {err && <ErrorBox message={errorText(t, err.code)} reference={err.correlationId} />}
          <ul className="divide-y divide-line/50">
            {pending.data.items.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="text-sm"><p className="font-bold">{p.reason ? t(`rs_${p.reason}` as never) : ""} · {p.lines} {t("st_lines")}</p>
                  <p className="text-soft">{t("st_requested_by")} <span dir="ltr">{p.requested_by}</span> · {t("st_value_change")} <b dir="ltr">{money(p.value_change ?? 0)}</b></p>{p.note && <p className="text-soft" dir="auto">{p.note}</p>}</div>
                <div className="flex gap-2"><Button className="min-h-10 px-4" loading={decide.isPending} onClick={() => decide.mutate({ id: p.id, kind: "approve" })}>{t("st_approve")}</Button>
                  <Button variant="ghost" className="min-h-10 px-4" onClick={() => decide.mutate({ id: p.id, kind: "reject" })}>{t("st_reject")}</Button></div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {sugg.data && sugg.data.items.length > 0 && (
        <Card className="space-y-3">
          <h2 className="flex items-center gap-2 text-lg font-black"><Lightbulb className="size-5 text-accent" aria-hidden /> {t("st_sugg_title")}</h2>
          <p className="text-sm text-soft">{t("st_sugg_note")}</p>
          <ul className="divide-y divide-line">
            {sugg.data.items.map((s) => (
              <li key={s.product_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="font-bold" dir="auto">{s.name}</span>
                <span className="text-sm text-soft">{t("st_forecast")} <b dir="ltr">{s.forecast}</b> / {t("st_min")} <b dir="ltr">{s.min}</b> → {t("st_sugg_qty")} <b className="text-brand" dir="ltr">{s.suggested_qty}</b></span>
              </li>
            ))}
          </ul>
          {can("purchasing.manage") && <Button variant="soft" onClick={prefill}>{t("st_sugg_make")}</Button>}
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <label className="relative block min-w-0 flex-1 basis-64"><span className="sr-only">{t("st_search")}</span>
          <Search className="pointer-events-none absolute start-4 top-1/2 size-5 -translate-y-1/2 text-soft" aria-hidden />
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("st_search")} className="min-h-12 w-full rounded-2xl border border-line bg-surface ps-12 pe-4 outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" /></label>
        <button role="switch" aria-checked={low} onClick={() => { setLow(!low); setOffset(0); }} className={cn("inline-flex min-h-12 items-center gap-2 rounded-2xl border-2 px-4 font-bold", low ? "border-bad bg-badsoft text-bad" : "border-line")}><AlertTriangle className="size-4" aria-hidden /> {t("st_low_only")}</button>
      </div>

      {stock.isLoading && <Spinner label={t("loading")} />}
      {d && d.total === 0 && <Card className="py-10 text-center text-soft">{t("st_none")}</Card>}
      <ul className="space-y-3">
        {d?.items.map((r) => (
          <li key={r.product_id}>
            <Card className={cn("space-y-3 p-4", r.low && "border-bad/40")}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0"><p className="truncate text-lg font-black" dir="auto">{r.name}</p>{r.barcode && <p className="font-mono text-xs text-soft" dir="ltr">{r.barcode}</p>}</div>
                <div className="flex items-center gap-2">{r.low && <Badge tone="bad">{t("st_low")}</Badge>}
                  {r.value !== undefined && <Badge>{t("st_value")} <span dir="ltr">{money(r.value)}</span></Badge>}</div>
              </div>
              <div className="grid grid-cols-4 gap-2">
                <Cell label={t("st_on_hand")} v={r.on_hand} /><Cell label={t("st_free")} v={r.free} /><Cell label={t("st_incoming")} v={r.incoming} /><Cell label={t("st_forecast")} v={r.forecast} tone={r.low ? "bad" : undefined} />
              </div>
              {can("inventory.adjust") && cid && (
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
                  <div className="flex items-center gap-2 text-sm"><span className="font-bold">{t("st_min")}</span><MinEditor cid={cid} row={r} /></div>
                  <Link href={`/inventory/stock/count?product=${r.product_id}`} className="text-sm font-bold text-brand">{t("st_count")}</Link>
                </div>
              )}
            </Card>
          </li>
        ))}
      </ul>
      {hasValue && <p className="text-xs text-soft">{t("st_min_hint")}</p>}
      {d && d.total > 20 && (
        <div className="flex justify-between">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))} className="min-h-11 rounded-2xl border border-line px-4 font-bold disabled:opacity-40">{t("prod_prev")}</button>
          <button disabled={offset + 20 >= d.total} onClick={() => setOffset(offset + 20)} className="min-h-11 rounded-2xl border border-line px-4 font-bold disabled:opacity-40">{t("prod_next")}</button>
        </div>
      )}
    </div>
  );
}
