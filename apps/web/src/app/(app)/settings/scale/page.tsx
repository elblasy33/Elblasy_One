"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Scale, ScanBarcode } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Badge, Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useMe } from "@/lib/queries";

interface Fmt { prefix: string; plu_digits: number; int_digits: number; dec_digits: number }
interface Rule { id: number; name: string; type: "weight" | "price"; pattern: string; sequence: number; managed: boolean; format: Fmt | null }

/** Coloured picture of a label: prefix | item number | value (integer . decimals) | check digit. */
function Layout({ f, kind }: { f: Fmt; kind: string }) {
  const { t } = useLang();
  const box = (n: number, cls: string, ch: string) => Array.from({ length: n }, (_, i) => <span key={cls + i} className={cn("grid h-8 w-6 place-items-center rounded font-mono text-sm font-black", cls)}>{ch}</span>);
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-0.5" dir="ltr">
        {[...f.prefix].map((d, i) => <span key={`p${i}`} className="grid h-8 w-6 place-items-center rounded bg-ink font-mono text-sm font-black text-surface">{d}</span>)}
        {box(f.plu_digits, "bg-brandsoft text-brand", "P")}
        {box(f.int_digits, "bg-oksoft text-ok", "N")}
        {box(f.dec_digits, "bg-warnsoft text-warn", "D")}
        {box(1, "bg-surface2 text-soft", "✓")}
      </div>
      <p className="text-xs text-soft">{t("sc_legend")} {kind === "price" ? t("sc_value_price") : t("sc_value_weight")}</p>
    </div>
  );
}

