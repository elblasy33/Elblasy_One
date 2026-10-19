"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Factory } from "lucide-react";
import { useState } from "react";
import { InventoryTabs } from "@/components/inv-tabs";
import { Badge, Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection } from "@/lib/queries";
import type { Recipe, ProductionRun } from "@/lib/types";

const n = (v: number) => String(Math.round(v * 100) / 100);

function RecipeCard({ cid, r }: { cid: string; r: Recipe }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const keyFor = useIdempotencyKey();
  const [qty, setQty] = useState(String(r.yield));
  const [done, setDone] = useState(false);
  const payload = { template_id: r.template_id, qty: Number(qty || 0) };
  const m = useMutation({
    mutationFn: () => api(`/connections/${cid}/production/batches`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: () => { setDone(true); void qc.invalidateQueries({ queryKey: ["recipes"] }); void qc.invalidateQueries({ queryKey: ["production-history"] }); void qc.invalidateQueries({ queryKey: ["products"] }); void qc.invalidateQueries({ queryKey: ["stock-overview"] }); },
  });
  const err = m.error instanceof ApiError ? m.error : null;
  const need = (per: number) => per * Number(qty || 0);
  const short = r.components.some((c) => c.on_hand + 1e-9 < need(c.per_unit));
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-lg font-black" dir="auto">{r.name}</p>
        <div className="flex gap-2"><Badge>{t("prod_stock")}: <span dir="ltr">{n(r.on_hand)}</span></Badge><Badge tone={r.can_make > 0 ? "ok" : "warn"}>{t("pr_can_make")}: <span dir="ltr">{n(r.can_make)}</span></Badge></div>
      </div>
      <ul className="text-sm">
        {r.components.map((c) => (
          <li key={c.template_id} className="flex justify-between border-b border-line py-1 last:border-0">
            <span dir="auto">{c.name}</span>
            <span dir="ltr" className={c.on_hand + 1e-9 < need(c.per_unit) ? "font-bold text-bad" : "text-soft"}>{n(need(c.per_unit))} / {n(c.on_hand)}</span>
          </li>
        ))}
      </ul>
      <div className="flex items-end gap-2">
        <label className="flex-1 text-sm font-bold">{t("pr_qty")}
          <input type="number" inputMode="decimal" min="0" step="any" value={qty} onChange={(e) => { setQty(e.target.value); setDone(false); }} dir="ltr" className="mt-1 min-h-12 w-full rounded-2xl border border-line bg-surface px-4 text-lg font-black outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
        </label>
        <Button onClick={() => m.mutate()} disabled={!(Number(qty) > 0) || short} loading={m.isPending} className="min-h-12"><Factory className="size-4" aria-hidden /> {t("pr_make")}</Button>
      </div>
      {short && <p className="text-sm font-bold text-bad">{t("pr_short")}</p>}
      {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${/_rejected$/.test(err.code) ? err.message : ""}`} reference={err.correlationId} />}
      {done && <p role="status" className="flex items-center gap-2 font-bold text-ok"><CheckCircle2 className="size-5" aria-hidden /> {t("pr_done")}</p>}
    </Card>
  );
}

export default function ProductionPage() {
  const { t } = useLang();
  const cid = useActiveConnection().data?.id;
  const recipes = useQuery({ queryKey: ["recipes", cid], queryFn: () => api<{ items: Recipe[] }>(`/connections/${cid}/production/recipes`), enabled: !!cid });
  const hist = useQuery({ queryKey: ["production-history", cid], queryFn: () => api<{ items: ProductionRun[] }>(`/connections/${cid}/production/history`), enabled: !!cid });
  return (
    <div className="rise space-y-5">
      <InventoryTabs />
      <h1 className="flex items-center gap-3 text-3xl font-black"><Factory className="size-8 text-brand" aria-hidden /> {t("pr_title")}</h1>
      {recipes.isLoading && <Spinner label={t("loading")} />}
      {recipes.data && recipes.data.items.length === 0 && <Card className="py-10 text-center"><p className="text-xl font-black">{t("pr_none")}</p><p className="text-soft">{t("pr_none_sub")}</p></Card>}
      {cid && recipes.data?.items.map((r) => <RecipeCard key={r.template_id} cid={cid} r={r} />)}
      {!!hist.data?.items.length && (
        <Card className="space-y-2">
          <h2 className="text-lg font-black">{t("pr_history")}</h2>
          <ul className="divide-y divide-line">{hist.data.items.map((h) => <li key={h.id} className="flex justify-between py-2"><span dir="auto">{h.product}</span><span dir="ltr" className="font-black">+{n(h.qty_produced)} <span className="text-xs font-normal text-soft">{h.name}</span></span></li>)}</ul>
        </Card>
      )}
    </div>
  );
}
