"use client";
import { Boxes, ChevronsLeft, ChevronsRight, ClipboardList, FileText, LayoutDashboard, Languages, Lock, LogOut, Settings, ShoppingCart, Store, Wallet } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore, type ReactNode } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useLang, type TKey } from "@/lib/i18n";
import { useActiveConnection } from "@/lib/queries";
import type { Me } from "@/lib/types";

interface Item { href: string; label: TKey; icon: typeof Store; any: string[]; cap?: string; match?: string[]; not?: string[] }
const ITEMS: Item[] = [
  { href: "/today", label: "nav_today", icon: LayoutDashboard, any: [] },
  { href: "/sales", label: "nav_sales", icon: ShoppingCart, any: ["sales.create"], cap: "pos" },
  { href: "/sales-orders", label: "nav_sorders", icon: FileText, any: ["sales.orders"], cap: "sales" },
  { href: "/inventory", label: "nav_inventory", icon: Boxes, any: ["inventory.adjust", "products.manage", "reports.view"], cap: "inventory", not: ["/inventory/purchases", "/inventory/suppliers"] },
  { href: "/inventory/purchases", label: "nav_purchases", icon: ClipboardList, any: ["purchasing.view"], cap: "purchase", match: ["/inventory/purchases", "/inventory/suppliers"] },
  { href: "/money", label: "nav_money", icon: Wallet, any: ["payments.create", "expenses.create", "reports.view"], cap: "accounting" },
  { href: "/settings", label: "nav_settings", icon: Settings, any: ["config.manage", "connections.manage", "users.manage"] },
];

const SLIM_KEY = "nav-slim";
const subscribeSlim = (cb: () => void) => { window.addEventListener(SLIM_KEY, cb); window.addEventListener("storage", cb); return () => { window.removeEventListener(SLIM_KEY, cb); window.removeEventListener("storage", cb); }; };
const readSlim = () => { try { return localStorage.getItem(SLIM_KEY) === "1"; } catch { return false; } };

export function Shell({ me, children }: { me: Me; children: ReactNode }) {
  const { t, lang, setLang } = useLang();
  const path = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  // Navigation mirrors server-side permissions; the API enforces them regardless.
  const caps = useActiveConnection().data?.capabilities;
  const off = (i: Item) => !!i.cap && caps?.[i.cap] === false;
  const isAdmin = me.permissions.includes("config.manage");
  const items = ITEMS.filter((i) => (i.any.length === 0 || i.any.some((p) => me.permissions.includes(p))) && (!off(i) || isAdmin));
  const isActive = (i: Item) => {
    if (i.not?.some((n) => path === n || path.startsWith(`${n}/`))) return false;
    return (i.match ?? [i.href]).some((m) => path === m || path.startsWith(`${m}/`));
  };
  const slim = useSyncExternalStore(subscribeSlim, readSlim, () => false);
  const toggle = () => { try { localStorage.setItem(SLIM_KEY, slim ? "0" : "1"); } catch { /* storage unavailable */ } window.dispatchEvent(new Event(SLIM_KEY)); };
  const Fold = (lang === "ar") !== slim ? ChevronsLeft : ChevronsRight;
  const logout = async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    qc.clear();
    router.replace("/login");
  };
  return (
    <div className="min-h-dvh md:flex">
      <aside className={cn("hidden shrink-0 flex-col gap-2 overflow-hidden border-e border-line bg-surface p-4 transition-[width] duration-300 ease-out md:flex", slim ? "w-[5.5rem]" : "w-64")}>
        <div className="mb-4 flex items-center gap-3 px-1">
          <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-brand text-brandink"><Store className="size-6" aria-hidden /></div>
          {!slim && <span className="flex-1 truncate text-xl font-black">{t("app")}</span>}
        </div>
        <button onClick={toggle} aria-label={t(slim ? "nav_expand" : "nav_collapse")} title={t(slim ? "nav_expand" : "nav_collapse")} aria-expanded={!slim}
          className="mb-1 grid min-h-10 place-items-center rounded-xl text-soft hover:bg-surface2 hover:text-ink"><Fold className="size-5" aria-hidden /></button>
        <nav aria-label={t("nav_menu")} className="flex flex-1 flex-col gap-1">
          {items.map((i) => {
            const active = isActive(i);
            return (
              <Link key={i.href} href={i.href} aria-current={active ? "page" : undefined} title={slim ? t(i.label) : undefined} aria-label={slim ? t(i.label) : undefined}
                className={cn("flex min-h-12 items-center gap-3 rounded-2xl px-4 font-bold transition", slim && "justify-center px-0", active ? "bg-brandsoft text-brand" : "text-soft hover:bg-surface2 hover:text-ink")}>
                <i.icon className="size-5 shrink-0" aria-hidden />{!slim && <span className="truncate">{t(i.label)}</span>}{!slim && off(i) && <Lock className="ms-auto size-4" aria-hidden />}
              </Link>
            );
          })}
        </nav>
        <div className="space-y-1 border-t border-line pt-3">
          {!slim && <p className="truncate px-2 text-xs text-soft" dir="ltr">{me.email}</p>}
          <button onClick={() => setLang(lang === "ar" ? "en" : "ar")} title={t("lang_switch")} aria-label={t("lang_switch")} className={cn("flex min-h-11 w-full items-center gap-3 rounded-2xl px-4 text-sm font-bold text-soft hover:bg-surface2", slim && "justify-center px-0")}>
            <Languages className="size-4 shrink-0" aria-hidden />{!slim && t("lang_switch")}
          </button>
          <button onClick={logout} title={t("logout")} aria-label={t("logout")} className={cn("flex min-h-11 w-full items-center gap-3 rounded-2xl px-4 text-sm font-bold text-soft hover:bg-surface2", slim && "justify-center px-0")}>
            <LogOut className="size-4 shrink-0" aria-hidden />{!slim && t("logout")}
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 pb-28 pt-6 md:px-10 md:pb-10">
        <div className={cn("mx-auto w-full transition-[max-width] duration-300", slim ? "max-w-6xl" : "max-w-4xl")}>{children}</div>
      </main>
      <nav aria-label={t("nav_menu")} className="fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-surface/95 px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        {items.map((i) => {
          const active = isActive(i);
          return (
            <Link key={i.href} href={i.href} aria-current={active ? "page" : undefined}
              className={cn("flex min-h-16 flex-1 flex-col items-center justify-center gap-1 text-[11px] font-bold", active ? "text-brand" : "text-soft")}>
              <i.icon className="size-6" aria-hidden />
              <span className="max-w-full truncate px-1">{t(i.label)}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
