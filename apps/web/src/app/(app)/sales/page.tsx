"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Banknote, CheckCircle2, History, Lock, Minus, Percent, Plus, Printer, ScanBarcode, Search, ShoppingCart, Trash2, Undo2, UserRound, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { CustomerPicker } from "@/components/customer-picker";
import { money, Receipt } from "@/components/receipt";
import { Badge, Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useHydrated } from "@/lib/hydrated";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useMe, useSalesState, useSessionOrders } from "@/lib/queries";
import type { CloseResult, Customer, PosConfig, Quote, SaleProduct, SaleResult, SalesState } from "@/lib/types";

interface CartItem { product_id: number; name: string; price: number; qty: number; by_weight: boolean; discount: number }
type Tab = "register" | "history";

function errMsg(t: ReturnType<typeof useLang>["t"], e: unknown): { text: string; ref?: string } | null {
  if (!(e instanceof ApiError)) return null;
  if (e.code === "network") return { text: t("err_network") };
  const base = errorText(t, e.code);
  return { text: e.code === "sales_rejected" ? `${base} ${e.message}` : base, ...(e.correlationId ? { ref: e.correlationId } : {}) };
}

export default function SalesPage() {
  const { t } = useLang();
  const conns = useActiveConnection();
  const cid = conns.data?.id;
  const state = useSalesState(cid);
  if (conns.isLoading || (cid && state.isLoading)) return <Spinner label={t("loading")} />;
  const cfg = state.data?.configs[0];
  if (!cid || !state.data || !cfg)
    return (
      <Card className="rise mx-auto max-w-md space-y-3 py-12 text-center">
        <ShoppingCart className="mx-auto size-10 text-soft" aria-hidden />
        <p className="text-xl font-black">{t("pos_no_config")}</p>
        <p className="text-soft">{t("pos_no_config_sub")}</p>
        <Link href="/settings/setup" className="font-bold text-brand">{t("pos_go_setup")}</Link>
      </Card>
    );
  return cfg.session ? <Register cid={cid} cfg={cfg} state={state.data} /> : <OpenRegister cid={cid} cfg={cfg} />;
}

