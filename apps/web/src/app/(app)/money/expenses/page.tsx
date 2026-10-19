"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Banknote, Plus, Receipt, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { MoneyTabs } from "@/components/money-tabs";
import { Modal } from "@/components/modal";
import { money } from "@/components/receipt";
import { Badge, Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useExpenses, useMe, usePendingExpenses } from "@/lib/queries";
import type { ExpenseRow } from "@/lib/types";

function PayDialog({ cid, row, onClose, onDone }: { cid: string; row: ExpenseRow; onClose: () => void; onDone: () => void }) {
  const { t } = useLang();
  const keyFor = useIdempotencyKey();
  const [amount, setAmount] = useState(String(row.amount_residual));
  const [from, setFrom] = useState<"cash" | "bank">("cash");
  const payload = { amount: Number(amount || 0), journal_type: from };
  const m = useMutation({ mutationFn: () => api(`/connections/${cid}/money/expenses/${row.id}/pay`, { body: payload, headers: { "Idempotency-Key": keyFor({ id: row.id, ...payload }) } }), onSuccess: onDone });
  const err = m.error instanceof ApiError ? m.error : null;
  const ok = Number(amount) > 0 && Number(amount) <= row.amount_residual + 0.004;
  return (
    <Modal title={t("ex_pay")} onClose={onClose}>
      <div className="space-y-4">
        <p className="flex justify-between font-bold"><span>{t("mn_still_owed")}</span><span dir="ltr">{money(row.amount_residual)}</span></p>
        <input autoFocus aria-label={t("ex_amount")} type="number" inputMode="decimal" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} dir="ltr" className="min-h-14 w-full rounded-2xl border border-line bg-surface px-4 text-center text-3xl font-black outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
        <div role="radiogroup" aria-label={t("ex_from")} className="grid grid-cols-2 gap-2">
          {(["cash", "bank"] as const).map((k) => <button key={k} role="radio" aria-checked={from === k} onClick={() => setFrom(k)} className={cn("min-h-12 rounded-2xl border-2 font-bold", from === k ? "border-brand bg-brandsoft" : "border-line")}>{t(k === "cash" ? "mn_cash" : "mn_bank")}</button>)}
        </div>
        {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${/_rejected$/.test(err.code) ? err.message : ""}`} reference={err.correlationId} />}
        <Button onClick={() => m.mutate()} disabled={!ok} loading={m.isPending} className="min-h-14 w-full">{t("ex_pay")}</Button>
      </div>
    </Modal>
  );
}

export default function ExpensesPage() {
  const { t } = useLang();
  const qc = useQueryClient();
  const me = useMe();
  const cid = useActiveConnection().data?.id;
  const can = (p: string) => !!me.data?.permissions.includes(p);
  const [offset, setOffset] = useState(0);
  const list = useExpenses(cid, offset);
  const pending = usePendingExpenses(cid, can("expenses.approve"));
  const [pay, setPay] = useState<ExpenseRow | null>(null);
  const keyFor = useIdempotencyKey();
  const refresh = () => { setPay(null); void qc.invalidateQueries({ queryKey: ["expenses"] }); void qc.invalidateQueries({ queryKey: ["money-overview"] }); void qc.invalidateQueries({ queryKey: ["money-ledger"] }); void qc.invalidateQueries({ queryKey: ["expense-requests"] }); };
  const decide = useMutation({
    mutationFn: ({ id, kind }: { id: string; kind: "approve" | "reject" }) => api(`/connections/${cid}/money/expense-requests/${id}/${kind}`, { method: "POST", ...(kind === "reject" ? { body: {} } : {}), headers: { "Idempotency-Key": keyFor({ id, kind }) } }),
    onSuccess: refresh,
  });
  const derr = decide.error instanceof ApiError ? decide.error : null;
  const state = (r: ExpenseRow) => (r.payment_state === "paid" || r.payment_state === "in_payment" ? ["ex_paid", "ok"] as const : r.payment_state === "partial" ? ["ex_partial", "warn"] as const : ["ex_unpaid", "warn"] as const);

  return (
    <div className="rise space-y-5">
      <MoneyTabs />
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-3 text-3xl font-black"><Receipt className="size-8 text-brand" aria-hidden /> {t("ex_title")}</h1>
        {can("expenses.create") && <Link href="/money/expenses/new" className="inline-flex min-h-11 items-center gap-2 rounded-2xl bg-brand px-4 text-sm font-bold text-brandink shadow-card"><Plus className="size-4" aria-hidden /> {t("ex_new")}</Link>}
      </header>
      {pending.data && pending.data.items.length > 0 && (
        <Card className="space-y-3 border-warn/40 bg-warnsoft">
          <h2 className="flex items-center gap-2 text-lg font-black text-warn"><ShieldCheck className="size-5" aria-hidden /> {t("ex_pending")}</h2>
          {derr && <ErrorBox message={errorText(t, derr.code)} reference={derr.correlationId} />}
          <ul className="divide-y divide-line/50">
            {pending.data.items.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="text-sm"><p className="font-bold" dir="auto">{p.description}</p><p className="text-soft">{t("ex_requested_by")} <span dir="ltr">{p.requested_by}</span> · <b dir="ltr">{money(p.amount ?? 0)}</b></p></div>
                <div className="flex gap-2"><Button className="min-h-10 px-4" loading={decide.isPending} onClick={() => decide.mutate({ id: p.id, kind: "approve" })}>{t("st_approve")}</Button>
                  <Button variant="ghost" className="min-h-10 px-4" onClick={() => decide.mutate({ id: p.id, kind: "reject" })}>{t("st_reject")}</Button></div>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {list.isLoading && <Spinner label={t("loading")} />}
      {list.data && list.data.total === 0 && <Card className="py-12 text-center text-xl font-black">{t("ex_none")}</Card>}
      <ul className="space-y-3">
        {list.data?.items.map((r) => {
          const [label, tone] = state(r);
          return (
            <li key={r.id}><Card className="flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="min-w-0"><p className="truncate text-lg font-black" dir="auto">{r.description}</p>
                <p className="text-xs text-soft" dir="auto"><span dir="ltr">{r.date}</span> · {r.account}{r.ref ? ` · ${r.ref}` : ""}</p></div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={tone}>{t(label)}</Badge>
                <span className="text-lg font-black" dir="ltr">{money(r.amount_total)}</span>
                {r.amount_residual > 0.004 && <span className="text-xs text-soft">{t("mn_still_owed")}: <b dir="ltr">{money(r.amount_residual)}</b></span>}
                {r.amount_residual > 0.004 && can("payments.create") && <Button variant="soft" className="min-h-10 px-3" onClick={() => setPay(r)}><Banknote className="size-4" aria-hidden /> {t("ex_pay")}</Button>}
              </div>
            </Card></li>
          );
        })}
      </ul>
      {list.data && list.data.total > 20 && (
        <div className="flex justify-between">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))} className="min-h-11 rounded-2xl border border-line px-4 font-bold disabled:opacity-40">{t("prod_prev")}</button>
          <button disabled={offset + 20 >= list.data.total} onClick={() => setOffset(offset + 20)} className="min-h-11 rounded-2xl border border-line px-4 font-bold disabled:opacity-40">{t("prod_next")}</button>
        </div>
      )}
      {pay && cid && <PayDialog cid={cid} row={pay} onClose={() => setPay(null)} onDone={refresh} />}
    </div>
  );
}
