"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileUp, XCircle } from "lucide-react";
import { useState, type ChangeEvent } from "react";
import { InventoryTabs } from "@/components/inv-tabs";
import { Button, Card, ErrorBox } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { parseCsv, toObjects } from "@/lib/csv";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useMe } from "@/lib/queries";

interface Validation { import_id: string; valid: number; invalid: number; rows: { row: number; ok: boolean; errors: string[]; name?: string; qty?: number }[] }
interface Result { posted_rows: number; skipped_invalid: number; batches: { status: string; error?: string }[] }

export default function OpeningPage() {
  const { t } = useLang();
  const qc = useQueryClient();
  const me = useMe();
  const cid = useActiveConnection().data?.id;
  const canPost = !!me.data?.permissions.includes("inventory.approve");
  const [text, setText] = useState("");
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [check, setCheck] = useState<Validation | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const onFile = async (e: ChangeEvent<HTMLInputElement>) => { const f = e.target.files?.[0]; if (f) { setText(await f.text()); setCheck(null); setResult(null); } };
  const validate = useMutation({
    mutationFn: () => { const parsed = toObjects(parseCsv(text)); setRows(parsed); return api<Validation>(`/connections/${cid}/stock/opening/validate`, { body: { rows: parsed } }); },
    onSuccess: setCheck,
  });
  const commit = useMutation({
    mutationFn: () => api<Result>(`/connections/${cid}/stock/opening/commit?import_id=${check?.import_id}`, { body: { rows } }),
    onSuccess: (r) => { setResult(r); void qc.invalidateQueries({ queryKey: ["stock"] }); },
  });
  const err = (validate.error ?? commit.error) instanceof ApiError ? ((validate.error ?? commit.error) as ApiError) : null;
  return (
    <div className="rise mx-auto max-w-3xl space-y-5">
      <InventoryTabs />
      <header><h1 className="text-3xl font-black">{t("op_title")}</h1><p className="mt-1 text-soft">{t("op_sub")}</p></header>
      <Card className="space-y-4">
        <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-2xl bg-brandsoft px-4 font-bold text-brand"><FileUp className="size-5" aria-hidden /> {t("im_choose")}<input type="file" accept=".csv,text/csv,text/plain" className="sr-only" onChange={onFile} /></label>
        <label className="block text-sm font-bold">{t("im_paste")}
          <textarea value={text} onChange={(e) => { setText(e.target.value); setCheck(null); setResult(null); }} rows={6} dir="ltr" spellCheck={false} className="mt-2 w-full rounded-2xl border border-line bg-surface p-3 font-mono text-sm outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" /></label>
        {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
        <Button onClick={() => validate.mutate()} disabled={!text.trim() || !cid} loading={validate.isPending} className="w-full">{t("im_check")}</Button>
      </Card>
      {check && !result && (
        <Card className="space-y-4">
          <div className="flex gap-4 font-bold"><span className="text-ok">✓ {check.valid} {t("im_valid")}</span>{check.invalid > 0 && <span className="text-bad">✗ {check.invalid} {t("im_invalid")}</span>}</div>
          <ul className="max-h-80 divide-y divide-line overflow-auto rounded-2xl border border-line">
            {check.rows.map((r) => (
              <li key={r.row} className="flex items-start gap-3 p-3 text-sm">
                {r.ok ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-ok" aria-hidden /> : <XCircle className="mt-0.5 size-5 shrink-0 text-bad" aria-hidden />}
                <div><span className="font-bold">{t("im_row")} {r.row}</span> <span className="text-soft" dir="auto">{r.name ?? rows[r.row - 1]?.barcode}</span>{r.ok && <span className="text-soft"> · <b dir="ltr">{r.qty}</b></span>}
                  {r.errors.map((e, i) => <p key={i} className="text-bad" dir="auto">{e}</p>)}</div>
              </li>
            ))}
          </ul>
          {canPost ? <Button onClick={() => commit.mutate()} disabled={check.valid === 0} loading={commit.isPending} className="w-full">{t("op_commit")} ({check.valid})</Button> : <p className="font-bold text-warn">{t("op_owner_only")}</p>}
        </Card>
      )}
      {result && <Card className="space-y-1 border-ok/30 bg-oksoft"><p className="text-xl font-black text-ok">{t("op_done")}</p><p className="font-bold">{result.posted_rows} {t("op_posted")}</p>{result.batches.filter((b) => b.status === "failed").map((b, i) => <p key={i} className="text-bad" dir="auto">{b.error}</p>)}</Card>}
    </div>
  );
}
