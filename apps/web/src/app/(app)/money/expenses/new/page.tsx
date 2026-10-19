"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Hourglass } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { MoneyTabs } from "@/components/money-tabs";
import { Button, Card, ErrorBox, Field } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useHydrated } from "@/lib/hydrated";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useExpenseCategories, useSuppliers } from "@/lib/queries";

export default function NewExpensePage() {
  const { t } = useLang();
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const cid = useActiveConnection().data?.id;
  const cats = useExpenseCategories(cid);
  const suppliers = useSuppliers(cid, "");
  const keyFor = useIdempotencyKey();
  const [category, setCategory] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [desc, setDesc] = useState("");
  const [ref, setRef] = useState("");
  const [payee, setPayee] = useState("");
  const [paidNow, setPaidNow] = useState(true);
  const [from, setFrom] = useState<"cash" | "bank">("cash");
  const payload = { category_id: category, amount: Number(amount || 0), date, description: desc.trim(), ...(ref.trim() ? { ref: ref.trim() } : {}), ...(payee ? { partner_id: Number(payee) } : {}), ...(paidNow ? { pay_now: { journal_type: from } } : {}) };
  const m = useMutation({
    mutationFn: () => api<{ status?: string }>(`/connections/${cid}/money/expenses`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["expenses"] }); void qc.invalidateQueries({ queryKey: ["money-overview"] }); void qc.invalidateQueries({ queryKey: ["money-ledger"] }); },
  });
  const err = m.error instanceof ApiError ? m.error : null;
  const valid = !!category && Number(amount) > 0 && desc.trim().length > 0;

  if (m.isSuccess) {
    const waiting = m.data?.status === "awaiting_approval";
    return (
      <div className="rise mx-auto max-w-xl space-y-4">
        <Card className={cn("space-y-2 text-center", waiting ? "border-warn/40 bg-warnsoft" : "border-ok/30 bg-oksoft")}>
          {waiting ? <Hourglass className="mx-auto size-12 text-warn" aria-hidden /> : <CheckCircle2 className="pop mx-auto size-12 text-ok" aria-hidden />}
          <p className="text-xl font-black">{waiting ? t("ex_waiting") : t("ex_saved")}</p>
        </Card>
        <Link href="/money/expenses" className="inline-flex min-h-12 w-full items-center justify-center rounded-2xl bg-brand font-bold text-brandink">{t("ex_title")}</Link>
      </div>
    );
  }
  return (
    <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate(); }} className="rise mx-auto max-w-xl space-y-5">
      <MoneyTabs />
      <h1 className="text-3xl font-black">{t("ex_new")}</h1>
      {cats.data && cats.data.items.length === 0 && <Card className="border-warn/40 bg-warnsoft"><Link href="/money/categories" className="font-bold text-warn">{t("ex_need_cat")}</Link></Card>}
      <Card className="space-y-4">
        <label className="block text-sm font-bold">{t("ex_category")}
          <select value={category} onChange={(e) => setCategory(e.target.value)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-3 text-base">
            <option value="" />
            {cats.data?.items.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select></label>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("ex_amount")} name="amount" type="number" inputMode="decimal" min="0" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} dir="ltr" />
          <Field label={t("ex_date")} name="date" type="date" required value={date} onChange={(e) => setDate(e.target.value)} dir="ltr" />
        </div>
        <Field label={t("ex_desc")} name="desc" required value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={300} />
        <Field label={t("ex_ref")} name="ref" value={ref} onChange={(e) => setRef(e.target.value)} maxLength={100} dir="ltr" />
        <label className="block text-sm font-bold">{t("ex_payee")}
          <select value={payee} onChange={(e) => setPayee(e.target.value)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-3 text-base">
            <option value="">{t("ex_no_payee")}</option>
            {suppliers.data?.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select></label>
      </Card>
      <Card className="space-y-3">
        <div role="radiogroup" aria-label="payment" className="grid grid-cols-2 gap-2">
          <button type="button" role="radio" aria-checked={paidNow} onClick={() => setPaidNow(true)} className={cn("min-h-12 rounded-2xl border-2 font-bold", paidNow ? "border-brand bg-brandsoft" : "border-line")}>{t("ex_paid_now")}</button>
          <button type="button" role="radio" aria-checked={!paidNow} onClick={() => setPaidNow(false)} className={cn("min-h-12 rounded-2xl border-2 font-bold", !paidNow ? "border-brand bg-brandsoft" : "border-line")}>{t("ex_on_credit")}</button>
        </div>
        {paidNow && (
          <div role="radiogroup" aria-label={t("ex_from")} className="grid grid-cols-2 gap-2">
            {(["cash", "bank"] as const).map((k) => <button type="button" key={k} role="radio" aria-checked={from === k} onClick={() => setFrom(k)} className={cn("min-h-11 rounded-2xl border-2 font-bold", from === k ? "border-brand bg-brandsoft" : "border-line")}>{t(k === "cash" ? "mn_cash" : "mn_bank")}</button>)}
          </div>
        )}
        <p className="text-xs text-soft">{t("ex_no_tax")}</p>
      </Card>
      {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${/_rejected$/.test(err.code) ? err.message : ""}`} reference={err.correlationId} />}
      <Button type="submit" disabled={!hydrated || !valid} loading={m.isPending} className="w-full">{t("ex_save")}</Button>
    </form>
  );
}