function OpenRegister({ cid, cfg }: { cid: string; cfg: PosConfig }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const hydrated = useHydrated();
  const keyFor = useIdempotencyKey();
  const [cash, setCash] = useState("0");
  const payload = { config_id: cfg.id, opening_cash: Number(cash || 0) };
  const m = useMutation({
    mutationFn: () => api(`/connections/${cid}/sales/sessions`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sales-state", cid] }),
  });
  const e = errMsg(t, m.error);
  return (
    <form method="post" action="#" onSubmit={(ev: FormEvent) => { ev.preventDefault(); m.mutate(); }} className="rise mx-auto max-w-md space-y-5">
      <Card className="space-y-4 p-6 text-center">
        <div className="mx-auto grid size-16 place-items-center rounded-3xl bg-brandsoft text-brand"><Lock className="size-8" aria-hidden /></div>
        <h1 className="text-2xl font-black">{t("pos_open_title")}</h1>
        <p className="text-soft">{t("pos_open_sub")}</p>
        <label className="block text-start text-sm font-bold">{t("pos_opening_cash")}
          <input type="number" inputMode="decimal" min="0" step="0.01" value={cash} onChange={(ev) => setCash(ev.target.value)} dir="ltr"
            className="mt-1.5 min-h-14 w-full rounded-2xl border border-line bg-surface px-4 text-center text-2xl font-black outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
        </label>
        {e && <ErrorBox message={e.text} reference={e.ref} />}
        <Button type="submit" disabled={!hydrated} loading={m.isPending} className="w-full">{t("pos_open_btn")}</Button>
      </Card>
    </form>
  );
}

function Register({ cid, cfg, state }: { cid: string; cfg: PosConfig; state: SalesState }) {
  const { t } = useLang();
  const me = useMe();
  const qc = useQueryClient();
  const session = cfg.session!;
  const dec = state.currency_decimals;
  const [tab, setTab] = useState<Tab>("register");
  const [cart, setCart] = useState<CartItem[]>([]);
  const [scan, setScan] = useState("");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
  const [result, setResult] = useState<SaleResult | null>(null);
  const [closing, setClosing] = useState(false);
  const [closed, setClosed] = useState<CloseResult | null>(null);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [pickingCustomer, setPickingCustomer] = useState(false);
  const scanRef = useRef<HTMLInputElement>(null);
  const canDiscount = !!me.data?.permissions.includes("sales.discount");

  useEffect(() => { const id = setTimeout(() => setQuery(scan.trim()), 250); return () => clearTimeout(id); }, [scan]);
  useEffect(() => { if (tab === "register" && !paying && !result) scanRef.current?.focus(); }, [tab, paying, result, cart.length]);

  const found = useQuery({
    queryKey: ["register-search", cid, cfg.id, query],
    queryFn: () => api<{ items: SaleProduct[] }>(`/connections/${cid}/sales/products?config_id=${cfg.id}&q=${encodeURIComponent(query)}&limit=12`),
    enabled: query.length >= 2 && !/^\d{6,}$/.test(query),
  });
  const lines = cart.map((c) => ({ product_id: c.product_id, qty: c.qty, discount: c.discount }));
  const quote = useQuery({
    queryKey: ["quote", cid, cfg.id, JSON.stringify(lines)],
    queryFn: () => api<Quote>(`/connections/${cid}/sales/quote`, { body: { config_id: cfg.id, lines } }),
    enabled: cart.length > 0, placeholderData: (p) => p, retry: false,
  });

  const add = (p: { product_id: number; name: string; price: number; by_weight: boolean }, qty = 1) => {
    setNotice(null);
    setCart((c) => {
      const i = c.findIndex((x) => x.product_id === p.product_id);
      if (i >= 0) return c.map((x, j) => (j === i ? { ...x, qty: Math.round((x.qty + qty) * 1000) / 1000 } : x));
      return [...c, { ...p, qty, discount: 0 }];
    });
  };
  const doScan = async (e: FormEvent) => {
    e.preventDefault();
    const code = scan.trim();
    if (!code) return;
    if (/^[0-9A-Za-z-]{6,64}$/.test(code)) {
      const r = await api<{ found: boolean; product_id?: number; name?: string; price?: number; qty?: number; by_weight?: boolean }>(
        `/connections/${cid}/sales/lookup?config_id=${cfg.id}&code=${encodeURIComponent(code)}`).catch(() => null);
      if (r?.found && r.product_id) { add({ product_id: r.product_id, name: r.name ?? "", price: r.price ?? 0, by_weight: !!r.by_weight }, r.qty ?? 1); setScan(""); return; }
      if (/^\d{6,}$/.test(code)) { setNotice(t("pos_not_found")); return; }
    }
  };
  const setQty = (id: number, qty: number) => setCart((c) => c.map((x) => (x.product_id === id ? { ...x, qty: Math.max(0.001, Math.round(qty * 1000) / 1000) } : x)));
  const remove = (id: number) => setCart((c) => c.filter((x) => x.product_id !== id));
  const newSale = () => { setResult(null); setCart([]); setCustomer(null); setScan(""); void qc.invalidateQueries({ queryKey: ["sales-orders", cid] }); void qc.invalidateQueries({ queryKey: ["sales-summary", cid] }); };
  const stale = quote.isPlaceholderData || quote.isFetching; // never show a total that no longer matches the cart
  const qLine = (id: number) => (stale ? undefined : quote.data?.lines.find((l) => l.product_id === id));
  const total = quote.data?.total ?? 0;

  if (closed) return <CloseSummary r={closed} currency={state.currency} onDone={() => { setClosed(null); void qc.invalidateQueries({ queryKey: ["sales-state", cid] }); }} />;
  if (result)
    return (
      <div className="rise mx-auto max-w-md space-y-4">
        <Card className="space-y-2 border-ok/30 bg-oksoft text-center">
          <CheckCircle2 className="pop mx-auto size-12 text-ok" aria-hidden />
          <p className="text-2xl font-black text-ok">{t("sale_done")}</p>
          <p className="text-sm text-ok/90">{t("sale_verified")}</p>
          {result.receipt.change > 0 && <p className="text-lg font-black">{t("pay_change")}: <span dir="ltr">{money(result.receipt.change, dec)}</span></p>}
          {!result.stock_updated && <p className="text-xs">{t("sale_stock_late")}</p>}
        </Card>
        <Receipt r={result.receipt} currency={state.currency} />
        <div className="grid grid-cols-2 gap-3">
          <Button variant="soft" onClick={() => window.print()}><Printer className="size-5" aria-hidden /> {t("sale_print")}</Button>
          <Button onClick={newSale}>{t("sale_new")}</Button>
        </div>
      </div>
    );

  return (
    <div className="rise space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2" role="tablist">
          {(["register", "history"] as const).map((k) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={cn("inline-flex min-h-11 items-center gap-2 rounded-2xl px-4 font-bold", tab === k ? "bg-brand text-brandink" : "bg-surface2 text-soft")}>
              {k === "register" ? <ShoppingCart className="size-4" aria-hidden /> : <History className="size-4" aria-hidden />}
              {t(k === "register" ? "tab_register" : "tab_history")}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-sm text-soft">
          <Badge tone="ok">{session.name}</Badge>
          <button onClick={() => setClosing(true)} className="inline-flex min-h-11 items-center gap-2 rounded-2xl border border-line px-3 font-bold hover:bg-surface2"><Lock className="size-4" aria-hidden /> {t("close_btn")}</button>
        </div>
      </header>

      {tab === "history" ? <History_ cid={cid} sessionId={session.id} cashId={cfg.payment_methods.find((m) => m.is_cash)?.id} currency={state.currency} dec={dec} canRefund={!!me.data?.permissions.includes("sales.returns")} /> : (
        <div className="grid gap-4 lg:grid-cols-[1fr_24rem]">
          <section className="space-y-3">
            <form onSubmit={doScan} className="relative">
              <ScanBarcode className="pointer-events-none absolute start-4 top-1/2 size-6 -translate-y-1/2 text-brand" aria-hidden />
              <input ref={scanRef} value={scan} onChange={(e) => { setScan(e.target.value); setNotice(null); }} placeholder={t("pos_scan")} aria-label={t("pos_scan")} autoComplete="off" inputMode="search"
                className="min-h-14 w-full rounded-2xl border-2 border-line bg-surface ps-14 pe-4 text-lg outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
            </form>
            {notice && <p role="alert" className="font-bold text-bad">{notice}</p>}
            {found.data && (
              <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {found.data.items.map((p) => (
                  <li key={p.product_id}>
                    <button onClick={() => { add(p); setScan(""); }} className="flex min-h-24 w-full flex-col justify-between rounded-2xl border border-line bg-surface p-3 text-start transition hover:border-brand hover:bg-brandsoft active:scale-[0.98]">
                      <span className="line-clamp-2 font-bold" dir="auto">{p.name}</span>
                      <span className="flex items-center justify-between text-sm"><span className="font-black text-brand" dir="ltr">{money(p.price, dec)}</span>
                        {p.on_hand !== undefined && <span className={cn("text-xs", p.on_hand <= 0 ? "text-bad" : "text-soft")}>{t("pos_stock_low")}: {p.on_hand}</span>}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {!found.data && cart.length === 0 && <Card className="py-10 text-center text-soft"><Search className="mx-auto mb-2 size-8" aria-hidden />{t("pos_empty_cart")}</Card>}
          </section>

          <aside className="space-y-3 lg:sticky lg:top-4 lg:self-start">
            {cfg.payment_methods.some((m) => m.is_credit) && (
              <button onClick={() => setPickingCustomer(true)} className="flex min-h-12 w-full items-center justify-between rounded-2xl border border-line bg-surface px-4 font-bold hover:bg-surface2">
                <span className="flex items-center gap-2"><UserRound className="size-4 text-brand" aria-hidden /> {t("pos_customer")}</span><span className="text-soft" dir="auto">{customer?.name ?? t("pos_no_customer")}</span>
              </button>
            )}
            <Card className="space-y-3 p-4">
              {cart.length === 0 ? <p className="py-6 text-center text-soft">{t("pos_empty_cart")}</p> : (
                <ul className="divide-y divide-line">
                  {cart.map((c) => {
                    const ql = qLine(c.product_id);
                    return (
                      <li key={c.product_id} className="space-y-2 py-3">
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-bold" dir="auto">{c.name}</span>
                          <span className="font-black" dir="ltr">{ql ? money(ql.subtotal_incl, dec) : "…"}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <button aria-label="−" onClick={() => setQty(c.product_id, c.qty - (c.by_weight ? 0.1 : 1))} className="grid size-10 place-items-center rounded-xl border border-line"><Minus className="size-4" aria-hidden /></button>
                          <input aria-label={t("pos_qty")} type="number" inputMode="decimal" min="0.001" step={c.by_weight ? "0.001" : "1"} value={c.qty} onChange={(e) => setQty(c.product_id, Number(e.target.value) || 0.001)} dir="ltr" className="min-h-10 w-20 rounded-xl border border-line bg-surface px-2 text-center font-bold" />
                          <button aria-label="+" onClick={() => setQty(c.product_id, c.qty + (c.by_weight ? 0.1 : 1))} className="grid size-10 place-items-center rounded-xl border border-line"><Plus className="size-4" aria-hidden /></button>
                          {c.by_weight && <Badge tone="brand">kg</Badge>}
                          {canDiscount && (
                            <label className="ms-auto flex items-center gap-1 text-xs text-soft"><Percent className="size-3" aria-hidden />
                              <input aria-label={t("pos_discount")} type="number" min="0" max="100" value={c.discount || ""} placeholder="0" onChange={(e) => setCart(cart.map((x) => (x.product_id === c.product_id ? { ...x, discount: Math.min(100, Math.max(0, Number(e.target.value) || 0)) } : x)))} dir="ltr" className="min-h-10 w-14 rounded-xl border border-line bg-surface px-2 text-center" /></label>
                          )}
                          <button aria-label="remove" onClick={() => remove(c.product_id)} className="grid size-10 place-items-center rounded-xl text-bad hover:bg-badsoft"><Trash2 className="size-4" aria-hidden /></button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
              {cart.length > 0 && (
                <div className="space-y-1 border-t border-line pt-3">
                  <p className="flex items-baseline justify-between text-2xl font-black"><span>{t("pos_total")}</span><span dir="ltr" aria-live="polite">{quote.data && !stale ? money(total, dec) : "…"} <span className="text-sm">{state.currency}</span></span></p>
                  {quote.data && !stale && <p className="flex justify-between text-xs text-soft"><span>{t("pos_tax")}</span><span dir="ltr">{money(quote.data.tax, dec)}</span></p>}
                  {quote.error && <ErrorBox message={errMsg(t, quote.error)?.text ?? t("err_generic")} />}
                </div>
              )}
            </Card>
            <Button onClick={() => setPaying(true)} disabled={!quote.data || stale || cart.length === 0} className="min-h-16 w-full text-xl"><Banknote className="size-6" aria-hidden /> {t("pos_pay")}</Button>
            {cart.length > 0 && <button onClick={() => setCart([])} className="w-full text-sm font-bold text-soft hover:text-bad">{t("pos_clear")}</button>}
          </aside>
        </div>
      )}

      {paying && quote.data && (
        <PayDialog cid={cid} cfg={cfg} cart={cart} customer={customer} canOverride={!!me.data?.permissions.includes("customers.credit.override")} total={quote.data.total} currency={state.currency} dec={dec} onClose={() => setPaying(false)}
          onDone={(r) => { setPaying(false); setResult(r); }} onRefresh={() => void quote.refetch()} />
      )}
      {pickingCustomer && <CustomerPicker cid={cid} onPick={(c) => { setCustomer(c); setPickingCustomer(false); }} onClose={() => setPickingCustomer(false)} />}
      {closing && <CloseDialog cid={cid} session={session} dec={dec} currency={state.currency} onClose={() => setClosing(false)} onDone={(r) => { setClosing(false); setClosed(r); }} />}
    </div>
  );
}

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
    <dialog ref={ref} onClose={onClose} className="m-auto w-[min(94vw,30rem)] rounded-[1.5rem] border border-line bg-surface p-6 text-ink shadow-card backdrop:bg-black/50">
      <div className="mb-4 flex items-center justify-between"><h2 className="text-xl font-black">{title}</h2>
        <button aria-label="close" onClick={() => ref.current?.close()} className="grid size-10 place-items-center rounded-xl hover:bg-surface2"><XCircle className="size-5 text-soft" aria-hidden /></button></div>
      {children}
    </dialog>
  );
}

function PayDialog({ cid, cfg, cart, customer, canOverride, total, currency, dec, onClose, onDone, onRefresh }: { cid: string; cfg: PosConfig; cart: CartItem[]; customer: Customer | null; canOverride: boolean; total: number; currency: string; dec: number; onClose: () => void; onDone: (r: SaleResult) => void; onRefresh: () => void }) {
  const { t } = useLang();
  const keyFor = useIdempotencyKey();
  const normal = cfg.payment_methods.filter((m) => !m.is_credit);
  const creditMethod = cfg.payment_methods.find((m) => m.is_credit);
  const [method, setMethod] = useState(normal.find((m) => m.is_cash)?.id ?? normal[0]?.id ?? 0);
  const isCash = normal.find((m) => m.id === method)?.is_cash ?? true;
  const [tendered, setTendered] = useState("");
  const [onCredit, setOnCredit] = useState(false);
  const [creditStr, setCreditStr] = useState("");
  const [override, setOverride] = useState(false);
  const credit = onCredit ? Math.min(total, Math.max(0, Number(creditStr === "" ? total : creditStr))) : 0;
  const due = Math.round((total - credit) * 100) / 100; // what is paid now
  const paid = due <= 0 ? 0 : isCash ? Number(tendered || 0) : due;
  const change = Math.max(0, Math.round((paid - due) * 100) / 100);
  const creditOk = !onCredit || (!!customer && credit > 0);
  const ok = method > 0 && creditOk && (due <= 0 || paid + 0.004 >= due);
  const quick = [...new Set([Math.ceil(due), Math.ceil(due / 5) * 5, Math.ceil(due / 10) * 10, Math.ceil(due / 50) * 50, Math.ceil(due / 100) * 100, Math.ceil(due / 200) * 200])].filter((v) => v >= due && v > 0).slice(0, 5);
  const payments = [
    ...(due > 0 ? [{ payment_method_id: method, amount: paid }] : []),
    ...(onCredit && creditMethod ? [{ payment_method_id: creditMethod.id, amount: credit }] : []),
  ];
  const payload = { config_id: cfg.id, lines: cart.map((c) => ({ product_id: c.product_id, qty: c.qty, discount: c.discount })), expected_total: total, payments, ...(customer ? { partner_id: customer.id } : {}), ...(override ? { override_credit_limit: true } : {}) };
  const m = useMutation({
    mutationFn: () => api<SaleResult>(`/connections/${cid}/sales/orders`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: onDone,
    onError: (e) => { if (e instanceof ApiError && e.code === "price_changed") onRefresh(); },
  });
  const e = errMsg(t, m.error);
  const limitHit = m.error instanceof ApiError && m.error.code === "credit_limit_exceeded";
  return (
    <Modal title={t("pay_title")} onClose={onClose}>
      <div className="space-y-4">
        <p className="flex items-baseline justify-between text-3xl font-black"><span>{t("pos_total")}</span><span dir="ltr">{money(total, dec)} <span className="text-base">{currency}</span></span></p>
        {customer && <p className="text-sm text-soft">{t("pos_customer")}: <b dir="auto">{customer.name}</b></p>}
        {creditMethod && (
          <div className="space-y-2 rounded-2xl bg-surface2 p-3">
            <button type="button" role="switch" aria-checked={onCredit} onClick={() => setOnCredit(!onCredit)} className={cn("flex min-h-12 w-full items-center justify-between rounded-xl border-2 px-3 font-bold", onCredit ? "border-brand bg-brandsoft" : "border-line bg-surface")}>{t("pos_on_credit")}<span aria-hidden>{onCredit ? "✓" : ""}</span></button>
            {onCredit && !customer && <p role="alert" className="text-sm font-bold text-bad">{t("pos_credit_needs_customer")}</p>}
            {onCredit && (
              <label className="block text-sm font-bold">{t("pos_credit_part")}
                <input type="number" inputMode="decimal" min="0" max={total} step="0.01" value={creditStr === "" ? String(total) : creditStr} onChange={(ev) => setCreditStr(ev.target.value)} dir="ltr" className="mt-1.5 min-h-12 w-full rounded-xl border border-line bg-surface px-3 text-center text-xl font-black" /></label>
            )}
          </div>
        )}
        {due > 0 && normal.length > 1 && (
          <div role="radiogroup" aria-label={t("pay_method")} className="flex flex-wrap gap-2">
            {normal.map((mm) => <button key={mm.id} role="radio" aria-checked={method === mm.id} onClick={() => setMethod(mm.id)} className={cn("min-h-11 rounded-2xl border-2 px-4 font-bold", method === mm.id ? "border-brand bg-brandsoft" : "border-line")}>{mm.name}</button>)}
          </div>
        )}
        {due > 0 && isCash && (
          <>
            {onCredit && <p className="flex justify-between font-bold"><span>{t("pos_cash_part")}</span><span dir="ltr">{money(due, dec)}</span></p>}
            <label className="block text-sm font-bold">{t("pay_tendered")}
              <input autoFocus type="number" inputMode="decimal" min="0" step="0.01" value={tendered} onChange={(ev) => setTendered(ev.target.value)} dir="ltr" className="mt-1.5 min-h-14 w-full rounded-2xl border border-line bg-surface px-4 text-center text-3xl font-black outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
            </label>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => setTendered(String(due))} className="min-h-11 rounded-2xl bg-brandsoft px-4 font-bold text-brand">{t("pay_exact")}</button>
              {quick.map((q) => <button key={q} onClick={() => setTendered(String(q))} className="min-h-11 rounded-2xl bg-surface2 px-4 font-bold" dir="ltr">{q}</button>)}
            </div>
            <p className={cn("flex items-baseline justify-between text-xl font-black", ok ? "text-ok" : "text-soft")}><span>{ok ? t("pay_change") : t("pay_short")}</span>{ok && <span dir="ltr">{money(change, dec)}</span>}</p>
          </>
        )}
        {e && <ErrorBox message={e.text} reference={e.ref} />}
        {limitHit && canOverride && (
          <label className="flex items-start gap-3 rounded-2xl bg-warnsoft p-3 text-sm font-bold text-warn"><input type="checkbox" checked={override} onChange={(ev) => setOverride(ev.target.checked)} className="mt-0.5 size-5" /><span>{t("pos_override")}<span className="block text-xs font-normal">{t("pos_override_hint")}</span></span></label>
        )}
        <Button onClick={() => m.mutate()} disabled={!ok} loading={m.isPending} className="min-h-14 w-full text-lg">{t("pay_confirm")}</Button>
      </div>
    </Modal>
  );
}

function CloseDialog({ cid, session, dec, currency, onClose, onDone }: { cid: string; session: NonNullable<PosConfig["session"]>; dec: number; currency: string; onClose: () => void; onDone: (r: CloseResult) => void }) {
  const { t } = useLang();
  const keyFor = useIdempotencyKey();
  const [counted, setCounted] = useState("");
  const payload = { counted_cash: Number(counted || 0) };
  const m = useMutation({
    mutationFn: () => api<CloseResult>(`/connections/${cid}/sales/sessions/${session.id}/close`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: onDone,
  });
  const e = errMsg(t, m.error);
  return (
    <Modal title={t("close_title")} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-soft">{t("close_sub")}</p>
        <p className="text-sm text-soft">{t("close_open")} <span dir="ltr">{session.opened_at}</span> · {session.order_count} {t("kpi_orders")}</p>
        <label className="block text-sm font-bold">{t("close_counted")} ({currency})
          <input autoFocus type="number" inputMode="decimal" min="0" step="0.01" value={counted} onChange={(ev) => setCounted(ev.target.value)} dir="ltr" className="mt-1.5 min-h-14 w-full rounded-2xl border border-line bg-surface px-4 text-center text-3xl font-black outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
        </label>
        {e && <ErrorBox message={e.text} reference={e.ref} />}
        <Button onClick={() => m.mutate()} disabled={counted === ""} loading={m.isPending} className="min-h-14 w-full">{t("close_btn")}</Button>
        <span className="sr-only">{dec}</span>
      </div>
    </Modal>
  );
}

function CloseSummary({ r, currency, onDone }: { r: CloseResult; currency: string; onDone: () => void }) {
  const { t } = useLang();
  const s = r.session;
  return (
    <div className="rise mx-auto max-w-md space-y-4">
      <Card className={cn("space-y-3 text-center", r.has_difference ? "border-warn/40 bg-warnsoft" : "border-ok/30 bg-oksoft")}>
        {r.has_difference ? <XCircle className="mx-auto size-12 text-warn" aria-hidden /> : <CheckCircle2 className="pop mx-auto size-12 text-ok" aria-hidden />}
        <p className="text-2xl font-black">{r.has_difference ? t("close_diff_warn") : t("close_balanced")}</p>
        <dl className="grid grid-cols-3 gap-2 text-sm">
          <div><dt className="text-soft">{t("close_expected")}</dt><dd className="font-black" dir="ltr">{money(s.expected_cash)}</dd></div>
          <div><dt className="text-soft">{t("close_counted")}</dt><dd className="font-black" dir="ltr">{money(s.counted_cash ?? 0)}</dd></div>
          <div><dt className="text-soft">{t("close_diff")}</dt><dd className={cn("font-black", r.has_difference && "text-bad")} dir="ltr">{money(r.cash_difference)} {currency}</dd></div>
        </dl>
        {s.move_state === "posted" && <p className="text-sm">{t("close_posted")}</p>}
      </Card>
      <Button onClick={onDone} className="w-full">{t("continue")}</Button>
    </div>
  );
}

function History_({ cid, sessionId, cashId, currency, dec, canRefund }: { cid: string; sessionId: number; cashId?: number | undefined; currency: string; dec: number; canRefund: boolean }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const orders = useSessionOrders(cid, sessionId);
  const keyFor = useIdempotencyKey();
  const [target, setTarget] = useState<number | null>(null);
  const m = useMutation({
    mutationFn: (id: number) => {
      const payload = { payment_method_id: cashId };
      return api(`/connections/${cid}/sales/orders/${id}/refund`, { body: payload, headers: { "Idempotency-Key": keyFor({ id, ...payload }) } });
    },
    onSuccess: () => { setTarget(null); void qc.invalidateQueries({ queryKey: ["sales-orders", cid] }); },
  });
  const e = errMsg(t, m.error);
  if (orders.isLoading) return <Spinner label={t("loading")} />;
  if (!orders.data?.items.length) return <Card className="py-10 text-center text-soft">{t("hist_none")}</Card>;
  return (
    <div className="space-y-3">
      <h2 className="text-lg font-black">{t("hist_title")}</h2>
      {e && <ErrorBox message={e.text} reference={e.ref} />}
      <ul className="space-y-2">
        {orders.data.items.map((o) => (
          <li key={o.id}><Card className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div><p className="font-bold" dir="ltr">{o.name}</p><p className="text-xs text-soft" dir="ltr">{o.date_order} · {o.lines.length} {t("hist_items")}</p></div>
            <div className="flex items-center gap-3">
              <span className={cn("text-lg font-black", o.amount_total < 0 && "text-bad")} dir="ltr">{money(o.amount_total, dec)} {currency}</span>
              {o.amount_total < 0 ? <Badge tone="warn">{t("refunded")}</Badge> : canRefund && cashId && (
                target === o.id ? (
                  <span className="flex items-center gap-2"><span className="text-xs text-soft">{t("refund_confirm")} · {t("refund_method_note")}</span>
                    <Button variant="danger" loading={m.isPending} onClick={() => m.mutate(o.id)} className="min-h-10 px-3">{t("refund")}</Button>
                    <button onClick={() => setTarget(null)} className="text-sm font-bold text-soft">{t("cancel")}</button></span>
                ) : <button onClick={() => setTarget(o.id)} className="inline-flex min-h-10 items-center gap-1 rounded-xl border border-line px-3 text-sm font-bold hover:bg-surface2"><Undo2 className="size-4" aria-hidden />{t("refund")}</button>
              )}
            </div>
          </Card></li>
        ))}
      </ul>
    </div>
  );
}
