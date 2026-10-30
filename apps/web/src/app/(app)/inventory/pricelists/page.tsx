"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Tags, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { InventoryTabs } from "@/components/inv-tabs";
import { money } from "@/components/receipt";
import { Badge, Button, Card, ErrorBox, Field, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useMe, useProducts } from "@/lib/queries";

interface PL { id: number; name: string; currency: string; items: number; customers: number; rules?: { id: number; template_id: number | null; product: string | null; min_qty: number; price: number | null; list_price: number | null; managed: boolean; rule: string | null }[] }

const msg = (t: ReturnType<typeof useLang>["t"], e: unknown) => (e instanceof ApiError ? `${e.code === "network" ? t("err_network") : errorText(t, e.code)} ${e.code === "pricelist_rejected" ? e.message : ""}` : null);

/** Retail and wholesale prices: a list holds a fixed price per product, optionally from a quantity, and a
 *  customer can be given a list (on their statement page). Odoo applies them at the till and in orders. */
export default function PricelistsPage() {
  const { t } = useLang();
  const qc = useQueryClient();
  const cid = useActiveConnection().data?.id;
  const canEdit = !!useMe().data?.permissions.includes("sales.price.override");
  const keyFor = useIdempotencyKey();
  const lists = useQuery({ queryKey: ["pricelists", cid], queryFn: () => api<{ enabled: boolean; items: PL[] }>(`/connections/${cid}/pricelists`), enabled: !!cid });
  const [open, setOpen] = useState<number | null>(null);
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => api<{ pricelist: PL }>(`/connections/${cid}/pricelists`, { body: { name: name.trim() }, headers: { "Idempotency-Key": keyFor({ name: name.trim() }) } }),
    onSuccess: (r) => { setName(""); setOpen(r.pricelist.id); void qc.invalidateQueries({ queryKey: ["pricelists"] }); },
  });
  if (lists.isError) return <ErrorBox message={lists.error instanceof ApiError && lists.error.code !== "network" ? `${errorText(t, lists.error.code)} (${lists.error.code})` : t("err_network")} reference={lists.error instanceof ApiError ? lists.error.correlationId : undefined} />;
  if (!lists.data) return <Spinner label={t("loading")} />;
  return (
    <div className="rise space-y-5">
      <InventoryTabs />
      <header><h1 className="flex items-center gap-3 text-3xl font-black"><Tags className="size-8 text-brand" aria-hidden /> {t("pl_title")}</h1><p className="text-soft">{t("pl_sub")}</p></header>
      {!lists.data.enabled && <Card className="border-warn/40 bg-warnsoft font-bold">{t("pl_disabled")}</Card>}
      {canEdit && lists.data.enabled && (
        <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); if (name.trim()) create.mutate(); }} className="flex gap-2">
          <input aria-label={t("pl_new_name")} placeholder={t("pl_new_name")} value={name} onChange={(e) => setName(e.target.value)} className="min-h-12 flex-1 rounded-2xl border border-line bg-surface px-4" />
          <Button type="submit" loading={create.isPending} disabled={!name.trim()}><Plus className="size-4" aria-hidden /> {t("pl_create")}</Button>
        </form>
      )}
      {msg(t, create.error) && <ErrorBox message={msg(t, create.error)!} />}
      <ul className="space-y-3">
        {lists.data.items.map((p) => (
          <li key={p.id}>
            <Card className="space-y-3 p-4">
              <button onClick={() => setOpen(open === p.id ? null : p.id)} aria-expanded={open === p.id} className="flex w-full flex-wrap items-center justify-between gap-2 text-start">
                <span className="text-lg font-black">{p.name}</span>
                <span className="flex gap-2"><Badge>{p.items} {t("pl_prices")}</Badge><Badge tone="brand">{p.customers} {t("pl_customers")}</Badge></span>
              </button>
              {open === p.id && cid && <Rules cid={cid} id={p.id} canEdit={canEdit} />}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Rules({ cid, id, canEdit }: { cid: string; id: number; canEdit: boolean }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const keyFor = useIdempotencyKey();
  const pl = useQuery({ queryKey: ["pricelist", cid, id], queryFn: () => api<{ pricelist: PL }>(`/connections/${cid}/pricelists/${id}`) });
  const [text, setText] = useState("");
  const [pick, setPick] = useState<{ id: number; name: string; price: number } | null>(null);
  const [minQty, setMinQty] = useState("");
  const [price, setPrice] = useState("");
  const found = useProducts(cid, text.trim(), 0, 6);
  const set = useMutation({
    mutationFn: (b: { template_id: number; min_qty: number; price: number | null }) => api(`/connections/${cid}/pricelists/${id}/prices`, { method: "PUT", body: b, headers: { "Idempotency-Key": keyFor({ id, ...b }) } }),
    onSuccess: () => { setPick(null); setPrice(""); setMinQty(""); setText(""); void qc.invalidateQueries({ queryKey: ["pricelist", cid, id] }); void qc.invalidateQueries({ queryKey: ["pricelists"] }); },
  });
  if (!pl.data) return <Spinner />;
  const rules = pl.data.pricelist.rules ?? [];
  return (
    <div className="space-y-3 border-t border-line pt-3">
      {rules.length === 0 ? <p className="text-sm text-soft">{t("pl_empty")}</p> : (
        <table className="w-full text-sm">
          <thead className="text-xs text-soft"><tr><th className="py-1 text-start">{t("so_item")}</th><th>{t("pl_from_qty")}</th><th>{t("pl_shelf")}</th><th>{t("pl_price")}</th><th /></tr></thead>
          <tbody>{rules.map((r) => (
            <tr key={r.id} className="border-t border-line text-center">
              <td className="py-2 text-start font-bold" dir="auto">{r.product ?? r.rule}</td>
              <td dir="ltr">{r.min_qty || "—"}</td>
              <td dir="ltr" className="text-soft">{r.list_price != null ? money(r.list_price) : "—"}</td>
              <td dir="ltr" className="font-black text-brand">{r.price != null ? money(r.price) : t("pl_odoo_rule")}</td>
              <td>{canEdit && r.managed && r.template_id && <button aria-label={t("pl_remove")} onClick={() => set.mutate({ template_id: r.template_id!, min_qty: r.min_qty, price: null })} className="grid size-9 place-items-center rounded-xl text-bad hover:bg-badsoft"><Trash2 className="size-4" aria-hidden /></button>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {canEdit && (
        <div className="space-y-2 rounded-2xl bg-surface2 p-3">
          {!pick ? (
            <>
              <input aria-label={t("pl_add_product")} placeholder={t("pl_add_product")} value={text} onChange={(e) => setText(e.target.value)} className="min-h-11 w-full rounded-xl border border-line bg-surface px-3" />
              {text.trim() && found.data && (
                <ul className="divide-y divide-line rounded-xl border border-line bg-surface">{found.data.items.filter((p) => p.variant_count === 1).map((p) => (
                  <li key={p.template_id}><button type="button" onClick={() => { setPick({ id: p.template_id, name: p.name, price: p.price }); setPrice(String(p.price)); }} className="flex min-h-11 w-full items-center justify-between px-3 text-start hover:bg-surface2"><span dir="auto">{p.name}</span><span dir="ltr" className="text-soft">{money(p.price)}</span></button></li>
                ))}</ul>
              )}
            </>
          ) : (
            <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); set.mutate({ template_id: pick.id, min_qty: Number(minQty || 0), price: Number(price) }); }} className="grid gap-2 sm:grid-cols-[1fr_7rem_8rem_auto]">
              <span className="self-center font-bold" dir="auto">{pick.name} <span className="text-xs text-soft" dir="ltr">({money(pick.price)})</span></span>
              <Field label={t("pl_from_qty")} name="min_qty" type="number" inputMode="decimal" min="0" step="any" value={minQty} onChange={(e) => setMinQty(e.target.value)} dir="ltr" />
              <Field label={t("pl_price")} name="price" type="number" inputMode="decimal" min="0" step="any" required value={price} onChange={(e) => setPrice(e.target.value)} dir="ltr" />
              <div className={cn("flex items-end gap-2")}><Button type="submit" loading={set.isPending} disabled={price === ""}>{t("pe_save")}</Button><Button type="button" variant="ghost" onClick={() => setPick(null)}>{t("cancel")}</Button></div>
            </form>
          )}
          {msg(t, set.error) && <ErrorBox message={msg(t, set.error)!} />}
        </div>
      )}
    </div>
  );
}
