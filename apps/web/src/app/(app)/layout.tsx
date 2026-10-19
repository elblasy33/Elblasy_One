"use client";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Shell } from "@/components/shell";
import { Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { useMe } from "@/lib/queries";

export default function AppLayout({ children }: { children: ReactNode }) {
  const me = useMe();
  const router = useRouter();
  const { t } = useLang();
  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace("/login");
  }, [me.error, router]);
  if (!me.data) return <Spinner label={t("loading")} />;
  return <Shell me={me.data}>{children}</Shell>;
}
