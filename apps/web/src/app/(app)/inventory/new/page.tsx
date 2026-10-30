"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent, type ReactNode } from "react";
import { Button, Card, ErrorBox, Field } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useHydrated } from "@/lib/hydrated";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useConnections, useMe, useShopFeatures } from "@/lib/queries";
import type { CreatedProduct } from "@/lib/types";

type BarcodeMode = "none" | "type" | "internal" | "scale";
interface Attr { name: string; values: string }
const SHOES = "36,37,38,39,40,41,42,43,44,45,46";
const CLOTHES = "S,M,L,XL,XXL";

function Toggle({ on, onChange, children, hint }: { on: boolean; onChange: (v: boolean) => void; children: ReactNode; hint?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)}
      className={cn("flex min-h-14 w-full items-center justify-between gap-3 rounded-2xl border-2 px-4 text-start font-bold transition", on ? "border-brand bg-brandsoft" : "border-line bg-surface")}>
      <span>{children}{hint && <span className="block text-xs font-normal text-soft">{hint}</span>}</span>
      <span aria-hidden className={cn("h-7 w-12 shrink-0 rounded-full p-1 transition", on ? "bg-brand" : "bg-line")}>
        <span className={cn("block size-5 rounded-full bg-white transition", on ? "translate-x-5 rtl:-translate-x-5" : "")} />
      </span>
    </button>
  );
}

