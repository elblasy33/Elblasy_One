"use client";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Banknote, Delete, CheckCircle2, History, Keyboard, Lock, Minus, Plus, Printer, ScanBarcode, Search, ShoppingCart, Trash2, Undo2, UserRound, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { CustomerPicker } from "@/components/customer-picker";
import { money, Receipt } from "@/components/receipt";
import { Badge, Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useHydrated } from "@/lib/hydrated";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { beep, buildIndex, exact, parseCommand, search, type TillItem } from "@/lib/pos-search";
import { ACTIONS, actionFor, useBindings, type Action } from "@/lib/shortcuts";
import { useActiveConnection, useMe, useSalesState, useSessionOrders } from "@/lib/queries";
import type { CloseResult, Customer, PosConfig, Quote, RefundRequest, SaleProduct, SaleResult, SalesState } from "@/lib/types";

interface CartItem { product_id: number; name: string; price: number; qty: number; by_weight: boolean; discount: number; tracking?: string; serials?: string[]; override?: number; has_image?: boolean }
interface Parked { cart: CartItem[]; customer: Customer | null; note: string }
type Mode = "qty" | "disc" | "price";
const PAGE = 24;
const loadPark = (key: string): Parked[] => { try { const v = JSON.parse(localStorage.getItem(key) ?? "null") as Parked[] | null; return v && v.length ? v : [{ cart: [], customer: null, note: "" }]; } catch { return [{ cart: [], customer: null, note: "" }]; } };
type Tab = "register" | "history";

