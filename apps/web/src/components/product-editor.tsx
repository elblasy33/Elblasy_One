"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Modal } from "@/components/modal";
import { Button, ErrorBox, Field } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useCategories } from "@/lib/queries";
import type { Product } from "@/lib/types";

/** Edits one product (only what changed is sent) and archives / restores it. */
export function ProductEditor({ cid, product, onClose }: { cid: string; product: Product; onClose: () => void }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const keyFor = useIdempotencyKey();
  const cats = useCategories(cid);
  const [f, setF] = useState({
    name: product.name, price: String(product.price), cost: product.cost === undefined ? "" : String(product.cost),
    sku: product.sku ?? "", barcode: product.barcode ?? "", category: product.category ?? "",
  });
  const changes: Record<string, unknown> = {};
  if (f.name.trim() !== product.name) changes.name = f.name.trim();
  if (f.price !== "" && Number(f.price) !== product.price) changes.price = Number(f.price);
  if (product.cost !== undefined && f.cost !== "" && Number(f.cost) !== product.cost) changes.cost = Number(f.cost);
  if (f.sku !== (product.sku ?? "")) changes.sku = f.sku.trim();
  if (f.barcode !== (product.barcode ?? "") && product.variant_count <= 1) changes.barcode = f.barcode.trim();
  if (f.category.trim() && f.category.trim() !== (product.category ?? "")) changes.category = f.category.trim();
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/connections/${cid}/catalog/products/${product.template_id}`, { method: "PATCH", body, headers: { "Idempotency-Key": keyFor({ id: product.template_id, ...body }) } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["products"] }); void qc.invalidateQueries({ queryKey: ["categories"] }); onClose(); },
  });
  const err = save.error instanceof ApiError ? save.error : null;
  const archived = product.active === false;
  const canCompose = useActiveConnection().data?.capabilities?.manufacturing === true && product.variant_count <= 1;
  return (
    <Modal title={t("pe_title")} onClose={onClose}>
      <form method="post" action="#" className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (Object.keys(changes).length) save.mutate(changes); }}>
        <Field label={t("pe_name")} name="name" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("prod_price")} name="price" type="number" inputMode="decimal" min="0" step="0.01" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} dir="ltr" />
          {product.cost !== undefined && <Field label={t("prod_cost")} name="cost" type="number" inputMode="decimal" min="0" step="0.01" value={f.cost} onChange={(e) => setF({ ...f, cost: e.target.value })} dir="ltr" />}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("pe_sku")} name="sku" value={f.sku} onChange={(e) => setF({ ...f, sku: e.target.value })} dir="ltr" />
          <Field label={t("pe_barcode")} name="barcode" value={f.barcode} disabled={product.variant_count > 1} onChange={(e) => setF({ ...f, barcode: e.target.value })} dir="ltr" />
        </div>
        <Field label={t("pe_category")} name="category" list="pe-cats" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} />
        <datalist id="pe-cats">{(cats.data?.items ?? []).map((c) => <option key={c} value={c.split(" / ").pop()} />)}</datalist>
        {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${/_rejected$/.test(err.code) ? err.message : ""}`} reference={err.correlationId} />}
        <Button type="submit" disabled={!Object.keys(changes).length} loading={save.isPending} className="w-full">{t("pe_save")}</Button>
        <Button type="button" variant={archived ? "soft" : "danger"} onClick={() => save.mutate({ active: archived })} disabled={save.isPending} className="w-full">{archived ? t("pe_restore") : t("pe_archive")}</Button>
        {!archived && <p className="text-xs text-soft">{t("pe_archive_note")}</p>}
        {canCompose && !archived && <Link href={`/inventory/recipe?template=${product.template_id}`} className="block text-center text-sm font-bold text-brand">{t("pe_compose")}</Link>}
      </form>
    </Modal>
  );
}
