"use client";
import { Archive, Boxes, FileUp, Pencil, Plus, Scale, Search, Shapes, Timer } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { InventoryTabs } from "@/components/inv-tabs";
import { ProductEditor } from "@/components/product-editor";
import { Badge, Card, Spinner } from "@/components/ui";
import { useLang } from "@/lib/i18n";
import { useActiveConnection, useMe, useProducts } from "@/lib/queries";
import type { Product } from "@/lib/types";

const PAGE = 20;

export default function InventoryPage() {
  const { t } = useLang();
  const cid = useActiveConnection().data?.id;
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const id = setTimeout(() => { setQ(text.trim()); setOffset(0); }, 300);
    return () => clearTimeout(id);
  }, [text]);
  const [archived, setArchived] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const canEdit = !!useMe().data?.permissions.includes("products.manage");
  const products = useProducts(cid, q, offset, PAGE, archived);
  const d = products.data;

  return (
    <div className="rise space-y-5">
      <InventoryTabs />
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-3 text-3xl font-black"><Boxes className="size-8 text-brand" aria-hidden /> {t("prod_title")}</h1>
        <div className="flex gap-2">
          {canEdit && <button onClick={() => { setArchived(!archived); setOffset(0); }} aria-pressed={archived} className="inline-flex min-h-11 items-center gap-2 rounded-2xl border border-line px-4 text-sm font-bold hover:bg-surface2"><Archive className="size-4" aria-hidden /> {archived ? t("pe_active_view") : t("pe_archived_view")}</button>}
          <Link href="/inventory/import" className="inline-flex min-h-11 items-center gap-2 rounded-2xl border border-line px-4 text-sm font-bold hover:bg-surface2"><FileUp className="size-4" aria-hidden /> {t("prod_import")}</Link>
          <Link href="/inventory/new" className="inline-flex min-h-11 items-center gap-2 rounded-2xl bg-brand px-4 text-sm font-bold text-brandink shadow-card hover:brightness-110"><Plus className="size-4" aria-hidden /> {t("prod_add")}</Link>
        </div>
      </header>

      <label className="relative block">
        <span className="sr-only">{t("prod_search")}</span>
        <Search className="pointer-events-none absolute start-4 top-1/2 size-5 -translate-y-1/2 text-soft" aria-hidden />
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("prod_search")} inputMode="search"
          className="min-h-12 w-full rounded-2xl border border-line bg-surface ps-12 pe-4 text-base outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
      </label>

      {products.isLoading && <Spinner label={t("loading")} />}
      {d && d.total === 0 && (
        <Card className="space-y-2 py-12 text-center">
          <p className="text-xl font-black">{t("prod_none")}</p>
          <p className="text-soft">{t("prod_none_sub")}</p>
        </Card>
      )}
      {d && d.total > 0 && (
        <>
          <p className="text-sm text-soft" aria-live="polite">{d.total} {t("prod_found")}</p>
          <ul className="space-y-3">
            {d.items.map((p) => (
              <li key={p.template_id}>
                <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
                  <div className="min-w-0 space-y-1">
                    <p className="truncate text-lg font-black">{p.name}</p>
                    <div className="flex flex-wrap items-center gap-2 text-sm text-soft">
                      {p.barcode && <span dir="ltr" className="font-mono">{p.barcode}</span>}
                      {p.category && <Badge>{p.category}</Badge>}
                      {p.by_weight && <Badge tone="brand"><Scale className="size-3" aria-hidden />{t("prod_by_weight")}</Badge>}
                      {p.variant_count > 1 && <Badge tone="brand"><Shapes className="size-3" aria-hidden />{p.variant_count} {t("prod_variants")}</Badge>}
                      {p.tracking !== "none" && <Badge tone="warn"><Timer className="size-3" aria-hidden />{t("prod_lot")}</Badge>}
                    </div>
                  </div>
                  <dl className="flex gap-5 text-center">
                    <div><dt className="text-xs text-soft">{t("prod_price")}</dt><dd className="font-black" dir="ltr">{p.price}</dd></div>
                    {p.cost !== undefined && <div><dt className="text-xs text-soft">{t("prod_cost")}</dt><dd className="font-black" dir="ltr">{p.cost}</dd></div>}
                    <div><dt className="text-xs text-soft">{t("prod_stock")}</dt><dd className="font-black" dir="ltr">{p.on_hand ?? "—"}</dd></div>
                  </dl>
                  {canEdit && <button onClick={() => setEditing(p)} className="inline-flex min-h-10 items-center gap-1 rounded-xl border border-line px-3 text-sm font-bold hover:bg-surface2"><Pencil className="size-4" aria-hidden /> {t("pe_edit")}</button>}
                </Card>
              </li>
            ))}
          </ul>
          <nav className="flex items-center justify-between" aria-label="pagination">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="min-h-11 rounded-2xl border border-line px-4 font-bold disabled:opacity-40">{t("prod_prev")}</button>
            <span className="text-sm text-soft" dir="ltr">{offset + 1}–{Math.min(offset + PAGE, d.total)} / {d.total}</span>
            <button disabled={offset + PAGE >= d.total} onClick={() => setOffset(offset + PAGE)} className="min-h-11 rounded-2xl border border-line px-4 font-bold disabled:opacity-40">{t("prod_next")}</button>
          </nav>
        </>
      )}
      {editing && cid && <ProductEditor cid={cid} product={{ ...editing, active: !archived }} onClose={() => setEditing(null)} />}
    </div>
  );
}
