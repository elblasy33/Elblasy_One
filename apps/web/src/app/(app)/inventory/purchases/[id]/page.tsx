"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Banknote, FileText, PackageCheck, Pencil, Undo2, XCircle } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { InventoryTabs } from "@/components/inv-tabs";
import { money } from "@/components/receipt";
import { Badge, Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { PAY_KEY, receiptState } from "@/lib/purchasing";
import { useActiveConnection, useMe, usePurchaseOrder } from "@/lib/queries";
import type { BillBrief, PoLine, PurchaseOrder } from "@/lib/types";

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
    <dialog ref={ref} onClose={onClose} className="m-auto w-[min(94vw,32rem)] rounded-[1.5rem] border border-line bg-surface p-6 text-ink shadow-card backdrop:bg-black/50">
      <div className="mb-4 flex items-center justify-between"><h2 className="text-xl font-black">{title}</h2>
        <button aria-label="close" onClick={() => ref.current?.close()} className="grid size-10 place-items-center rounded-xl hover:bg-surface2"><XCircle className="size-5 text-soft" aria-hidden /></button></div>
      {children}
    </dialog>
  );
}

function msg(t: ReturnType<typeof useLang>["t"], e: unknown) {
  if (!(e instanceof ApiError)) return null;
  const base = e.code === "network" ? t("err_network") : errorText(t, e.code);
  return { text: /_rejected$/.test(e.code) ? `${base} ${e.message}` : base, ref: e.correlationId };
}

