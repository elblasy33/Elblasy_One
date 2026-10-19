"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { MoneyTabs } from "@/components/money-tabs";
import { Button, Card, ErrorBox, Field, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useExpenseCategories } from "@/lib/queries";

export default function CategoriesPage() {
  const { t } = useLang();
  const qc = useQueryClient();
  const cid = useActiveConnection().data?.id;
  const cats = useExpenseCategories(cid);
  const accounts = useQuery({ queryKey: ["expense-accounts", cid], queryFn: () => api<{ items: { id: number; code: string; name: string }[] }>(`/connections/${cid}/money/expense-accounts`), enabled: !!cid });
  const [account, setAccount] = useState("");
  const [label, setLabel] = useState("");
  const add = useMutation({
    mutationFn: () => api(`/connections/${cid}/money/categories`, { body: { account_id: Number(account), label: label.trim() } }),
    onSuccess: () => { setLabel(""); setAccount(""); void qc.invalidateQueries({ queryKey: ["expense-categories"] }); },
  });
  const del = useMutation({
    mutationFn: (id: string) => api(`/connections/${cid}/money/categories/${id}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["expense-categories"] }),
  });
  const err = add.error instanceof ApiError ? add.error : null;
  const used = new Set(cats.data?.items.map((c) => c.account_id));
  return (
    <div className="rise mx-auto max-w-2xl space-y-5">
      <MoneyTabs />
      <header><h1 className="text-3xl font-black">{t("ex_cats")}</h1><p className="mt-1 text-soft">{t("ex_cats_sub")}</p></header>
      <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); add.mutate(); }}>
        <Card className="space-y-4">
          <label className="block text-sm font-bold">{t("ex_pick_account")}
            <select value={account} onChange={(e) => setAccount(e.target.value)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-3 text-base">
              <option value="" />
              {accounts.data?.items.filter((a) => !used.has(a.id)).map((a) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}
            </select></label>
          <Field label={t("ex_label")} name="label" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120} />
          {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
          <Button type="submit" disabled={!account || !label.trim()} loading={add.isPending} className="w-full">{t("ex_add_cat")}</Button>
        </Card>
      </form>
      {cats.isLoading && <Spinner label={t("loading")} />}
      <ul className="space-y-2">
        {cats.data?.items.map((c) => (
          <li key={c.id}><Card className="flex items-center justify-between gap-3 p-4">
            <div><p className="text-lg font-black" dir="auto">{c.label}</p><p className="text-xs text-soft" dir="auto">{c.account}</p></div>
            <button aria-label={`${t("ex_delete")} ${c.label}`} onClick={() => del.mutate(c.id)} className="grid size-11 place-items-center rounded-xl text-bad hover:bg-badsoft"><Trash2 className="size-5" aria-hidden /></button>
          </Card></li>
        ))}
      </ul>
    </div>
  );
}