function errMsg(t: ReturnType<typeof useLang>["t"], e: unknown): { text: string; ref?: string } | null {
  if (!(e instanceof ApiError)) return null;
  if (e.code === "network") return { text: t("err_network") };
  const base = errorText(t, e.code);
  return { text: ["sales_rejected", "serial_not_in_stock", "lot_stock_short"].includes(e.code) ? `${base} ${e.message}` : base, ...(e.correlationId ? { ref: e.correlationId } : {}) };
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
  const parkKey = `pos-park-${session.id}`;
  const [orders, setOrders] = useState<Parked[]>(() => loadPark(parkKey));
  const [active, setActive] = useState(0);
  const cur = orders[active] ?? orders[0]!;
  const cart = cur.cart;
  const customer = cur.customer;
  const note = cur.note;
  const patch = (p: Partial<Parked>) => setOrders((o) => o.map((x, i) => (i === active ? { ...x, ...p } : x)));
  const setCart = (f: CartItem[] | ((c: CartItem[]) => CartItem[])) => setOrders((o) => o.map((x, i) => (i === active ? { ...x, cart: typeof f === "function" ? f(x.cart) : f } : x)));
  const setCustomer = (c: Customer | null) => patch({ customer: c });
  const setNote = (n: string) => patch({ note: n });
  const [sel, setSel] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("qty");
  const [buffer, setBuffer] = useState("");
  const [category, setCategory] = useState(0);
  const [scan, setScan] = useState("");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
  const [result, setResult] = useState<SaleResult | null>(null);
  const [closing, setClosing] = useState(false);
  const [closed, setClosed] = useState<CloseResult | null>(null);
  const [pickingCustomer, setPickingCustomer] = useState(false);
  const [hi, setHi] = useState(0);
  const [help, setHelp] = useState(false);
  const [flash, setFlash] = useState<number | null>(null);
  const bindings = useBindings();
  const scanRef = useRef<HTMLInputElement>(null);
  const canDiscount = !!me.data?.permissions.includes("sales.discount");
  const canPrice = !!me.data?.permissions.includes("sales.price.override");
  useEffect(() => { try { if (orders.length === 1 && orders[0]!.cart.length === 0 && !orders[0]!.customer && !orders[0]!.note) localStorage.removeItem(parkKey); else localStorage.setItem(parkKey, JSON.stringify(orders)); } catch { /* storage unavailable */ } }, [orders, parkKey]);

  useEffect(() => { const id = setTimeout(() => setQuery(scan.trim()), 250); return () => clearTimeout(id); }, [scan]);
  useEffect(() => { if (tab === "register" && !paying && !result) scanRef.current?.focus(); }, [tab, paying, result, cart.length]);

  const isCode = /^\d{6,}$/.test(query);
  const list = useInfiniteQuery({
    queryKey: ["register-products", cid, cfg.id, category, isCode ? "" : query],
    queryFn: ({ pageParam }) => api<{ items: SaleProduct[] }>(`/connections/${cid}/sales/products?config_id=${cfg.id}&q=${encodeURIComponent(isCode ? "" : query)}&category=${category}&limit=${PAGE}&offset=${pageParam}`),
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.items.length === PAGE ? all.length * PAGE : undefined),
    enabled: !(query.length === 1),
    placeholderData: (p) => p,
  });
  const cats = useQuery({ queryKey: ["register-categories", cid, cfg.id], queryFn: () => api<{ items: { id: number; name: string; count: number }[] }>(`/connections/${cid}/sales/categories?config_id=${cfg.id}`), staleTime: 60_000 });
  const products = (list.data?.pages ?? []).flatMap((p) => p.items);
  const lines = cart.map((c) => ({ product_id: c.product_id, qty: c.qty, discount: c.discount, ...(c.override !== undefined ? { price_override: c.override } : {}) }));
  const quote = useQuery({
    queryKey: ["quote", cid, cfg.id, JSON.stringify(lines)],
    queryFn: () => api<Quote>(`/connections/${cid}/sales/quote`, { body: { config_id: cfg.id, lines } }),
    enabled: cart.length > 0, placeholderData: (p) => p, retry: false,
  });

  // everything the till sells, loaded once per shift: scans, item codes and names answer on the device
  const till = useQuery({
    queryKey: ["till-catalog", cid, cfg.id, session.id],
    queryFn: () => api<{ fields: string[]; rows: unknown[][]; truncated: boolean }>(`/connections/${cid}/sales/catalog?config_id=${cfg.id}`),
    staleTime: 5 * 60_000,
  });
  const ix = useMemo(() => (till.data ? buildIndex(till.data.fields, till.data.rows) : null), [till.data]);
  const cmd = parseCommand(scan);
  const hits = useMemo(() => {
    if (!ix || cmd.kind !== "add" || cmd.term.length < 2 || /^\d{6,}$/.test(cmd.term)) return [];
    return search(ix, cmd.term);
  }, [ix, cmd.kind, cmd.kind === "add" ? cmd.term : ""]); // eslint-disable-line react-hooks/exhaustive-deps

  const add = (p: { product_id: number; name: string; price: number; by_weight: boolean; tracking?: string; has_image?: boolean }, qty = 1) => {
    setNotice(null);
    setFlash(p.product_id); setTimeout(() => setFlash((f) => (f === p.product_id ? null : f)), 700);
    setSel(p.product_id); setBuffer(""); setMode("qty");
    setCart((c) => {
      const i = c.findIndex((x) => x.product_id === p.product_id);
      if (i >= 0) return c.map((x, j) => (j === i ? { ...x, qty: Math.round((x.qty + qty) * 1000) / 1000, ...(p.tracking === "serial" ? { serials: [...(x.serials ?? []), ""] } : {}) } : x));
      return [...c, { ...p, qty, discount: 0, ...(p.tracking === "serial" ? { serials: [""] } : {}) }];
    });
  };
  const fromItem = (it: TillItem) => ({ product_id: it.id, name: it.name, price: it.price, by_weight: it.by_weight, tracking: it.tracking });
  const ok = () => { setScan(""); setHi(0); beep(true); };
  const fail = (msg: string) => { setNotice(msg); beep(false); };
  /** The command line: scan or type, then Enter. "3*" before a scan sets the quantity; "*5" changes the
   *  selected line; "%10" discount; "@25" price; Enter on an empty line goes to payment. */
  const doScan = async (e: FormEvent) => {
    e.preventDefault();
    const c = parseCommand(scan);
    if (c.kind === "empty") { if (payable) setPaying(true); return; }
    if (c.kind !== "add") {
      if (!selected) return fail(t("pos_pick_line"));
      if (c.kind === "set_qty") { if (c.qty > 0) setQty(selected.product_id, c.qty); return ok(); }
      if (c.kind === "discount") { if (!canDiscount) return fail(t("pos_no_perm")); setCart((x) => x.map((it) => (it.product_id === selected.product_id ? { ...it, discount: Math.min(100, c.value) } : it))); return ok(); }
      if (!canPrice) return fail(t("pos_no_perm"));
      setCart((x) => x.map((it) => (it.product_id === selected.product_id ? { ...it, override: c.value } : it)));
      return ok();
    }
    const local = ix ? exact(ix, c.term) : null;
    if (local) { add(fromItem(local), c.qty ?? 1); return ok(); }
    if (hits.length && !/^\d{6,}$/.test(c.term)) { add(fromItem(hits[Math.min(hi, hits.length - 1)]!), c.qty ?? 1); return ok(); }
    if (/^[0-9A-Za-z-]{3,64}$/.test(c.term)) { // weighed-item labels, or items added after the shift opened
      const r = await api<{ found: boolean; product_id?: number; name?: string; price?: number; qty?: number; by_weight?: boolean; tracking?: string }>(
        `/connections/${cid}/sales/lookup?config_id=${cfg.id}&code=${encodeURIComponent(c.term)}`).catch(() => null);
      if (r?.found && r.product_id) { add({ product_id: r.product_id, name: r.name ?? "", price: r.price ?? 0, by_weight: !!r.by_weight, ...(r.tracking ? { tracking: r.tracking } : {}) }, c.qty ?? r.qty ?? 1); return ok(); }
    }
    fail(t("pos_not_found"));
  };
  const setQty = (id: number, qty: number) => setCart((c) => c.map((x) => {
    if (x.product_id !== id) return x;
    if (x.tracking === "serial") { const n = Math.max(1, Math.round(qty)); return { ...x, qty: n, serials: Array.from({ length: n }, (_, k) => x.serials?.[k] ?? "") }; }
    return { ...x, qty: Math.max(0.001, Math.round(qty * 1000) / 1000) };
  }));
  const remove = (id: number) => setCart((c) => c.filter((x) => x.product_id !== id));
  const newSale = () => { setResult(null); setOrders((o) => (o.length > 1 ? o.filter((_, i) => i !== active) : [{ cart: [], customer: null, note: "" }])); setActive(0); setSel(null); setScan(""); void qc.invalidateQueries({ queryKey: ["sales-orders", cid] }); void qc.invalidateQueries({ queryKey: ["sales-summary", cid] }); };
  const selected = cart.find((c) => c.product_id === sel);
  const apply = (buf: string, m: Mode, item: CartItem) => {
    const n = Number(buf === "" || buf === "." ? 0 : buf);
    if (m === "qty") { if (n > 0) setQty(item.product_id, item.tracking === "serial" ? Math.round(n) : n); }
    else if (m === "disc") setCart((c) => c.map((x) => (x.product_id === item.product_id ? { ...x, discount: Math.min(100, n) } : x)));
    else setCart((c) => c.map((x) => (x.product_id === item.product_id ? { ...x, override: buf === "" ? undefined : n } : x)));
  };
  const press = (k: string) => {
    if (!selected) return;
    let next = buffer;
    if (k === "back") next = buffer.slice(0, -1);
    else if (k === "clear") next = "";
    else if (k === "." ) next = buffer.includes(".") ? buffer : `${buffer || "0"}.`;
    else next = `${buffer}${k}`.replace(/^0+(?=\d)/, "").slice(0, 9);
    setBuffer(next);
    apply(next, mode, selected);
  };
  const pickMode = (m: Mode) => { setMode(m); setBuffer(""); };
  const pickLine = (id: number) => { setSel(id); setBuffer(""); setMode("qty"); };
  const payable = cart.length > 0 && !!quote.data && !(quote.isPlaceholderData || quote.isFetching) && !cart.some((c) => c.tracking === "serial" && (c.serials ?? []).some((v) => !v.trim()));
  const parkNew = () => { setOrders((o) => [...o, { cart: [], customer: null, note: "" }]); setActive(orders.length); setSel(null); setScan(""); };
  const closeOrder = (i: number) => { setOrders((o) => (o.length > 1 ? o.filter((_, j) => j !== i) : [{ cart: [], customer: null, note: "" }])); setActive((a) => Math.max(0, a >= i && a > 0 ? a - 1 : a)); setSel(null); };
  const keys = useRef<(e: KeyboardEvent) => void>(() => undefined);
  const handleKey = (e: KeyboardEvent) => {
    const act = actionFor(bindings, e);
    if (result) { // after a sale: start the next one, or print
      if (act === "new_sale") { e.preventDefault(); newSale(); }
      else if (act === "print") { e.preventDefault(); window.print(); }
      return;
    }
    if (tab !== "register" || closing || closed || paying || pickingCustomer) return;
    const el = document.activeElement as HTMLElement | null;
    const inCmd = el === scanRef.current;
    const otherField = !inCmd && !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT");
    const global: Partial<Record<Action, () => void>> = {
      help: () => setHelp((h) => !h), focus: () => scanRef.current?.focus(),
      customer: () => { if (cfg.payment_methods.some((m) => m.is_credit)) setPickingCustomer(true); },
      pay: () => { if (payable) setPaying(true); }, pay_alt: () => { if (payable) setPaying(true); },
      park: () => parkNew(), next_order: () => { if (orders.length > 1) { setActive((x) => (x + 1) % orders.length); setSel(null); } },
    };
    const run = act ? global[act] : undefined;
    // a plain key is a shortcut only when it cannot be typing (function keys, or with Ctrl/Alt)
    if (run && (e.key.length > 1 || e.ctrlKey || e.altKey || e.metaKey || !inCmd || scan === "")) { e.preventDefault(); run(); return; }
    if (otherField) return;
    const empty = scan === "";
    const idx = cart.findIndex((c) => c.product_id === sel);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const d = e.key === "ArrowDown" ? 1 : -1;
      if (hits.length) setHi((h) => (h + d + hits.length) % hits.length);
      else if (cart.length) pickLine(cart[(((idx < 0 ? (d > 0 ? -1 : cart.length) : idx) + d) % cart.length + cart.length) % cart.length]!.product_id);
      return;
    }
    if (empty && selected && (act === "qty_up" || act === "qty_down")) {
      e.preventDefault();
      setQty(selected.product_id, selected.qty + (act === "qty_up" ? 1 : -1) * (selected.by_weight ? 0.1 : 1));
      return;
    }
    if (empty && selected && act === "delete_line") { e.preventDefault(); remove(selected.product_id); setSel(null); return; }
    if (act === "clear") { if (help) setHelp(false); else if (scan) { setScan(""); setHi(0); } else setSel(null); return; }
    if (!inCmd && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) scanRef.current?.focus(); // type anywhere
  };
  useEffect(() => { keys.current = handleKey; }); // the listener below always sees the latest state
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => keys.current(e);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
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
        <div className="grid gap-4 lg:grid-cols-[1fr_25rem]">
          <section className="min-w-0 space-y-3">
            <form onSubmit={doScan} className="relative">
              <ScanBarcode className="pointer-events-none absolute start-4 top-1/2 size-6 -translate-y-1/2 text-brand" aria-hidden />
              <input ref={scanRef} value={scan} onChange={(e) => { setScan(e.target.value); setNotice(null); setHi(0); }} placeholder={t("pos_scan")} aria-label={t("pos_scan")} autoComplete="off" inputMode="search"
                role="combobox" aria-expanded={hits.length > 0} aria-controls="pos-hits" aria-activedescendant={hits.length ? `pos-hit-${hits[Math.min(hi, hits.length - 1)]!.id}` : undefined}
                className="min-h-14 w-full rounded-2xl border-2 border-line bg-surface ps-14 pe-24 text-lg outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
              <button type="button" onClick={() => setHelp(true)} aria-label={t("pos_keys")} title={t("pos_keys")} className="absolute end-3 top-1/2 hidden -translate-y-1/2 items-center gap-1 rounded-lg border border-line px-2 py-1 text-xs text-soft hover:text-ink md:flex"><Keyboard className="size-4" aria-hidden /> {bindings.help}</button>
              {hits.length > 0 && (
                <ul id="pos-hits" role="listbox" aria-label={t("pos_products")} className="absolute inset-x-0 top-full z-30 mt-1 max-h-96 overflow-auto rounded-2xl border border-line bg-surface p-1 shadow-card">
                  {hits.map((h, i) => (
                    <li key={h.id} id={`pos-hit-${h.id}`} role="option" aria-selected={i === Math.min(hi, hits.length - 1)}>
                      <button type="button" onMouseEnter={() => setHi(i)} onClick={() => { add(fromItem(h), cmd.kind === "add" ? cmd.qty ?? 1 : 1); ok(); scanRef.current?.focus(); }}
                        className={cn("flex min-h-12 w-full items-center justify-between gap-3 rounded-xl px-3 text-start", i === Math.min(hi, hits.length - 1) ? "bg-brandsoft" : "hover:bg-surface2")}>
                        <span className="min-w-0"><span className="block truncate font-bold" dir="auto">{h.name}</span><span className="text-xs text-soft" dir="ltr">{[h.code, h.barcode].filter(Boolean).join(" · ")}</span></span>
                        <span className="shrink-0 font-black text-brand" dir="ltr">{cmd.kind === "add" && cmd.qty ? `${cmd.qty} × ` : ""}{money(h.price, dec)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </form>
            <p className="hidden flex-wrap gap-x-4 gap-y-1 text-xs text-soft md:flex">
              <span><kbd className="font-bold text-ink">3*</kbd> {t("pos_hint_qty")}</span><span><kbd className="font-bold text-ink">Enter</kbd> {t("pos_hint_pay")}</span>
              <span><kbd className="font-bold text-ink">↑↓</kbd> {t("pos_hint_lines")}</span><span><kbd className="font-bold text-ink">+ −</kbd> {t("pos_hint_pm")}</span>
              {till.data?.truncated && <span className="text-warn">{t("pos_catalog_big")}</span>}
            </p>
            {notice && <p role="alert" className="font-bold text-bad">{notice}</p>}
            {(cats.data?.items.length ?? 0) > 1 && (
              <div role="tablist" aria-label={t("pos_categories")} className="flex gap-2 overflow-x-auto pb-1">
                {[{ id: 0, name: t("pos_all"), count: 0 }, ...(cats.data?.items ?? [])].map((c) => (
                  <button key={c.id} role="tab" aria-selected={category === c.id} onClick={() => setCategory(c.id)}
                    className={cn("min-h-11 shrink-0 rounded-2xl border-2 px-4 font-bold", category === c.id ? "border-brand bg-brandsoft text-brand" : "border-line bg-surface text-soft hover:bg-surface2")}>{c.name}</button>
                ))}
              </div>
            )}
            {list.isLoading && <Spinner label={t("loading")} />}
            {list.data && products.length === 0 && <Card className="py-10 text-center text-soft"><Search className="mx-auto mb-2 size-8" aria-hidden />{t("pos_no_products")}</Card>}
            <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4" aria-label={t("pos_products")}>
              {products.map((p) => (
                <li key={p.product_id}>
                  <button onClick={() => { add(p); setScan(""); }} className="group flex h-full min-h-28 w-full flex-col overflow-hidden rounded-2xl border border-line bg-surface text-start transition hover:border-brand active:scale-[0.98]">
                    <span className="relative grid h-20 w-full place-items-center bg-surface2">
                      {/* eslint-disable-next-line @next/next/no-img-element -- session-protected API image; next/image cannot send the cookie */}
                      {p.has_image ? <img src={`/api/connections/${cid}/sales/products/${p.product_id}/image`} alt="" loading="lazy" className="size-full object-cover" />
                        : <span className="text-3xl font-black text-soft/60" aria-hidden>{[...p.name][0]}</span>}
                      {p.on_hand !== undefined && p.on_hand !== null && <span className={cn("absolute end-1 top-1 rounded-full px-2 text-[11px] font-bold", p.on_hand <= 0 ? "bg-badsoft text-bad" : "bg-surface/90 text-soft")}>{p.on_hand}</span>}
                    </span>
                    <span className="flex flex-1 flex-col justify-between gap-1 p-2.5">
                      <span className="line-clamp-2 text-sm font-bold leading-snug" dir="auto">{p.name}</span>
                      <span className="font-black text-brand" dir="ltr">{money(p.price, dec)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {list.hasNextPage && <Button variant="ghost" loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()} className="w-full">{t("pos_more")}</Button>}
          </section>

          <aside className="space-y-3 lg:sticky lg:top-4 lg:self-start">
            <div className="flex items-center gap-1.5 overflow-x-auto" role="tablist" aria-label={t("pos_orders")}>
              {orders.map((o, i) => (
                <span key={i} className={cn("flex shrink-0 items-center rounded-xl border-2", i === active ? "border-brand bg-brandsoft" : "border-line bg-surface")}>
                  <button role="tab" aria-selected={i === active} onClick={() => { setActive(i); setSel(null); setBuffer(""); }} className="min-h-10 px-3 text-sm font-bold">{t("pos_order")} {i + 1}{o.cart.length ? ` · ${o.cart.length}` : ""}</button>
                  {orders.length > 1 && <button aria-label={t("pos_clear")} onClick={() => closeOrder(i)} className="grid size-8 place-items-center text-soft hover:text-bad"><XCircle className="size-4" aria-hidden /></button>}
                </span>
              ))}
              <button onClick={parkNew} aria-label={t("pos_new_order")} title={t("pos_new_order")} className="grid size-10 shrink-0 place-items-center rounded-xl border-2 border-dashed border-line text-soft hover:border-brand hover:text-brand"><Plus className="size-4" aria-hidden /></button>
            </div>
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
                    const on = c.product_id === sel;
                    return (
                      <li key={c.product_id} className={cn("-mx-2 space-y-2 rounded-xl px-2 py-3 transition-colors duration-500", on && "bg-brandsoft/60", flash === c.product_id && "bg-oksoft")}>
                        <div className="flex items-start justify-between gap-2">
                          <button onClick={() => pickLine(c.product_id)} className="min-w-0 flex-1 text-start" aria-pressed={on}>
                            <span className="block font-bold" dir="auto">{c.name}</span>
                            <span className="text-xs text-soft" dir="ltr">{c.qty} × {c.override !== undefined ? <><s>{money(c.price, dec)}</s> <b className="text-warn">{money(c.override, dec)}</b></> : money(c.price, dec)}{c.discount ? ` − ${c.discount}%` : ""}</span>
                          </button>
                          <span className="font-black" dir="ltr">{ql ? money(ql.subtotal_incl, dec) : "…"}</span>
                          <button aria-label="remove" onClick={() => { remove(c.product_id); if (sel === c.product_id) setSel(null); }} className="grid size-9 place-items-center rounded-xl text-bad hover:bg-badsoft"><Trash2 className="size-4" aria-hidden /></button>
                        </div>
                        {c.tracking === "serial" && (
                          <div className="space-y-1">
                            {(c.serials ?? []).map((sn, k) => (
                              <input key={k} aria-label={`${t("pos_serial_n")} ${k + 1}`} placeholder={`${t("pos_serial")} ${k + 1}`} value={sn} dir="ltr" autoComplete="off"
                                onChange={(e) => setCart(cart.map((x) => (x.product_id === c.product_id ? { ...x, serials: (x.serials ?? []).map((v, j) => (j === k ? e.target.value : v)) } : x)))}
                                className="min-h-10 w-full rounded-xl border border-line bg-surface px-3 font-mono text-sm outline-none focus:border-brand" />
                            ))}
                          </div>
                        )}
                        {c.tracking === "lot" && <p className="text-xs text-soft">{t("pos_lot_auto")}</p>}
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
            {selected && (
              <Card className="space-y-2 p-3" aria-label={t("pos_numpad")}>
                <div role="radiogroup" aria-label={t("pos_mode")} className="grid grid-cols-3 gap-1.5">
                  {([["qty", t("pos_qty")], ...(canDiscount ? [["disc", t("pos_discount")]] : []), ...(canPrice ? [["price", t("pos_price")]] : [])] as [Mode, string][]).map(([m, label]) => (
                    <button key={m} role="radio" aria-checked={mode === m} onClick={() => pickMode(m)} className={cn("min-h-10 rounded-xl border-2 text-sm font-bold", mode === m ? "border-brand bg-brandsoft text-brand" : "border-line text-soft")}>{label}</button>
                  ))}
                </div>
                <div className="grid grid-cols-3 gap-1.5" dir="ltr">
                  {["7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "back"].map((k) => (
                    <button key={k} onClick={() => press(k)} aria-label={k === "back" ? "backspace" : k} className="grid min-h-12 place-items-center rounded-xl border border-line bg-surface text-xl font-black active:bg-brandsoft">{k === "back" ? <Delete className="size-5" aria-hidden /> : k}</button>
                  ))}
                </div>
                {mode === "price" && <p className="text-xs text-warn">{t("pos_price_note")}</p>}
                <div className="flex items-center justify-between gap-2">
                  <button onClick={() => press("clear")} className="text-sm font-bold text-soft hover:text-ink">{t("pos_numpad_clear")}</button>
                  <span className="flex items-center gap-1">
                    <button aria-label="−" onClick={() => setQty(selected.product_id, selected.qty - (selected.by_weight ? 0.1 : 1))} className="grid size-10 place-items-center rounded-xl border border-line"><Minus className="size-4" aria-hidden /></button>
                    <b className="w-14 text-center" dir="ltr">{selected.qty}</b>
                    <button aria-label="+" onClick={() => setQty(selected.product_id, selected.qty + (selected.by_weight ? 0.1 : 1))} className="grid size-10 place-items-center rounded-xl border border-line"><Plus className="size-4" aria-hidden /></button>
                  </span>
                </div>
              </Card>
            )}
            {cart.length > 0 && <input aria-label={t("pos_note")} placeholder={t("pos_note")} value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} className="min-h-11 w-full rounded-2xl border border-line bg-surface px-4 text-sm outline-none focus:border-brand" />}
            <Button onClick={() => setPaying(true)} disabled={!payable} className="min-h-16 w-full text-xl"><Banknote className="size-6" aria-hidden /> {t("pos_pay")} <kbd className="hidden rounded-md border border-brandink/40 px-1.5 text-xs font-normal md:inline">{bindings.pay}</kbd></Button>
            {cart.length > 0 && <button onClick={() => { setCart([]); setSel(null); }} className="w-full text-sm font-bold text-soft hover:text-bad">{t("pos_clear")}</button>}
          </aside>
        </div>
      )}

      {paying && quote.data && (
        <PayDialog cid={cid} cfg={cfg} cart={cart} customer={customer} note={note} canOverride={!!me.data?.permissions.includes("customers.credit.override")} total={quote.data.total} currency={state.currency} dec={dec} onClose={() => setPaying(false)}
          onDone={(r) => { setPaying(false); setResult(r); }} onRefresh={() => void quote.refetch()} />
      )}
      {help && <ShortcutsHelp onClose={() => { setHelp(false); scanRef.current?.focus(); }} />}
      {pickingCustomer && <CustomerPicker cid={cid} onPick={(c) => { setCustomer(c); setPickingCustomer(false); }} onClose={() => setPickingCustomer(false)} />}
      {closing && <CloseDialog cid={cid} session={session} dec={dec} currency={state.currency} onClose={() => setClosing(false)} onDone={(r) => { setClosing(false); setClosed(r); }} />}
    </div>
  );
}

function ShortcutsHelp({ onClose }: { onClose: () => void }) {
  const { t } = useLang();
  const keys = useBindings();
  const commands: [string, string][] = [
    ["Enter", t("k_enter")], ["3* + " + t("k_scan"), t("k_qty_first")], ["*5", t("k_set_qty")],
    ["%10", t("k_disc")], ["@25", t("k_price")], ["↑ ↓", t("k_lines")],
  ];
  const row = (k: string, v: string) => <div key={k + v} className="contents"><dt><kbd className="inline-block min-w-12 rounded-lg border border-line bg-surface2 px-2 py-0.5 text-center font-mono font-bold" dir="ltr">{k}</kbd></dt><dd className="self-center">{v}</dd></div>;
  return (
    <Modal title={t("pos_keys")} onClose={onClose}>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        {commands.map(([k, v]) => row(k, v))}
        {ACTIONS.map((a) => row(keys[a.id], t(a.label)))}
      </dl>
      <p className="mt-4 text-xs text-soft">{t("k_note")}</p>
      <Link href="/settings/shortcuts" className="mt-3 inline-block text-sm font-bold text-brand">{t("ks_edit")}</Link>
    </Modal>
  );
}

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    // showModal() focuses the first button (the close X); typing should start in the first field instead
    ref.current?.querySelector<HTMLElement>("input:not([type=checkbox]):not([disabled]), textarea, select")?.focus();
  }, []);
  return (
    <dialog ref={ref} onClose={onClose} className="m-auto w-[min(94vw,30rem)] rounded-[1.5rem] border border-line bg-surface p-6 text-ink shadow-card backdrop:bg-black/50">
      <div className="mb-4 flex items-center justify-between"><h2 className="text-xl font-black">{title}</h2>
        <button aria-label="close" onClick={() => ref.current?.close()} className="grid size-10 place-items-center rounded-xl hover:bg-surface2"><XCircle className="size-5 text-soft" aria-hidden /></button></div>
      {children}
    </dialog>
  );
}

function PayDialog({ cid, cfg, cart, customer, note, canOverride, total, currency, dec, onClose, onDone, onRefresh }: { cid: string; cfg: PosConfig; cart: CartItem[]; customer: Customer | null; note: string; canOverride: boolean; total: number; currency: string; dec: number; onClose: () => void; onDone: (r: SaleResult) => void; onRefresh: () => void }) {
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
  const payload = { config_id: cfg.id, lines: cart.map((c) => ({ product_id: c.product_id, qty: c.qty, discount: c.discount, ...(c.override !== undefined ? { price_override: c.override } : {}), ...(c.tracking === "serial" ? { serials: (c.serials ?? []).map((v) => v.trim()) } : {}) })), expected_total: total, payments, ...(note.trim() ? { note: note.trim() } : {}), ...(customer ? { partner_id: customer.id } : {}), ...(override ? { override_credit_limit: true } : {}) };
  const m = useMutation({
    mutationFn: (body: typeof payload) => api<SaleResult>(`/connections/${cid}/sales/orders`, { body, headers: { "Idempotency-Key": keyFor(body) } }),
    onSuccess: onDone,
    onError: (e) => { if (e instanceof ApiError && e.code === "price_changed") onRefresh(); },
  });
  const e = errMsg(t, m.error);
  const limitHit = m.error instanceof ApiError && m.error.code === "credit_limit_exceeded";
  /** Keyboard: Enter confirms; Enter with nothing typed pays the exact amount (the common cash case). */
  const onKeys = (ev: ReactKeyboardEvent) => {
    if (ev.key !== "Enter" || m.isPending) return;
    ev.preventDefault();
    if (ok) return m.mutate(payload);
    if (isCash && tendered === "" && due > 0 && creditOk && method > 0) {
      const exactPay = { ...payload, payments: [{ payment_method_id: method, amount: due }, ...payments.slice(1)] };
      setTendered(String(due));
      m.mutate(exactPay);
    }
  };
  return (
    <Modal title={t("pay_title")} onClose={onClose}>
      <div className="space-y-4" onKeyDown={onKeys}>
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
              <button type="button" onClick={() => setTendered(String(due))} className="min-h-11 rounded-2xl bg-brandsoft px-4 font-bold text-brand">{t("pay_exact")}</button>
              {quick.map((q) => <button key={q} onClick={() => setTendered(String(q))} className="min-h-11 rounded-2xl bg-surface2 px-4 font-bold" dir="ltr">{q}</button>)}
            </div>
            <p className={cn("flex items-baseline justify-between text-xl font-black", ok ? "text-ok" : "text-soft")}><span>{ok ? t("pay_change") : t("pay_short")}</span>{ok && <span dir="ltr">{money(change, dec)}</span>}</p>
          </>
        )}
        {e && <ErrorBox message={e.text} reference={e.ref} />}
        {limitHit && canOverride && (
          <label className="flex items-start gap-3 rounded-2xl bg-warnsoft p-3 text-sm font-bold text-warn"><input type="checkbox" checked={override} onChange={(ev) => setOverride(ev.target.checked)} className="mt-0.5 size-5" /><span>{t("pos_override")}<span className="block text-xs font-normal">{t("pos_override_hint")}</span></span></label>
        )}
        <Button onClick={() => m.mutate(payload)} disabled={!ok} loading={m.isPending} className="min-h-14 w-full text-lg">{t("pay_confirm")} <kbd className="hidden rounded-md border border-brandink/40 px-1.5 text-xs font-normal md:inline">Enter</kbd></Button>
        {isCash && due > 0 && <p className="hidden text-center text-xs text-soft md:block">{t("pay_enter_exact")}</p>}
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

function RefundRequests({ cid, canDecide }: { cid: string; canDecide: boolean }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["refund-requests", cid], queryFn: () => api<{ items: RefundRequest[] }>(`/connections/${cid}/sales/refund-requests`), refetchInterval: 15_000 });
  const act = useMutation({
    mutationFn: ({ id, ok }: { id: string; ok: boolean }) => api(`/connections/${cid}/sales/refund-requests/${id}/${ok ? "approve" : "reject"}`, { method: "POST", body: ok ? undefined : { note: "" } }),
    onSettled: () => { void qc.invalidateQueries({ queryKey: ["refund-requests", cid] }); void qc.invalidateQueries({ queryKey: ["sales-orders", cid] }); void qc.invalidateQueries({ queryKey: ["alerts"] }); },
  });
  const e = errMsg(t, act.error);
  const items = (list.data?.items ?? []).filter((r) => r.status === "awaiting_approval" || !canDecide);
  if (!items.length) return null;
  return (
    <Card className="space-y-2">
      <h2 className="text-lg font-black">{t("rr_title")}</h2>
      {e && <ErrorBox message={e.text} reference={e.ref} />}
      <ul className="divide-y divide-line">
        {items.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
            <div><p className="font-bold" dir="ltr">{r.order} · {money(r.amount ?? 0)}{r.partial ? ` · ${t("rr_partial")}` : ""}</p><p className="text-xs text-soft" dir="auto">{r.requested_by}</p></div>
            {canDecide && r.status === "awaiting_approval" ? (
              <div className="flex gap-2"><Button className="min-h-10 px-3" loading={act.isPending} onClick={() => act.mutate({ id: r.id, ok: true })}>{t("rr_approve")}</Button>
                <Button variant="ghost" className="min-h-10 px-3" onClick={() => act.mutate({ id: r.id, ok: false })}>{t("rr_reject")}</Button></div>
            ) : <Badge tone={r.status === "succeeded" ? "ok" : r.status === "rejected" ? "bad" : "warn"}>{t(r.status === "succeeded" ? "rr_done" : r.status === "rejected" ? "rr_rejected" : "rr_waiting")}</Badge>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function History_({ cid, sessionId, cashId, currency, dec, canRefund }: { cid: string; sessionId: number; cashId?: number | undefined; currency: string; dec: number; canRefund: boolean }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const orders = useSessionOrders(cid, sessionId);
  const keyFor = useIdempotencyKey();
  const [target, setTarget] = useState<number | null>(null);
  const [picked, setPicked] = useState<Record<number, number>>({});
  const m = useMutation({
    mutationFn: (id: number) => {
      const lines = Object.entries(picked).filter(([, q]) => q > 0).map(([line_id, qty]) => ({ line_id: Number(line_id), qty }));
      const payload = { payment_method_id: cashId, lines };
      return api(`/connections/${cid}/sales/orders/${id}/${canRefund ? "refund" : "refund-request"}`, { body: payload, headers: { "Idempotency-Key": keyFor({ id, ...payload }) } });
    },
    onSuccess: () => { setTarget(null); setPicked({}); setSent(!canRefund); void qc.invalidateQueries({ queryKey: ["sales-orders", cid] }); void qc.invalidateQueries({ queryKey: ["refund-requests", cid] }); },
  });
  const [sent, setSent] = useState(false);
  const e = errMsg(t, m.error);
  if (orders.isLoading) return <Spinner label={t("loading")} />;
  if (!orders.data?.items.length) return <Card className="py-10 text-center text-soft">{t("hist_none")}</Card>;
  return (
    <div className="space-y-3">
      <RefundRequests cid={cid} canDecide={canRefund} />
      {sent && <div role="status"><Card className="border-ok/30 bg-oksoft font-bold text-ok">{t("rr_sent")}</Card></div>}
      <h2 className="text-lg font-black">{t("hist_title")}</h2>
      {e && <ErrorBox message={e.text} reference={e.ref} />}
      <ul className="space-y-2">
        {orders.data.items.map((o) => (
          <li key={o.id}><Card className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div><p className="font-bold" dir="ltr">{o.name}</p><p className="text-xs text-soft" dir="ltr">{o.date_order} · {o.lines.length} {t("hist_items")}</p></div>
            <div className="flex items-center gap-3">
              <span className={cn("text-lg font-black", o.amount_total < 0 && "text-bad")} dir="ltr">{money(o.amount_total, dec)} {currency}</span>
              {o.amount_total < 0 ? <Badge tone="warn">{t("refunded")}</Badge> : cashId && !o.lines.every((l) => (l.refunded_qty ?? 0) >= l.qty) && (
                target !== o.id && <button onClick={() => { setTarget(o.id); setPicked({}); }} className="inline-flex min-h-10 items-center gap-1 rounded-xl border border-line px-3 text-sm font-bold hover:bg-surface2"><Undo2 className="size-4" aria-hidden />{t(canRefund ? "refund" : "rr_ask")}</button>
              )}
            </div>
            {target === o.id && (
              <div className="w-full space-y-2 border-t border-line pt-3">
                <p className="text-sm font-bold">{t("refund_pick")}</p>
                {o.lines.filter((l) => l.id && l.qty > 0).map((l) => {
                  const left = l.qty - (l.refunded_qty ?? 0);
                  if (left <= 0) return null;
                  const v = picked[l.id as number] ?? 0;
                  return (
                    <div key={l.id} className="flex items-center justify-between gap-2">
                      <span dir="auto">{l.name} <span className="text-xs text-soft">({t("refund_left")}: {left})</span></span>
                      <span className="flex items-center gap-1">
                        <button aria-label="-" onClick={() => setPicked({ ...picked, [l.id as number]: Math.max(0, v - 1) })} className="size-10 rounded-xl border border-line font-black">−</button>
                        <span className="w-10 text-center font-black" dir="ltr">{v}</span>
                        <button aria-label="+" onClick={() => setPicked({ ...picked, [l.id as number]: Math.min(left, v + 1) })} className="size-10 rounded-xl border border-line font-black">+</button>
                      </span>
                    </div>
                  );
                })}
                <p className="text-xs text-soft">{t("refund_method_note")} {Object.values(picked).every((q) => !q) ? t("refund_all_note") : ""}</p>
                <div className="flex gap-2">
                  <Button variant="danger" loading={m.isPending} onClick={() => m.mutate(o.id)} className="min-h-10 px-3">{t(canRefund ? "refund" : "rr_ask")}</Button>
                  <button onClick={() => { setTarget(null); setPicked({}); }} className="text-sm font-bold text-soft">{t("cancel")}</button>
                </div>
              </div>
            )}
          </Card></li>
        ))}
      </ul>
    </div>
  );
}
