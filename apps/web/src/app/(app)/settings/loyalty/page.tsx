"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gift, Plus } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, ErrorBox, Field, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang, type TKey } from "@/lib/i18n";
import { useActiveConnection, useMe, useProducts } from "@/lib/queries";

type Kind = "points" | "bxgy" | "product_discount" | "order_discount";
interface Program { id: number; name: string; kind: Kind; active: boolean; date_from: string | null; date_to: string | null; points_per_unit?: number; point_value?: number; min_redeem?: number; members?: number; buy?: number; free?: number; product?: string; percent?: number; products?: { id: number; name: string }[]; category?: string | null; minimum_amount?: number }
const KINDS: { k: Kind; title: TKey; sub: TKey; icon: string }[] = [
  { k: "points", title: "lo_points", sub: "lo_points_sub", icon: "⭐" }, { k: "bxgy", title: "lo_bxgy", sub: "lo_bxgy_sub", icon: "🎁" },
  { k: "product_discount", title: "lo_pdisc", sub: "lo_pdisc_sub", icon: "🏷️" }, { k: "order_discount", title: "lo_odisc", sub: "lo_odisc_sub", icon: "🧾" },
];

function describe(p: Program, t: ReturnType<typeof useLang>["t"]): string {
  if (p.kind === "points") return `${p.points_per_unit} ${t("lo_ppu")} · ${t("lo_pv")} ${p.point_value} · ${t("lo_min")} ${p.min_redeem}`;
  if (p.kind === "bxgy") return `${t("lo_buy")} ${p.buy} ${t("lo_free")} ${p.free} · ${p.product}`;
  if (p.kind === "product_discount") return `${p.percent}% · ${[...(p.products ?? []).map((x) => x.name), p.category].filter(Boolean).join("، ")}`;
  return `${p.percent}% · ${t("lo_min_amount")} ${p.minimum_amount}`;
}

