"use client";
import { Boxes, Truck, ClipboardList } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { useLang, type TKey } from "@/lib/i18n";
import { useMe } from "@/lib/queries";

const TABS: { href: string; label: TKey; icon: typeof Boxes; perm: string; exact?: boolean }[] = [
  { href: "/inventory", label: "tab_products", icon: Boxes, perm: "products.manage", exact: true },
  { href: "/inventory/suppliers", label: "tab_suppliers", icon: Truck, perm: "purchasing.view" },
  { href: "/inventory/purchases", label: "tab_purchases", icon: ClipboardList, perm: "purchasing.view" },
];

export function InventoryTabs() {
  const { t } = useLang();
  const path = usePathname();
  const me = useMe();
  const tabs = TABS.filter((x) => me.data?.permissions.includes(x.perm));
  return (
    <nav aria-label="inventory sections" className="flex flex-wrap gap-2">
      {tabs.map((x) => {
        const active = x.exact ? path === x.href || path.startsWith("/inventory/new") || path.startsWith("/inventory/import") || path.startsWith("/inventory/recipe") : path.startsWith(x.href);
        return (
          <Link key={x.href} href={x.href} aria-current={active ? "page" : undefined}
            className={cn("inline-flex min-h-11 items-center gap-2 rounded-2xl px-4 font-bold", active ? "bg-brand text-brandink" : "bg-surface2 text-soft hover:text-ink")}>
            <x.icon className="size-4" aria-hidden /> {t(x.label)}
          </Link>
        );
      })}
    </nav>
  );
}
