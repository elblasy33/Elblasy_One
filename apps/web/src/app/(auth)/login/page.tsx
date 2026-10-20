"use client";
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { AuthShell } from "@/components/auth-shell";
import { Button, ErrorBox, Field } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useHydrated } from "@/lib/hydrated";
import { errorText, useLang } from "@/lib/i18n";

export default function LoginPage() {
  const { t } = useLang();
  const hydrated = useHydrated();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const m = useMutation({
    mutationFn: () => api("/auth/login", { body: { email, password } }),
    onSuccess: () => router.replace("/today"),
  });
  const err = m.error instanceof ApiError ? m.error : null;
  return (
    <AuthShell title={t("login")}>
      <form method="post" action="#" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate(); }}>
        <Field label={t("email")} name="email" type="text" inputMode="email" autoCapitalize="none" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} dir="ltr" />
        <Field label={t("password")} name="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} dir="ltr" />
        {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
        <Button type="submit" disabled={!hydrated} loading={m.isPending} className="w-full">{t("login")}</Button>
      </form>
      <p className="mt-5 text-center text-sm text-soft">
        {t("no_account")} <Link className="font-bold text-brand" href="/signup">{t("signup")}</Link>
      </p>
    </AuthShell>
  );
}
