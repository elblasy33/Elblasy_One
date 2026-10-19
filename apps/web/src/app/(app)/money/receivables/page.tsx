"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { MoneyTabs } from "@/components/money-tabs";
import { money } from "@/components/receipt";
import { Badge, Button, Card, ErrorBox, Field, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useHydrated } from "@/lib/hydrated";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useCustomers, useMe } from "@/lib/queries";

export default function ReceivablesPage() {
  const { t } = useLang();
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const me = useMe();
  const cid = useActiveConnection().data?.id;
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", phone: "", limit: "" });
  const keyFor = useIdempotencyKey();
  useEffect(() => { const id = setTimeout(() => setQ(text.trim()), 300); return () => clearTimeout(id); }, [text]);
  const list = useCustomers(cid, q);
  const canLimit = !!me.data?.permissions.includes("customers.credit.override");
  const payload = { name: f.name.trim(), ...(f.phone.trim() ? { phone: f.phone.trim() } : {}), ...(canLimit && f.limit !== "" ? { credit_limit: Number(f.limit) } : {}) };
  const create = useMutation({
    mutationFn: () => api(`/connections/${cid}/customers`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: () => { setAdding(false); setF({ name: "", phone: "", limit: "" }); void qc.invalidateQueries({ queryKey: ["customers"] }); },
  });
  const err = create.error instanceof ApiError ? create.error : null;
  const items = [...(list.data?.items ?? [])].sort((a, b) => (b.receivable ?? 0) - (a.receivable ?? 0));
  return (
    <div className="rise space-y-5">
      <MoneyTabs />
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-3 text-3xl font-black"><Users className="size-8 text-brand" aria-hidden /> {t("cu_title")}</h1>
        <Button onClick={() => setAdding(!adding)} variant={adding ? "ghost" : "primary"}><Plus className="size-4" aria-hidden /> {t("cu_add")}</Button>
      </header>
      {adding && (
        <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
          <Card className="space-y-4">
            <Field label={t("cu_name")} name="name" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            <Field label={t("cu_phone")} name="phone" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} dir="ltr" inputMode="tel" />
            {canLimit && <Field label={t("cu_limit")} name="limit" type="number" inputMode="decimal" min="0" step="0.01" value={f.limit} onChange={(e) => setF({ ...f, limit: e.target.value })} dir="ltr" />}
            {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
            <Button type="submit" disabled={!hydrated || !f.name.trim()} loading={create.isPending} className="w-full">{t("cu_save")}</Button>
          </Card>
        </form>
      )}
      <label className="relative block"><span className="sr-only">{t("cu_search")}</span>
        <Search className="pointer-events-none absolute start-4 top-1/2 size-5 -translate-y-1/2 text-soft" aria-hidden />
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("cu_search")} className="min-h-12 w-full rounded-2xl border border-line bg-surface ps-12 pe-4 outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" /></label>
      {list.isLoading && <Spinner label={t("loading")} />}
      {list.data && list.data.total === 0 && <Card className="py-12 text-center text-xl font-black">{t("cu_none")}</Card>}
      <ul className="space-y-3">
        {items.map((c) => (
          <li key={c.id}><Link href={`/money/receivables/${c.id}`} className="block"><Card className="flex flex-wrap items-center justify-between gap-3 p-4 transition hover:border-brand">
            <div><p className="text-lg font-black" dir="auto">{c.name}</p>{c.phone && <p className="text-sm text-soft" dir="ltr">{c.phone}</p>}</div>
            <div className="flex flex-wrap items-center gap-2">
              {c.receivable !== undefined && <Badge tone={c.receivable > 0 ? "warn" : "ok"}>{t("cu_owes")} <span dir="ltr">{money(c.receivable)}</span></Badge>}
              {!!c.credit_limit && <Badge>{t("cu_limit")} <span dir="ltr">{money(c.credit_limit)}</span></Badge>}
            </div>
          </Card></Link></li>
        ))}
      </ul>
    </div>
  );
}