export default function NewProductPage() {
  const { t, dir } = useLang();
  void dir;
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const me = useMe();
  const conns = useConnections();
  const cid = conns.data?.find((c) => c.status === "active")?.id;
  const { features } = useShopFeatures(cid);
  const canSeeCost = !!me.data?.permissions.includes("products.cost.view");
  const keyFor = useIdempotencyKey();

  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [category, setCategory] = useState("");
  const [sku, setSku] = useState("");
  const [byWeight, setByWeight] = useState(false);
  const [mode, setMode] = useState<BarcodeMode>("none");
  const [barcode, setBarcode] = useState("");
  const [hasVariants, setHasVariants] = useState(false);
  const [attrs, setAttrs] = useState<Attr[]>([{ name: "", values: "" }]);
  const [lot, setLot] = useState(false);
  const [serial, setSerial] = useState(false);
  const [service, setService] = useState(false);
  const [pos, setPos] = useState(true);
  const [made, setMade] = useState(false);
  const [done, setDone] = useState<CreatedProduct | null>(null);

  const splitValues = (v: string) => v.split(/[,،]/).map((x) => x.trim()).filter(Boolean);
  const combos = hasVariants ? attrs.reduce((n, a) => n * Math.max(1, splitValues(a.values).length), 1) : 1;

  const payload = {
    name: name.trim(), price: Number(price || 0),
    ...(canSeeCost && cost !== "" ? { cost: Number(cost) } : {}),
    kind: service ? "service" : byWeight ? "weight" : "unit",
    ...(mode === "type" && barcode.trim() ? { barcode: barcode.trim() } : {}),
    ...(mode === "internal" ? { auto_barcode: "internal" } : {}),
    ...(mode === "scale" && byWeight ? { auto_barcode: "scale" } : {}),
    ...(category.trim() ? { category: category.trim() } : {}),
    ...(sku.trim() ? { sku: sku.trim() } : {}),
    ...(serial ? { tracking: "serial" } : lot ? { tracking: "lot" } : {}), pos,
    ...(hasVariants ? { variants: attrs.filter((a) => a.name.trim() && splitValues(a.values).length).map((a) => ({ name: a.name.trim(), values: splitValues(a.values) })) } : {}),
  };

  const m = useMutation({
    mutationFn: () => api<CreatedProduct>(`/connections/${cid}/catalog/products`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: (p) => { setDone(p); void qc.invalidateQueries({ queryKey: ["products"] }); },
  });
  const err = m.error instanceof ApiError ? m.error : null;
  const reset = () => {
    // a new product starts from a clean form: nothing from the previous one may leak into it
    setDone(null); setName(""); setPrice(""); setCost(""); setCategory(""); setSku("");
    setByWeight(false); setMode("none"); setBarcode(""); setHasVariants(false);
    setAttrs([{ name: "", values: "" }]); setLot(false); setPos(true); setMade(false);
    m.reset();
  };

  if (done)
    return (
      <div className="rise mx-auto max-w-xl space-y-5">
        <Card className="space-y-3 border-ok/30 bg-oksoft text-center">
          <CheckCircle2 className="pop mx-auto size-12 text-ok" aria-hidden />
          <p className="text-2xl font-black text-ok">{t("np_saved")}</p>
          <p className="font-bold">{done.name}</p>
          {done.barcode && <p className="font-mono text-lg" dir="ltr">{done.barcode}</p>}
          <p className="text-sm text-ok/90">{t("np_verified")}</p>
        </Card>
        <div className="grid gap-3 sm:grid-cols-2">
          <Button onClick={reset}>{t("np_another")}</Button>
          <Link href="/inventory" className="inline-flex min-h-12 items-center justify-center rounded-2xl border border-line font-bold hover:bg-surface2">{t("np_to_list")}</Link>
          {made && features.has("manufacturing") && (
            <Link href={`/inventory/recipe?template=${done.template_id}`} className="inline-flex min-h-12 items-center justify-center rounded-2xl bg-brandsoft font-bold text-brand sm:col-span-2">{t("np_to_recipe")}</Link>
          )}
        </div>
      </div>
    );

  const modes: { id: BarcodeMode; label: string }[] = [
    { id: "none", label: t("np_bc_none") }, { id: "type", label: t("np_bc_type") }, { id: "internal", label: t("np_bc_auto") },
    ...(byWeight ? [{ id: "scale" as const, label: t("np_bc_scale") }] : []),
  ];

  return (
    <form method="post" action="#" className="rise mx-auto max-w-xl space-y-5" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate(); }}>
      <h1 className="text-3xl font-black">{t("np_title")}</h1>
      <Card className="space-y-4">
        <Field label={t("np_name")} name="name" required value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("np_price")} name="price" type="number" inputMode="decimal" min="0" step="0.01" required value={price} onChange={(e) => setPrice(e.target.value)} dir="ltr" />
          {canSeeCost && <Field label={t("np_cost")} name="cost" type="number" inputMode="decimal" min="0" step="0.01" value={cost} onChange={(e) => setCost(e.target.value)} dir="ltr" />}
        </div>
        <Field label={t("np_category")} name="category" value={category} onChange={(e) => setCategory(e.target.value)} />
      </Card>

      {features.has("services") && <Toggle on={service} onChange={(v) => { setService(v); if (v) { setByWeight(false); setLot(false); setSerial(false); } }} hint={t("np_service_hint")}>{t("np_service")}</Toggle>}
      {(features.has("weighing") || byWeight) && !hasVariants && !service && (
        <Toggle on={byWeight} onChange={(v) => { setByWeight(v); if (!v && mode === "scale") setMode("none"); if (v) setMode("scale"); }} hint={t("np_weight_hint")}>{t("np_weight")}</Toggle>
      )}

      {!hasVariants && (
        <Card className="space-y-3">
          <p className="font-bold">{t("np_barcode")}</p>
          <div role="radiogroup" aria-label={t("np_barcode")} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {modes.map((o) => (
              <button type="button" role="radio" aria-checked={mode === o.id} key={o.id} onClick={() => setMode(o.id)}
                className={cn("min-h-12 rounded-2xl border-2 px-2 text-sm font-bold transition", mode === o.id ? "border-brand bg-brandsoft" : "border-line")}>{o.label}</button>
            ))}
          </div>
          {mode === "type" && <Field label={t("np_barcode")} name="barcode" value={barcode} onChange={(e) => setBarcode(e.target.value)} dir="ltr" inputMode="numeric" autoFocus />}
        </Card>
      )}

      {(features.has("variants") || hasVariants) && !byWeight && (
        <>
          <Toggle on={hasVariants} onChange={(v) => { setHasVariants(v); if (v) setMode("none"); }}>{t("np_variants")}</Toggle>
          {hasVariants && (
            <Card className="space-y-4">
              {attrs.map((a, i) => (
                <div key={i} className="space-y-2 rounded-2xl bg-surface2 p-3">
                  <div className="flex gap-2">
                    <input aria-label={t("np_attr_name")} placeholder={t("np_attr_name")} value={a.name} onChange={(e) => setAttrs(attrs.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} className="min-h-11 flex-1 rounded-xl border border-line bg-surface px-3" />
                    {attrs.length > 1 && <button type="button" aria-label="remove" onClick={() => setAttrs(attrs.filter((_, j) => j !== i))} className="grid size-11 place-items-center rounded-xl text-bad hover:bg-badsoft"><Trash2 className="size-5" aria-hidden /></button>}
                  </div>
                  <input aria-label={t("np_attr_values")} placeholder={t("np_attr_values")} value={a.values} onChange={(e) => setAttrs(attrs.map((x, j) => (j === i ? { ...x, values: e.target.value } : x)))} className="min-h-11 w-full rounded-xl border border-line bg-surface px-3" />
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={() => setAttrs(attrs.map((x, j) => (j === i ? { name: x.name || (dir === "rtl" ? "المقاس" : "Size"), values: SHOES } : x)))} className="rounded-full bg-brandsoft px-3 py-1 text-xs font-bold text-brand">{t("np_preset_shoes")}</button>
                    <button type="button" onClick={() => setAttrs(attrs.map((x, j) => (j === i ? { name: x.name || (dir === "rtl" ? "المقاس" : "Size"), values: CLOTHES } : x)))} className="rounded-full bg-brandsoft px-3 py-1 text-xs font-bold text-brand">{t("np_preset_clothes")}</button>
                  </div>
                </div>
              ))}
              <div className="flex items-center justify-between">
                {attrs.length < 3 ? <button type="button" onClick={() => setAttrs([...attrs, { name: "", values: "" }])} className="inline-flex items-center gap-1 text-sm font-bold text-brand"><Plus className="size-4" aria-hidden />{t("np_add_attr")}</button> : <span />}
                <span className={cn("text-sm font-bold", combos > 100 ? "text-bad" : "text-soft")}>{t("np_variants_total")}: {combos}</span>
              </div>
            </Card>
          )}
        </>
      )}

      <div className="space-y-3">
        {features.has("lots") && !serial && !service && <Toggle on={lot} onChange={setLot}>{t("np_lot")}</Toggle>}
        {features.has("serials") && !lot && !service && <Toggle on={serial} onChange={setSerial}>{t("np_serial")}</Toggle>}
        <Toggle on={pos} onChange={setPos}>{t("np_pos")}</Toggle>
        {features.has("manufacturing") && <Toggle on={made} onChange={setMade}>{t("np_made")}</Toggle>}
      </div>

      {err && <ErrorBox message={err.code === "network" ? t("err_network") : err.code === "product_rejected" ? `${errorText(t, err.code)} ${err.message}` : errorText(t, err.code)} reference={err.correlationId} />}
      <Button type="submit" disabled={!hydrated || combos > 100} loading={m.isPending} className="w-full">{t("np_save")}</Button>
      <p className="text-center text-xs text-soft">{t("np_retry_note")}</p>
    </form>
  );
}
