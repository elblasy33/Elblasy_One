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

export default function SignupPage() {
  const { t } = useLang();
  const hydrated = useHydrated();
  const router = useRouter();
  const [business, setBusiness] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const m = useMutation({
    mutationFn: () => api("/auth/bootstrap", { body: { business_name: business, email, password } }),
    onSuccess: () => router.replace("/today"),
  });
  const err = m.error instanceof ApiError ? m.error : null;
  return (
    <AuthShell title={t("signup")}>
      <form method="post" action="#" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate(); }}>
        <Field label={t("business_name")} name="business" required value={business} onChange={(e) => setBusiness(e.target.value)} />
        <Field label={t("email")} name="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} dir="ltr" />
        <Field label={t("password")} name="password" type="password" autoComplete="new-password" required minLength={12} hint={t("password_hint")} value={password} onChange={(e) => setPassword(e.target.value)} dir="ltr" />
        {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
        <Button type="submit" disabled={!hydrated} loading={m.isPending} className="w-full">{t("signup")}</Button>
      </form>
      <p className="mt-5 text-center text-sm text-soft">
        {t("have_account")} <Link className="font-bold text-brand" href="/login">{t("login")}</Link>
      </p>
    </AuthShell>
  );
}
