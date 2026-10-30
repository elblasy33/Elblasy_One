"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Banknote } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Modal } from "@/components/modal";
import { MoneyTabs } from "@/components/money-tabs";
import { money } from "@/components/receipt";
import { Badge, Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { PAY_KEY } from "@/lib/purchasing";
import { useActiveConnection, useCustomerStatement, useMe } from "@/lib/queries";
import type { Customer, CustomerInvoice } from "@/lib/types";

function Collect({ cid, inv, onClose, onDone }: { cid: string; inv: CustomerInvoice; onClose: () => void; onDone: () => void }) {
  const { t } = useLang();
  const keyFor = useIdempotencyKey();
  const [amount, setAmount] = useState(String(inv.amount_residual));
  const [to, setTo] = useState<"cash" | "bank">("cash");
  const payload = { amount: Number(amount || 0), journal_type: to };
  const m = useMutation({ mutationFn: () => api(`/connections/${cid}/customers/invoices/${inv.id}/receive`, { body: payload, headers: { "Idempotency-Key": keyFor({ id: inv.id, ...payload }) } }), onSuccess: onDone });
  const err = m.error instanceof ApiError ? m.error : null;
  const ok = Number(amount) > 0 && Number(amount) <= inv.amount_residual + 0.004;
  return (
    <Modal title={t("cu_collect_title")} onClose={onClose}>
      <div className="space-y-4">
        <p className="flex justify-between font-bold"><span>{t("cu_owes")}</span><span dir="ltr">{money(inv.amount_residual)}</span></p>
        <input autoFocus aria-label={t("ex_amount")} type="number" inputMode="decimal" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} dir="ltr" className="min-h-14 w-full rounded-2xl border border-line bg-surface px-4 text-center text-3xl font-black outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
        <div role="radiogroup" aria-label={t("ex_from")} className="grid grid-cols-2 gap-2">
          {(["cash", "bank"] as const).map((k) => <button key={k} role="radio" aria-checked={to === k} onClick={() => setTo(k)} className={cn("min-h-12 rounded-2xl border-2 font-bold", to === k ? "border-brand bg-brandsoft" : "border-line")}>{t(k === "cash" ? "mn_cash" : "mn_bank")}</button>)}
        </div>
        {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${/_rejected$/.test(err.code) ? err.message : ""}`} reference={err.correlationId} />}
        <Button onClick={() => m.mutate()} disabled={!ok} loading={m.isPending} className="min-h-14 w-full">{t("cu_collect")}</Button>
      </div>
    </Modal>
  );
}

function CustomerPricelist({ cid, customer }: { cid: string; customer: Customer }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const keyFor = useIdempotencyKey();
  const canEdit = !!useMe().data?.permissions.includes("sales.price.override");
  const lists = useQuery({ queryKey: ["pricelists", cid], queryFn: () => api<{ enabled: boolean; items: { id: number; name: string }[] }>(`/connections/${cid}/pricelists`) });
  const m = useMutation({
    mutationFn: (pricelist_id: number | null) => api(`/connections/${cid}/customers/${customer.id}/pricelist`, { method: "PUT", body: { pricelist_id }, headers: { "Idempotency-Key": keyFor({ c: customer.id, pricelist_id }) } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["customer-statement"] }); void qc.invalidateQueries({ queryKey: ["pricelists"] }); },
  });
  if (!lists.data?.enabled || !lists.data.items.length) return null;
  return (
    <Card className="flex flex-wrap items-center justify-between gap-3">
      <span className="font-bold">{t("cu_pricelist")}</span>
      <select aria-label={t("cu_pricelist")} disabled={!canEdit || m.isPending} value={customer.pricelist_id ?? ""} onChange={(e) => m.mutate(e.target.value ? Number(e.target.value) : null)}
        className="min-h-11 rounded-xl border border-line bg-surface px-3 font-bold">
        <option value="">{t("cu_pricelist_none")}</option>
        {lists.data.items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </Card>
  );
}

export default function CustomerStatementPage() {
  const { t } = useLang();
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const me = useMe();
  const cid = useActiveConnection().data?.id;
  const st = useCustomerStatement(cid, Number(id));
  const [pay, setPay] = useState<CustomerInvoice | null>(null);
  const [flash, setFlash] = useState(false);
  const canCollect = !!me.data?.permissions.includes("payments.create");
  if (!st.data) return <Spinner label={t("loading")} />;
  const s = st.data;
  const done = () => { setPay(null); setFlash(true); void qc.invalidateQueries({ queryKey: ["customer-statement"] }); void qc.invalidateQueries({ queryKey: ["customers"] }); void qc.invalidateQueries({ queryKey: ["money-overview"] }); void qc.invalidateQueries({ queryKey: ["money-ledger"] }); };
  return (
    <div className="rise space-y-5">
      <MoneyTabs />
      <header><h1 className="text-3xl font-black" dir="auto">{s.customer.name}</h1><p className="text-soft">{t("cu_statement")}</p></header>
      {flash && <div role="status"><Card className="border-ok/30 bg-oksoft font-bold text-ok">{t("cu_collected")}</Card></div>}
      <Card className="flex flex-wrap items-baseline justify-between gap-3">
        <span className="font-bold">{t("cu_total_owed")}</span><span className="text-3xl font-black" dir="ltr">{money(s.customer.receivable ?? 0)}</span>
        {!!s.customer.credit_limit && <span className="w-full text-sm text-soft">{t("cu_limit")}: <b dir="ltr">{money(s.customer.credit_limit)}</b>{s.customer.available_credit != null && <> · {t("cu_available")}: <b dir="ltr">{money(s.customer.available_credit)}</b></>}</span>}
      </Card>
      {cid && <CustomerPricelist cid={cid} customer={s.customer} />}
      <Card className="space-y-2">
        <h2 className="text-lg font-black">{t("cu_invoices")}</h2>
        {s.invoices.length === 0 ? <p className="text-soft">{t("cu_no_inv")}</p> : (
          <ul className="divide-y divide-line">
            {s.invoices.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                <div><p className="font-bold" dir="ltr">{b.name ?? `#${b.id}`}</p><p className="text-xs text-soft" dir="ltr">{b.date}</p></div>
                <div className="flex flex-wrap items-center gap-2"><Badge tone={b.payment_state === "paid" ? "ok" : "warn"}>{t(PAY_KEY[b.payment_state] ?? "pay_st_not_paid")}</Badge>
                  <span className="font-black" dir="ltr">{money(b.amount_total)}</span>
                  {b.amount_residual > 0.004 && <span className="text-sm text-soft">{t("cu_owes")}: <b dir="ltr">{money(b.amount_residual)}</b></span>}
                  {b.amount_residual > 0.004 && canCollect && <Button variant="soft" className="min-h-10 px-3" onClick={() => setPay(b)}><Banknote className="size-4" aria-hidden /> {t("cu_collect")}</Button>}</div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="space-y-2">
        <h2 className="text-lg font-black">{t("sup_payments")}</h2>
        {s.payments.length === 0 ? <p className="text-soft">{t("cu_no_pay")}</p> : (
          <ul className="divide-y divide-line">{s.payments.map((p) => <li key={p.id} className="flex items-center justify-between py-3"><div><p className="font-bold" dir="ltr">{p.name}</p><p className="text-xs text-soft" dir="ltr">{p.date} · {p.journal}</p></div><span className="font-black text-ok" dir="ltr">{money(p.amount)}</span></li>)}</ul>
        )}
      </Card>
      {pay && cid && <Collect cid={cid} inv={pay} onClose={() => setPay(null)} onDone={done} />}
    </div>
  );
}
