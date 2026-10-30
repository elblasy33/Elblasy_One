"use client";
import { Boxes, ClipboardList, Factory, Package, Tags, Truck } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { useLang, type TKey } from "@/lib/i18n";
import { useActiveConnection, useMe, useShopFeatures } from "@/lib/queries";

const TABS: { href: string; label: TKey; icon: typeof Boxes; perm: string[]; exact?: boolean; cap?: string; feature?: string }[] = [
  { href: "/inventory", label: "tab_products", icon: Boxes, perm: ["products.manage"], exact: true },
  { href: "/inventory/stock", label: "tab_stock", icon: Package, perm: ["inventory.adjust", "purchasing.view", "products.manage"] },
  { href: "/inventory/production", label: "tab_production", icon: Factory, perm: ["products.manage"], cap: "manufacturing" },
  { href: "/inventory/pricelists", label: "pl_title", icon: Tags, perm: ["products.view"], feature: "pricelists" },
  { href: "/inventory/suppliers", label: "tab_suppliers", icon: Truck, perm: ["purchasing.view"], cap: "purchase" },
  { href: "/inventory/purchases", label: "tab_purchases", icon: ClipboardList, perm: ["purchasing.view"], cap: "purchase" },
];

export function InventoryTabs() {
  const { t } = useLang();
  const path = usePathname();
  const me = useMe();
  const conn = useActiveConnection().data;
  const caps = conn?.capabilities;
  const { features } = useShopFeatures(conn?.id);
  const tabs = TABS.filter((x) => x.perm.some((p) => me.data?.permissions.includes(p)) && !(x.cap && caps?.[x.cap] === false) && (!x.feature || features.has(x.feature)));
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