export default function PurchaseDetail() {
  const { t } = useLang();
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const me = useMe();
  const cid = useActiveConnection().data?.id;
  const data = usePurchaseOrder(cid, id);
  const [dlg, setDlg] = useState<"receive" | "pay" | "return" | null>(null);
  const [payBill, setPayBill] = useState<BillBrief | null>(null);
  const [priceLine, setPriceLine] = useState<PoLine | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const can = (p: string) => !!me.data?.permissions.includes(p);
  const refresh = () => { setDlg(null); void qc.invalidateQueries({ queryKey: ["purchase-order"] }); void qc.invalidateQueries({ queryKey: ["purchase-orders"] }); void qc.invalidateQueries({ queryKey: ["suppliers"] }); };
  const keyFor = useIdempotencyKey();
  const bill = useMutation({
    mutationFn: () => api(`/connections/${cid}/purchasing/orders/${id}/bill`, { method: "POST", headers: { "Idempotency-Key": keyFor({ bill: id, at: data.data?.order.lines.map((l) => l.received) }) } }),
    onSuccess: () => { setFlash(t("po_billed_ok")); refresh(); },
  });
  if (!data.data) return <Spinner label={t("loading")} />;
  const { order: o, stock } = data.data;
  const rs = receiptState(o);
  const canBillNow = can("payments.create") && o.invoice_status === "to invoice";
  const e = msg(t, bill.error);
  const showMoney = o.amount_total !== undefined;

  return (
    <div className="rise space-y-5">
      <InventoryTabs />
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="text-3xl font-black" dir="ltr">{o.name}</h1><p className="text-soft">{o.partner}</p></div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={rs === "full" ? "ok" : rs === "part" ? "warn" : "neutral"}>{t(rs === "full" ? "po_st_full" : rs === "part" ? "po_st_part" : "po_st_none")}</Badge>
          {showMoney && <span className="text-2xl font-black" dir="ltr">{money(o.amount_total ?? 0)}</span>}
        </div>
      </header>
      {flash && <div role="status"><Card className="border-ok/30 bg-oksoft font-bold text-ok">{flash}</Card></div>}

      <Card className="space-y-3">
        <div className="hidden grid-cols-[1fr_repeat(4,5rem)] gap-2 text-xs font-bold text-soft sm:grid">
          <span>{t("po_title")}</span><span className="text-center">{t("po_ordered")}</span><span className="text-center">{t("po_received")}</span><span className="text-center">{t("po_billed")}</span><span className="text-center">{t("po_remaining")}</span>
        </div>
        <ul className="divide-y divide-line">
          {o.lines.map((l) => {
            const s = stock[String(l.product_id)];
            return (
              <li key={l.id} className="space-y-1 py-3">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-[1fr_repeat(4,5rem)]">
                  <span className="col-span-2 font-bold sm:col-span-1" dir="auto">{l.name}</span>
                  <Num label={t("po_ordered")} v={l.ordered} /><Num label={t("po_received")} v={l.received} tone={l.received >= l.ordered ? "ok" : undefined} /><Num label={t("po_billed")} v={l.billed} /><Num label={t("po_remaining")} v={Math.max(0, l.ordered - l.received)} />
                </div>
                {l.price_unit !== undefined && (
                  <p className="flex flex-wrap items-center gap-2 text-sm"><span className="text-soft">{t("po_price")}:</span> <b dir="ltr" className={l.price_unit > 0 ? "" : "text-bad"}>{money(l.price_unit)}</b>
                    <span className="text-soft">{t("po_line_total")}:</span> <b dir="ltr">{money(l.subtotal ?? 0)}</b>
                    {l.billed === 0 && can("purchasing.manage") && <button type="button" onClick={() => setPriceLine(l)} className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-line px-2 text-xs font-bold hover:bg-surface2"><Pencil className="size-3" aria-hidden />{t("po_edit_price")}</button>}
                    {l.price_unit <= 0 && <span className="font-bold text-bad">{t("po_zero_price")}</span>}</p>
                )}
                {s && <p className="text-xs text-soft">{t("po_stock")}: {t("po_on_hand")} <b dir="ltr">{s.on_hand}</b> · {t("po_free")} <b dir="ltr">{s.free}</b> · {t("po_incoming")} <b dir="ltr">{s.incoming}</b> · {t("po_forecast")} <b dir="ltr">{s.forecast}</b></p>}
              </li>
            );
          })}
        </ul>
      </Card>

      <div className="flex flex-wrap gap-3">
        {can("purchasing.manage") && rs !== "full" && <Button onClick={() => setDlg("receive")}><PackageCheck className="size-5" aria-hidden /> {t("po_receive")}</Button>}
        {can("purchasing.manage") && o.lines.some((l) => l.received > 0) && <Button variant="ghost" onClick={() => setDlg("return")}><Undo2 className="size-5" aria-hidden /> {t("po_return")}</Button>}
        {canBillNow && <Button variant="soft" loading={bill.isPending} onClick={() => bill.mutate()}><FileText className="size-5" aria-hidden /> {t("po_bill")}</Button>}
      </div>
      {canBillNow && <p className="text-xs text-soft">{t("po_bill_hint")}</p>}
      {e && <ErrorBox message={e.text} reference={e.ref} />}

      {o.bills && o.bills.length > 0 && (
        <Card className="space-y-2">
          <h2 className="text-lg font-black">{t("po_bills")}</h2>
          <ul className="divide-y divide-line">
            {o.bills.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                <div><p className="font-bold" dir="ltr">{b.name ?? `#${b.id}`}</p><Badge tone={b.payment_state === "paid" ? "ok" : "warn"}>{t(PAY_KEY[b.payment_state] ?? "pay_st_not_paid")}</Badge></div>
                <div className="flex items-center gap-3"><span className="font-black" dir="ltr">{money(b.amount_total)}</span>
                  {b.amount_residual > 0.004 && <span className="text-sm text-soft">{t("po_residual")}: <b dir="ltr">{money(b.amount_residual)}</b></span>}
                  {b.amount_residual > 0.004 && can("payments.create") && <Button variant="soft" className="min-h-10 px-3" onClick={() => { setPayBill(b); setDlg("pay"); }}><Banknote className="size-4" aria-hidden /> {t("po_pay")}</Button>}</div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {dlg === "receive" && cid && <ReceiveDialog cid={cid} order={o} onClose={() => setDlg(null)} onDone={() => { setFlash(t("po_received_ok")); refresh(); }} />}
      {priceLine && cid && <PriceDialog cid={cid} orderId={o.id} line={priceLine} onClose={() => setPriceLine(null)} onDone={() => { setPriceLine(null); refresh(); }} />}
      {dlg === "return" && cid && <ReturnDialog cid={cid} order={o} onClose={() => setDlg(null)} onDone={() => { setFlash(t("po_return_ok")); refresh(); }} />}
      {dlg === "pay" && cid && payBill && <PayDialog cid={cid} bill={payBill} onClose={() => setDlg(null)} onDone={() => { setFlash(t("po_pay_ok")); refresh(); }} />}
    </div>
  );
}

function Num({ label, v, tone }: { label: string; v: number; tone?: "ok" | undefined }) {
  return <span className="text-center"><span className="block text-[10px] text-soft sm:hidden">{label}</span><b className={cn("text-lg", tone === "ok" && "text-ok")} dir="ltr">{v}</b></span>;
}

function ReceiveDialog({ cid, order, onClose, onDone }: { cid: string; order: PurchaseOrder; onClose: () => void; onDone: () => void }) {
  const { t } = useLang();
  const keyFor = useIdempotencyKey();
  const open = order.lines.filter((l) => l.ordered - l.received > 0.0001);
  const [qty, setQty] = useState<Record<number, string>>(Object.fromEntries(open.map((l) => [l.id, String(l.ordered - l.received)])));
  const [lot, setLot] = useState<Record<number, string>>({});
  const [sn, setSn] = useState<Record<number, string>>({});
  const serialsOf = (id: number) => (sn[id] ?? "").split(/\r?\n/).map((v) => v.trim()).filter(Boolean);
  const isSerial = (l: PoLine) => l.tracking === "serial";
  const lines = open.filter((l) => (isSerial(l) ? serialsOf(l.id).length > 0 : Number(qty[l.id]) > 0)).map((l) => (isSerial(l) ? { line_id: l.id, qty: serialsOf(l.id).length, serials: serialsOf(l.id) } : { line_id: l.id, qty: Number(qty[l.id]), ...(lot[l.id]?.trim() ? { lot_name: lot[l.id]!.trim() } : {}) }));
  const payload = { lines };
  const m = useMutation({ mutationFn: () => api(`/connections/${cid}/purchasing/orders/${order.id}/receive`, { body: payload, headers: { "Idempotency-Key": keyFor({ order: order.id, ...payload }) } }), onSuccess: onDone });
  const e = msg(t, m.error);
  const needsLot = (l: PoLine) => l.tracking === "lot";
  const ok = lines.length > 0 && open.every((l) => isSerial(l) || !(Number(qty[l.id]) > 0) || !needsLot(l) || !!lot[l.id]?.trim());
  return (
    <Modal title={t("po_receive_title")} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-soft">{t("po_receive_hint")}</p>
        {open.map((l) => (
          <div key={l.id} className="space-y-2 rounded-2xl bg-surface2 p-3">
            <div className="flex items-center justify-between gap-2"><span className="font-bold" dir="auto">{l.name}</span><span className="text-xs text-soft">{t("po_remaining")}: <b dir="ltr">{l.ordered - l.received}</b></span></div>
            {isSerial(l) ? (
              <label className="block text-sm font-bold">{t("po_serials")} <span className="text-xs font-normal text-soft">({t("po_serials_count")}: {serialsOf(l.id).length})</span>
                <textarea rows={4} value={sn[l.id] ?? ""} onChange={(ev) => setSn({ ...sn, [l.id]: ev.target.value })} dir="ltr" className="mt-1 w-full rounded-xl border border-line bg-surface px-3 py-2 font-mono text-sm" /></label>
            ) : <div className="flex gap-2">
              <input aria-label={t("po_qty")} type="number" inputMode="decimal" min="0" max={l.ordered - l.received} step="any" value={qty[l.id] ?? ""} onChange={(ev) => setQty({ ...qty, [l.id]: ev.target.value })} dir="ltr" className="min-h-12 w-28 rounded-xl border border-line bg-surface px-3 text-center text-lg font-bold" />
              {needsLot(l) && <input aria-label={t("po_lot")} placeholder={t("po_lot")} value={lot[l.id] ?? ""} onChange={(ev) => setLot({ ...lot, [l.id]: ev.target.value })} dir="ltr" className="min-h-12 flex-1 rounded-xl border border-line bg-surface px-3" />}
            </div>}
          </div>
        ))}
        {e && <ErrorBox message={e.text} reference={e.ref} />}
        <Button onClick={() => m.mutate()} disabled={!ok} loading={m.isPending} className="min-h-14 w-full">{t("po_confirm_receive")}</Button>
      </div>
    </Modal>
  );
}

function PriceDialog({ cid, orderId, line, onClose, onDone }: { cid: string; orderId: number; line: PoLine; onClose: () => void; onDone: () => void }) {
  const { t } = useLang();
  const keyFor = useIdempotencyKey();
  const [price, setPrice] = useState(line.price_unit ? String(line.price_unit) : "");
  const body = { price_unit: Number(price || 0) };
  const m = useMutation({ mutationFn: () => api(`/connections/${cid}/purchasing/orders/${orderId}/lines/${line.id}`, { method: "PATCH", body, headers: { "Idempotency-Key": keyFor({ orderId, line: line.id, ...body }) } }), onSuccess: onDone });
  const e = msg(t, m.error);
  return (
    <Modal title={t("po_edit_price")} onClose={onClose}>
      <div className="space-y-4">
        <p className="font-bold" dir="auto">{line.name}</p>
        <label className="block text-sm font-bold">{t("po_price")}
          <input autoFocus type="number" inputMode="decimal" min="0" step="any" value={price} onChange={(ev) => setPrice(ev.target.value)} dir="ltr" className="mt-1.5 min-h-14 w-full rounded-2xl border border-line bg-surface px-4 text-center text-3xl font-black outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" /></label>
        {e && <ErrorBox message={e.text} reference={e.ref} />}
        <Button onClick={() => m.mutate()} disabled={!(Number(price) > 0)} loading={m.isPending} className="min-h-14 w-full">{t("pe_save")}</Button>
      </div>
    </Modal>
  );
}

function ReturnDialog({ cid, order, onClose, onDone }: { cid: string; order: PurchaseOrder; onClose: () => void; onDone: () => void }) {
  const { t } = useLang();
  const keyFor = useIdempotencyKey();
  const open = order.lines.filter((l) => l.received > 0.0001);
  const [qty, setQty] = useState<Record<number, string>>({});
  const [reason, setReason] = useState("");
  const lines = open.filter((l) => Number(qty[l.id]) > 0).map((l) => ({ line_id: l.id, qty: Number(qty[l.id]) }));
  const payload = { lines, reason: reason.trim() };
  const m = useMutation({ mutationFn: () => api(`/connections/${cid}/purchasing/orders/${order.id}/return`, { body: payload, headers: { "Idempotency-Key": keyFor({ order: order.id, ...payload }) } }), onSuccess: onDone });
  const e = msg(t, m.error);
  const billed = (order.bills ?? []).some((b) => b.state === "posted");
  return (
    <Modal title={t("po_return_title")} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-soft">{t("po_return_hint")}{billed ? ` ${t("po_return_credit")}` : ""}</p>
        {open.map((l) => (
          <div key={l.id} className="space-y-2 rounded-2xl bg-surface2 p-3">
            <div className="flex items-center justify-between gap-2"><span className="font-bold" dir="auto">{l.name}</span><span className="text-xs text-soft">{t("po_received")}: <b dir="ltr">{l.received}</b></span></div>
            <input aria-label={t("po_qty")} type="number" inputMode="decimal" min="0" max={l.received} step="any" value={qty[l.id] ?? ""} onChange={(ev) => setQty({ ...qty, [l.id]: ev.target.value })} dir="ltr" className="min-h-12 w-28 rounded-xl border border-line bg-surface px-3 text-center text-lg font-bold" />
          </div>
        ))}
        <label className="block text-sm font-bold">{t("po_return_reason")}
          <input value={reason} maxLength={200} onChange={(ev) => setReason(ev.target.value)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-4" /></label>
        {e && <ErrorBox message={e.text} reference={e.ref} />}
        <Button variant="danger" onClick={() => m.mutate()} disabled={!lines.length} loading={m.isPending} className="min-h-14 w-full">{t("po_return_confirm")}</Button>
      </div>
    </Modal>
  );
}

function PayDialog({ cid, bill, onClose, onDone }: { cid: string; bill: BillBrief; onClose: () => void; onDone: () => void }) {
  const { t } = useLang();
  const keyFor = useIdempotencyKey();
  const [amount, setAmount] = useState(String(bill.amount_residual));
  const [from, setFrom] = useState<"cash" | "bank">("cash");
  const payload = { amount: Number(amount || 0), journal_type: from };
  const m = useMutation({ mutationFn: () => api(`/connections/${cid}/purchasing/bills/${bill.id}/pay`, { body: payload, headers: { "Idempotency-Key": keyFor({ bill: bill.id, ...payload }) } }), onSuccess: onDone });
  const e = msg(t, m.error);
  const ok = Number(amount) > 0 && Number(amount) <= bill.amount_residual + 0.004;
  return (
    <Modal title={t("po_pay_title")} onClose={onClose}>
      <div className="space-y-4">
        <p className="flex justify-between font-bold"><span>{t("po_residual")}</span><span dir="ltr">{money(bill.amount_residual)}</span></p>
        <label className="block text-sm font-bold">{t("po_pay_amount")}
          <input autoFocus type="number" inputMode="decimal" min="0" step="0.01" value={amount} onChange={(ev) => setAmount(ev.target.value)} dir="ltr" className="mt-1.5 min-h-14 w-full rounded-2xl border border-line bg-surface px-4 text-center text-3xl font-black outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
        </label>
        <div role="radiogroup" aria-label={t("po_pay_from")} className="grid grid-cols-2 gap-2">
          {(["cash", "bank"] as const).map((k) => <button key={k} role="radio" aria-checked={from === k} onClick={() => setFrom(k)} className={cn("min-h-12 rounded-2xl border-2 font-bold", from === k ? "border-brand bg-brandsoft" : "border-line")}>{t(k === "cash" ? "po_cash" : "po_bank")}</button>)}
        </div>
        {e && <ErrorBox message={e.text} reference={e.ref} />}
        <Button onClick={() => m.mutate()} disabled={!ok} loading={m.isPending} className="min-h-14 w-full">{t("po_pay")}</Button>
      </div>
    </Modal>
  );
}
