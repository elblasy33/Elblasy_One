"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogOut, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button, Card, ErrorBox, Field } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useHydrated } from "@/lib/hydrated";
import { errorText, useLang } from "@/lib/i18n";
import { useMe } from "@/lib/queries";

export default function AccountPage() {
  const { t } = useLang();
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const router = useRouter();
  const me = useMe();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const change = useMutation({
    mutationFn: () => api("/auth/change-password", { body: { current_password: cur, new_password: pw } }),
    onSuccess: async () => { setCur(""); setPw(""); await qc.invalidateQueries({ queryKey: ["me"] }); },
  });
  const out = useMutation({ mutationFn: () => api("/auth/logout-everywhere", { method: "POST" }), onSuccess: () => { qc.clear(); router.replace("/login"); } });
  const err = change.error instanceof ApiError ? change.error : null;
  return (
    <div className="rise mx-auto max-w-xl space-y-5">
      <h1 className="text-3xl font-black">{t("ac_title")}</h1>
      <p className="text-soft" dir="ltr">{me.data?.email}</p>
      {me.data?.must_change_password && <Card className="border-warn/40 bg-warnsoft font-bold text-warn">{t("ac_force")}</Card>}
      <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); change.mutate(); }}>
        <Card className="space-y-4">
          <Field label={t("ac_current")} name="current" type="password" required autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} dir="ltr" />
          <Field label={t("ac_new")} name="new" type="password" required minLength={12} autoComplete="new-password" hint={t("password_hint")} value={pw} onChange={(e) => setPw(e.target.value)} dir="ltr" />
          {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
          {change.isSuccess && <p role="status" className="flex items-center gap-2 font-bold text-ok"><ShieldCheck className="size-5" aria-hidden /> {t("ac_changed")}</p>}
          <Button type="submit" disabled={!hydrated} loading={change.isPending} className="w-full">{t("ac_change")}</Button>
        </Card>
      </form>
      <Card className="space-y-2">
        <p className="text-sm text-soft">{t("ac_logout_all_hint")}</p>
        <Button variant="ghost" onClick={() => out.mutate()} loading={out.isPending} className="w-full"><LogOut className="size-4" aria-hidden /> {t("ac_logout_all")}</Button>
      </Card>
    </div>
  );
}