/** Create and switch offers; the till applies them, Odoo keeps them. */
export default function LoyaltyPage() {
  const { t } = useLang();
  const qc = useQueryClient();
  const cid = useActiveConnection().data?.id;
  const canEdit = !!useMe().data?.permissions.includes("sales.price.override");
  const keyFor = useIdempotencyKey();
  const progs = useQuery({ queryKey: ["loyalty", cid], queryFn: () => api<{ installed: boolean; items: Program[] }>(`/connections/${cid}/loyalty/programs`), enabled: !!cid });
  const [kind, setKind] = useState<Kind | null>(null);
  const [f, setF] = useState<Record<string, string>>({});
  const [picked, setPicked] = useState<{ id: number; name: string }[]>([]);
  const [text, setText] = useState("");
  const found = useProducts(cid, text.trim(), 0, 6);
  const body = (): Record<string, unknown> => {
    const n = (k: string) => (f[k] ? Number(f[k]) : undefined);
    const b: Record<string, unknown> = { kind, name: (f.name ?? "").trim(), ...(f.date_from ? { date_from: f.date_from } : {}), ...(f.date_to ? { date_to: f.date_to } : {}) };
    if (kind === "points") Object.assign(b, { points_per_unit: n("ppu"), point_value: n("pv"), min_redeem: n("min") ?? 1 });
    if (kind === "bxgy") Object.assign(b, { product_id: picked[0]?.id, buy: n("buy"), free: n("free") });
    if (kind === "product_discount") Object.assign(b, { product_ids: picked.map((p) => p.id), percent: n("pct") });
    if (kind === "order_discount") Object.assign(b, { percent: n("pct"), minimum_amount: n("minamt") ?? 0 });
    return b;
  };
  const create = useMutation({
    mutationFn: () => { const b = body(); return api(`/connections/${cid}/loyalty/programs`, { body: b, headers: { "Idempotency-Key": keyFor(b) } }); },
    onSuccess: () => { setKind(null); setF({}); setPicked([]); void qc.invalidateQueries({ queryKey: ["loyalty"] }); },
  });
  const toggle = useMutation({
    mutationFn: (p: Program) => api(`/connections/${cid}/loyalty/programs/${p.id}/active`, { method: "PUT", body: { active: !p.active }, headers: { "Idempotency-Key": keyFor({ id: p.id, active: !p.active, at: Date.now() }) } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["loyalty"] }),
  });
  const err = (create.error ?? toggle.error) instanceof ApiError ? ((create.error ?? toggle.error) as ApiError) : null;
  if (progs.isError) return <ErrorBox message={progs.error instanceof ApiError && progs.error.code !== "network" ? `${errorText(t, progs.error.code)} (${progs.error.code})` : t("err_network")} reference={progs.error instanceof ApiError ? progs.error.correlationId : undefined} />;
  if (!progs.data) return <Spinner label={t("loading")} />;
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const multi = kind === "product_discount";
  return (
    <div className="rise mx-auto max-w-3xl space-y-5">
      <header>
        <h1 className="flex items-center gap-3 text-3xl font-black"><Gift className="size-8 text-brand" aria-hidden /> {t("lo_title")}</h1>
        <p className="mt-1 text-soft">{t("lo_sub")}</p>
      </header>
      {!progs.data.installed && <Card className="border-warn/40 bg-warnsoft font-bold">{t("lo_off")}</Card>}
      {progs.data.installed && progs.data.items.length === 0 && <Card className="py-8 text-center text-soft">{t("lo_none")}</Card>}
      <ul className="space-y-2">
        {progs.data.items.map((p) => (
          <li key={p.id}><Card className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="min-w-0"><p className="font-black">{KINDS.find((k) => k.k === p.kind)?.icon} {p.name}</p><p className="text-sm text-soft" dir="auto">{describe(p, t)}</p>
              {p.kind === "points" && <Badge tone="brand">{p.members} {t("lo_members")}</Badge>}</div>
            <button type="button" role="switch" aria-checked={p.active} aria-label={`${t("lo_active")}: ${p.name}`} disabled={!canEdit || toggle.isPending} onClick={() => toggle.mutate(p)}
              className={cn("h-8 w-14 shrink-0 rounded-full p-1 transition disabled:opacity-50", p.active ? "bg-brand" : "bg-line")}>
              <span className={cn("block size-6 rounded-full bg-white transition", p.active ? "translate-x-6 rtl:-translate-x-6" : "")} />
            </button>
          </Card></li>
        ))}
      </ul>
      {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${err.code === "loyalty_rejected" || err.code === "validation" ? err.message : ""}`} reference={err.correlationId} />}
      {canEdit && progs.data.installed && (
        <Card className="space-y-4">
          <h2 className="flex items-center gap-2 text-lg font-black"><Plus className="size-5 text-brand" aria-hidden /> {t("lo_new")}</h2>
          <div role="radiogroup" aria-label={t("lo_kind")} className="grid gap-2 sm:grid-cols-2">
            {KINDS.map((k) => (
              <button key={k.k} type="button" role="radio" aria-checked={kind === k.k} onClick={() => { setKind(k.k); setPicked([]); }}
                className={cn("rounded-2xl border-2 p-3 text-start", kind === k.k ? "border-brand bg-brandsoft" : "border-line bg-surface")}>
                <span className="block font-black">{k.icon} {t(k.title)}</span><span className="text-xs text-soft">{t(k.sub)}</span>
              </button>
            ))}
          </div>
          {kind && (
            <div className="space-y-3">
              <Field label={t("lo_name")} name="name" value={f.name ?? ""} onChange={set("name")} />
              {kind === "points" && <div className="grid gap-3 sm:grid-cols-3">
                <Field label={t("lo_ppu")} name="ppu" type="number" min="0" step="any" value={f.ppu ?? ""} onChange={set("ppu")} dir="ltr" />
                <Field label={t("lo_pv")} name="pv" type="number" min="0" step="any" value={f.pv ?? ""} onChange={set("pv")} dir="ltr" />
                <Field label={t("lo_min")} name="min" type="number" min="1" step="1" value={f.min ?? ""} onChange={set("min")} dir="ltr" /></div>}
              {kind === "bxgy" && <div className="grid grid-cols-2 gap-3">
                <Field label={t("lo_buy")} name="buy" type="number" min="1" step="1" value={f.buy ?? ""} onChange={set("buy")} dir="ltr" />
                <Field label={t("lo_free")} name="free" type="number" min="1" step="1" value={f.free ?? ""} onChange={set("free")} dir="ltr" /></div>}
              {(kind === "product_discount" || kind === "order_discount") && <Field label={t("lo_percent")} name="pct" type="number" min="0" max="100" step="any" value={f.pct ?? ""} onChange={set("pct")} dir="ltr" />}
              {kind === "order_discount" && <Field label={t("lo_min_amount")} name="minamt" type="number" min="0" step="any" value={f.minamt ?? ""} onChange={set("minamt")} dir="ltr" />}
              {(kind === "bxgy" || multi) && (
                <div className="space-y-2">
                  <p className="text-sm font-bold">{t(multi ? "lo_products" : "lo_product")}: {picked.map((p) => p.name).join("، ")}</p>
                  <input aria-label={t("lo_search")} placeholder={t("lo_search")} value={text} onChange={(e) => setText(e.target.value)} className="min-h-11 w-full rounded-xl border border-line bg-surface px-3" />
                  {text.trim() && found.data && (
                    <ul className="divide-y divide-line rounded-xl border border-line">{found.data.items.filter((p) => p.variant_count === 1).map((p) => (
                      <li key={p.template_id}><button type="button" onClick={() => { const v = { id: p.variant_id ?? p.template_id, name: p.name }; setPicked(multi ? [...picked.filter((x) => x.id !== v.id), v] : [v]); setText(""); }} className="min-h-11 w-full px-3 text-start hover:bg-surface2" dir="auto">{p.name}</button></li>
                    ))}</ul>
                  )}
                </div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <Field label={t("lo_from")} name="date_from" type="date" value={f.date_from ?? ""} onChange={set("date_from")} dir="ltr" />
                <Field label={t("lo_to")} name="date_to" type="date" value={f.date_to ?? ""} onChange={set("date_to")} dir="ltr" />
              </div>
              <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!(f.name ?? "").trim()} className="w-full">{t("lo_create")}</Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