export default function ScalePage() {
  const { t } = useLang();
  const qc = useQueryClient();
  const cid = useActiveConnection().data?.id;
  const canEdit = !!useMe().data?.permissions.includes("config.manage");
  const keyFor = useIdempotencyKey();
  const rules = useQuery({ queryKey: ["scale-rules", cid], queryFn: () => api<{ nomenclature: string; items: Rule[] }>(`/connections/${cid}/scale/rules`), enabled: !!cid });
  const [f, setF] = useState({ prefix: "27", plu_digits: 5, kind: "weight" as "weight" | "price", int_digits: 2, dec_digits: 3 });
  const total = f.prefix.length + f.plu_digits + f.int_digits + f.dec_digits;
  const add = useMutation({
    mutationFn: () => api<{ rule: Rule }>(`/connections/${cid}/scale/rules`, { body: f, headers: { "Idempotency-Key": keyFor(f) } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["scale-rules"] }),
  });
  const [label, setLabel] = useState("");
  const test = useMutation({ mutationFn: (code: string) => api<{ type: string; value?: number; base_code?: string; product?: string | null }>(`/connections/${cid}/scale/parse?code=${code}`) });
  const err = add.error instanceof ApiError ? add.error : null;
  const num = (k: "plu_digits" | "int_digits" | "dec_digits", label: string) => (
    <label className="block text-sm font-bold">{label}
      <input type="number" min={k === "dec_digits" ? 0 : 1} max={10} value={f[k]} onChange={(e) => setF({ ...f, [k]: Number(e.target.value) })} dir="ltr" className="mt-1 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-center" /></label>
  );
  if (rules.isError) return <ErrorBox message={rules.error instanceof ApiError && rules.error.code !== "network" ? `${errorText(t, rules.error.code)} (${rules.error.code})` : t("err_network")} reference={rules.error instanceof ApiError ? rules.error.correlationId : undefined} />;
  if (!rules.data) return <Spinner label={t("loading")} />;
  return (
    <div className="rise mx-auto max-w-3xl space-y-5">
      <header>
        <h1 className="flex items-center gap-3 text-3xl font-black"><Scale className="size-8 text-brand" aria-hidden /> {t("sc_title")}</h1>
        <p className="mt-1 text-soft">{t("sc_sub")}</p>
      </header>

      <Card className="space-y-3">
        <h2 className="flex items-center gap-2 text-lg font-black"><ScanBarcode className="size-5 text-brand" aria-hidden /> {t("sc_test")}</h2>
        <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); if (/^\d{8,14}$/.test(label)) test.mutate(label); }} className="flex gap-2">
          <input aria-label={t("sc_test")} placeholder={t("sc_test_ph")} value={label} onChange={(e) => setLabel(e.target.value.replace(/\D/g, ""))} dir="ltr" inputMode="numeric" className="min-h-12 flex-1 rounded-2xl border border-line bg-surface px-4 font-mono text-lg" />
          <Button type="submit" disabled={!/^\d{8,14}$/.test(label)} loading={test.isPending}>{t("sc_read")}</Button>
        </form>
        {test.data && (
          <p role="status" className="font-bold">
            {test.data.type === "weight" || test.data.type === "price"
              ? <>{t(test.data.type === "price" ? "sc_read_price" : "sc_read_weight")} <span dir="ltr">{test.data.value}</span> · {test.data.product ? <span className="text-ok">{test.data.product}</span> : <span className="text-warn">{t("sc_no_product")}</span>}</>
              : <span className="text-warn">{t("sc_not_scale")}</span>}
          </p>
        )}
      </Card>

      <Card className="space-y-3">
        <h2 className="text-lg font-black">{t("sc_formats")} <span className="text-xs font-normal text-soft">({rules.data.nomenclature})</span></h2>
        <ul className="divide-y divide-line">
          {rules.data.items.map((r) => (
            <li key={r.id} className="space-y-2 py-3">
              <div className="flex flex-wrap items-center gap-2"><span className="font-mono font-bold" dir="ltr">{r.pattern}</span><Badge tone={r.type === "price" ? "warn" : "brand"}>{t(r.type === "price" ? "sc_price" : "sc_weight")}</Badge>{r.managed && <Badge tone="ok">{t("sc_yours")}</Badge>}</div>
              {r.format && <Layout f={r.format} kind={r.type} />}
            </li>
          ))}
        </ul>
      </Card>

      {canEdit && (
        <Card className="space-y-4">
          <h2 className="flex items-center gap-2 text-lg font-black"><Plus className="size-5 text-brand" aria-hidden /> {t("sc_add")}</h2>
          <p className="text-sm text-soft">{t("sc_add_sub")}</p>
          <div role="radiogroup" aria-label={t("sc_kind")} className="grid grid-cols-2 gap-2">
            {(["weight", "price"] as const).map((k) => <button key={k} type="button" role="radio" aria-checked={f.kind === k} onClick={() => setF({ ...f, kind: k })} className={cn("min-h-12 rounded-2xl border-2 font-bold", f.kind === k ? "border-brand bg-brandsoft" : "border-line")}>{t(k === "price" ? "sc_kind_price" : "sc_kind_weight")}</button>)}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <label className="block text-sm font-bold">{t("sc_prefix")}
              <input value={f.prefix} onChange={(e) => setF({ ...f, prefix: e.target.value.replace(/\D/g, "").slice(0, 3) })} dir="ltr" inputMode="numeric" className="mt-1 min-h-11 w-full rounded-xl border border-line bg-surface px-3 text-center font-mono" /></label>
            {num("plu_digits", t("sc_plu_digits"))}{num("int_digits", t("sc_int_digits"))}{num("dec_digits", t("sc_dec_digits"))}
          </div>
          <Layout f={f} kind={f.kind} />
          <p className={cn("text-sm font-bold", total === 12 ? "text-ok" : "text-bad")}>{t("sc_total")}: {total} / 12</p>
          {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${err.code === "scale_rejected" ? err.message : ""}`} reference={err.correlationId} />}
          <Button onClick={() => add.mutate()} disabled={total !== 12 || !f.prefix} loading={add.isPending} className="w-full">{t("sc_save")}</Button>
        </Card>
      )}
    </div>
  );
}
