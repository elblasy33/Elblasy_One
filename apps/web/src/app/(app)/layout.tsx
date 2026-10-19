"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Shell } from "@/components/shell";
import { Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { useMe } from "@/lib/queries";

export default function AppLayout({ children }: { children: ReactNode }) {
  const me = useMe();
  const router = useRouter();
  const path = usePathname();
  const { t } = useLang();
  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace("/login");
  }, [me.error, router]);
  useEffect(() => {
    if (me.data?.must_change_password && path !== "/settings/account") router.replace("/settings/account");
  }, [me.data?.must_change_password, path, router]);
  if (!me.data) return <Spinner label={t("loading")} />;
  return <Shell me={me.data}>{children}</Shell>;
}
