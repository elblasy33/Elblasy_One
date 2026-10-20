"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button, Card, ErrorBox, Field } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useHydrated } from "@/lib/hydrated";
import { cn } from "@/lib/cn";
import { errorText, useLang } from "@/lib/i18n";
import type { Connection } from "@/lib/types";

export default function ConnectPage() {
  const { t } = useLang();
  const hydrated = useHydrated();
  const router = useRouter();
  const qc = useQueryClient();
  const [mode, setMode] = useState<"new" | "existing">("new");
  const [f, setF] = useState({ name: "", base_url: "", db_name: "", login: "", secret: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const m = useMutation({
    mutationFn: () => api<Connection>("/connections", { body: { ...f, name: f.name || "Odoo", mode } }),
    onSuccess: (created) => {
      // Put the new connection in the cache first so the next screen never sees a stale empty list.
      qc.setQueryData<Connection[]>(["connections"], (old) => [...(old ?? []), created]);
      void qc.invalidateQueries({ queryKey: ["connections"] });
      router.replace(mode === "existing" ? "/settings/readiness" : "/settings/setup");
    },
  });
  const err = m.error instanceof ApiError ? m.error : null;
  return (
    <div className="rise mx-auto max-w-xl space-y-5">
      <header>
        <h1 className="text-3xl font-black">{t("connect_title")}</h1>
        <p className="mt-1 text-soft">{t("connect_sub")}</p>
      </header>
      <div role="radiogroup" aria-label={t("mode_title")} className="grid gap-3 sm:grid-cols-2">
        {(["new", "existing"] as const).map((k) => (
          <button key={k} type="button" role="radio" aria-checked={mode === k} onClick={() => setMode(k)} className={cn("rounded-2xl border-2 p-4 text-start transition", mode === k ? "border-brand bg-brandsoft" : "border-line bg-surface")}>
            <span className="block font-black">{t(k === "new" ? "mode_new" : "mode_existing")}</span>
            <span className="mt-1 block text-sm text-soft">{t(k === "new" ? "mode_new_sub" : "mode_existing_sub")}</span>
          </button>
        ))}
      </div>
      <Card>
        <form method="post" action="#" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); m.mutate(); }}>
          <Field label={t("conn_name")} name="name" value={f.name} onChange={set("name")} placeholder="Odoo" />
          <Field label={t("conn_url")} name="base_url" required value={f.base_url} onChange={set("base_url")} placeholder="https://erp.example.com" dir="ltr" inputMode="url" />
          <Field label={t("conn_db")} name="db_name" required value={f.db_name} onChange={set("db_name")} dir="ltr" />
          <Field label={t("conn_login")} name="login" required value={f.login} onChange={set("login")} dir="ltr" autoComplete="off" />
          <Field label={t("conn_secret")} name="secret" type="password" required value={f.secret} onChange={set("secret")} hint={t("conn_secret_hint")} dir="ltr" autoComplete="off" />
          {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
          <Button type="submit" disabled={!hydrated} loading={m.isPending} className="w-full">{m.isPending ? t("connecting") : t("connect_btn")}</Button>
        </form>
      </Card>
    </div>
  );
}
