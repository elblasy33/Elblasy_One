"use client";
import { Boxes, LayoutDashboard, Languages, LogOut, Settings, ShoppingCart, Store, Wallet } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useLang, type TKey } from "@/lib/i18n";
import type { Me } from "@/lib/types";

interface Item { href: string; label: TKey; icon: typeof Store; any: string[] }
const ITEMS: Item[] = [
  { href: "/today", label: "nav_today", icon: LayoutDashboard, any: [] },
  { href: "/sales", label: "nav_sales", icon: ShoppingCart, any: ["sales.create"] },
  { href: "/inventory", label: "nav_inventory", icon: Boxes, any: ["inventory.adjust", "reports.view"] },
  { href: "/money", label: "nav_money", icon: Wallet, any: ["payments.create", "expenses.create", "reports.view"] },
  { href: "/settings", label: "nav_settings", icon: Settings, any: ["config.manage", "connections.manage", "users.manage"] },
];

export function Shell({ me, children }: { me: Me; children: ReactNode }) {
  const { t, lang, setLang } = useLang();
  const path = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  // Navigation mirrors server-side permissions; the API enforces them regardless.
  const items = ITEMS.filter((i) => i.any.length === 0 || i.any.some((p) => me.permissions.includes(p)));
  const logout = async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    qc.clear();
    router.replace("/login");
  };
  return (
    <div className="min-h-dvh md:flex">
      <aside className="hidden w-64 shrink-0 flex-col gap-2 border-e border-line bg-surface p-4 md:flex">
        <div className="mb-4 flex items-center gap-3 px-2">
          <div className="grid size-11 place-items-center rounded-2xl bg-brand text-brandink"><Store className="size-6" aria-hidden /></div>
          <span className="text-xl font-black">{t("app")}</span>
        </div>
        <nav aria-label={t("nav_menu")} className="flex flex-1 flex-col gap-1">
          {items.map((i) => {
            const active = path === i.href || path.startsWith(`${i.href}/`);
            return (
              <Link key={i.href} href={i.href} aria-current={active ? "page" : undefined}
                className={cn("flex min-h-12 items-center gap-3 rounded-2xl px-4 font-bold transition", active ? "bg-brandsoft text-brand" : "text-soft hover:bg-surface2 hover:text-ink")}>
                <i.icon className="size-5" aria-hidden /> {t(i.label)}
              </Link>
            );
          })}
        </nav>
        <div className="space-y-1 border-t border-line pt-3">
          <p className="truncate px-2 text-xs text-soft" dir="ltr">{me.email}</p>
          <button onClick={() => setLang(lang === "ar" ? "en" : "ar")} className="flex min-h-11 w-full items-center gap-3 rounded-2xl px-4 text-sm font-bold text-soft hover:bg-surface2">
            <Languages className="size-4" aria-hidden /> {t("lang_switch")}
          </button>
          <button onClick={logout} className="flex min-h-11 w-full items-center gap-3 rounded-2xl px-4 text-sm font-bold text-soft hover:bg-surface2">
            <LogOut className="size-4" aria-hidden /> {t("logout")}
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 pb-28 pt-6 md:px-10 md:pb-10">
        <div className="mx-auto w-full max-w-4xl">{children}</div>
      </main>
      <nav aria-label={t("nav_menu")} className="fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-surface/95 px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        {items.map((i) => {
          const active = path === i.href || path.startsWith(`${i.href}/`);
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
