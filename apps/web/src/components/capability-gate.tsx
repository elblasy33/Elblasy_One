"use client";
import { PlugZap } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Card } from "@/components/ui";
import { useLang } from "@/lib/i18n";
import { useActiveConnection, useMe } from "@/lib/queries";

/** The UI follows what this Odoo can actually do. An unavailable capability is explained, never hidden
 *  silently and never installed automatically: the owner can enable it through the reviewed setup plan. */
export function CapabilityGate({ cap, children }: { cap: string; children: ReactNode }) {
  const { t } = useLang();
  const conn = useActiveConnection();
  const me = useMe();
  if (conn.data?.capabilities && conn.data.capabilities[cap] === false)
    return (
      <Card className="rise mx-auto max-w-md space-y-3 py-12 text-center">
        <PlugZap className="mx-auto size-10 text-soft" aria-hidden />
        <p className="text-xl font-black">{t("cap_off_title")}</p>
        <p className="text-soft">{t("cap_off_sub")}</p>
        {me.data?.permissions.includes("config.manage") && <Link href="/settings/setup" className="font-bold text-brand">{t("cap_off_go")}</Link>}
      </Card>
    );
  return <>{children}</>;
}
