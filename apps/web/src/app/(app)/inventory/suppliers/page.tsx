"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Truck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { InventoryTabs } from "@/components/inv-tabs";
import { money } from "@/components/receipt";
import { Badge, Button, Card, ErrorBox, Field, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useHydrated } from "@/lib/hydrated";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useMe, useSuppliers } from "@/lib/queries";
import type { Supplier } from "@/lib/types";

export default function SuppliersPage() {
  const { t } = useLang();
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const me = useMe();
  const cid = useActiveConnection().data?.id;
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const keyFor = useIdempotencyKey();
  useEffect(() => { const id = setTimeout(() => setQ(text.trim()), 300); return () => clearTimeout(id); }, [text]);
  const list = useSuppliers(cid, q);
  const canManage = !!me.data?.permissions.includes("purchasing.manage");
  const canStatement = !!me.data?.permissions.includes("payments.create");
  const payload = { name: name.trim(), ...(phone.trim() ? { phone: phone.trim() } : {}) };
  const create = useMutation({
    mutationFn: () => api<{ supplier: Supplier }>(`/connections/${cid}/purchasing/suppliers`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: () => { setAdding(false); setName(""); setPhone(""); void qc.invalidateQueries({ queryKey: ["suppliers"] }); },
  });
  const err = create.error instanceof ApiError ? create.error : null;

  return (
    <div className="rise space-y-5">
      <InventoryTabs />
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-3 text-3xl font-black"><Truck className="size-8 text-brand" aria-hidden /> {t("sup_title")}</h1>
        {canManage && <Button onClick={() => setAdding(!adding)} variant={adding ? "ghost" : "primary"}><Plus className="size-4" aria-hidden /> {t("sup_add")}</Button>}
      </header>
      {adding && (
        <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
          <Card className="space-y-4">
            <Field label={t("sup_name")} name="name" required value={name} onChange={(e) => setName(e.target.value)} />
            <Field label={t("sup_phone")} name="phone" value={phone} onChange={(e) => setPhone(e.target.value)} dir="ltr" inputMode="tel" />
            {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
            <Button type="submit" disabled={!hydrated || !name.trim()} loading={create.isPending} className="w-full">{t("sup_save")}</Button>
          </Card>
        </form>
      )}
      <label className="relative block">
        <span className="sr-only">{t("sup_search")}</span>
        <Search className="pointer-events-none absolute start-4 top-1/2 size-5 -translate-y-1/2 text-soft" aria-hidden />
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("sup_search")} className="min-h-12 w-full rounded-2xl border border-line bg-surface ps-12 pe-4 outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
      </label>
      {list.isLoading && <Spinner label={t("loading")} />}
      {list.data && list.data.total === 0 && <Card className="space-y-2 py-12 text-center"><p className="text-xl font-black">{t("sup_none")}</p><p className="text-soft">{t("sup_none_sub")}</p></Card>}
      <ul className="space-y-3">
        {list.data?.items.map((s) => {
          const body = (
            <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
              <div><p className="text-lg font-black">{s.name}</p>{s.phone && <p className="text-sm text-soft" dir="ltr">{s.phone}</p>}</div>
              {s.balance !== undefined && <div className="text-end"><p className="text-xs text-soft">{t("sup_balance")}</p><Badge tone={s.balance > 0 ? "warn" : "ok"}><span dir="ltr">{money(s.balance)}</span></Badge></div>}
            </Card>
          );
          return <li key={s.id}>{canStatement ? <Link href={`/inventory/suppliers/${s.id}`} className="block transition hover:opacity-90">{body}</Link> : body}</li>;
        })}
      </ul>
    </div>
  );
}
