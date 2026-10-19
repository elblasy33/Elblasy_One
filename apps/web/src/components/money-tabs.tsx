"use client";
import { Landmark, Receipt, Tags, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { useLang, type TKey } from "@/lib/i18n";
import { useMe } from "@/lib/queries";

const TABS: { href: string; label: TKey; icon: typeof Landmark; perm: string[]; exact?: boolean }[] = [
  { href: "/money", label: "mn_title", icon: Landmark, perm: ["reports.view", "payments.create"], exact: true },
  { href: "/money/expenses", label: "ex_title", icon: Receipt, perm: ["expenses.create", "reports.view", "payments.create"] },
  { href: "/money/receivables", label: "cu_title", icon: Users, perm: ["payments.create", "reports.view"] },
  { href: "/money/categories", label: "ex_cats", icon: Tags, perm: ["config.manage"] },
];

export function MoneyTabs() {
  const { t } = useLang();
  const path = usePathname();
  const me = useMe();
  return (
    <nav aria-label="money sections" className="flex flex-wrap gap-2">
      {TABS.filter((x) => x.perm.some((p) => me.data?.permissions.includes(p))).map((x) => {
        const active = x.exact ? path === x.href : path.startsWith(x.href);
        return (
          <Link key={x.href} href={x.href} aria-current={active ? "page" : undefined} className={cn("inline-flex min-h-11 items-center gap-2 rounded-2xl px-4 font-bold", active ? "bg-brand text-brandink" : "bg-surface2 text-soft hover:text-ink")}>
            <x.icon className="size-4" aria-hidden /> {t(x.label)}
          </Link>
        );
      })}
    </nav>
  );
}
