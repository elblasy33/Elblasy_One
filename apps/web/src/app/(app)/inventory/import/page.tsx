"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileUp, XCircle } from "lucide-react";
import { useState, type ChangeEvent } from "react";
import { Button, Card, ErrorBox } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { parseCsv, TEMPLATE_CSV, toObjects } from "@/lib/csv";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection } from "@/lib/queries";
import type { ImportResult, ImportValidation } from "@/lib/types";

export default function ImportPage() {
  const { t } = useLang();
  const qc = useQueryClient();
  const cid = useActiveConnection().data?.id;
  const [text, setText] = useState("");
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [check, setCheck] = useState<ImportValidation | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setText(await f.text());
  };
  const validate = useMutation({
    mutationFn: () => {
      const parsed = toObjects(parseCsv(text));
      setRows(parsed);
      setResult(null);
      return api<ImportValidation>(`/connections/${cid}/catalog/import/validate`, { body: { rows: parsed } });
    },
    onSuccess: setCheck,
  });
  const commit = useMutation({
    mutationFn: () => api<ImportResult>(`/connections/${cid}/catalog/import/commit?import_id=${check?.import_id}`, { body: { rows } }),
    onSuccess: (r) => { setResult(r); void qc.invalidateQueries({ queryKey: ["products"] }); },
  });
  const err = (validate.error ?? commit.error) instanceof ApiError ? ((validate.error ?? commit.error) as ApiError) : null;
  const tooMany = toObjects(parseCsv(text)).length > 100;

  return (
    <div className="rise mx-auto max-w-3xl space-y-5">
      <header>
        <h1 className="text-3xl font-black">{t("im_title")}</h1>
        <p className="mt-1 text-soft">{t("im_sub")} {t("im_limit")}</p>
      </header>
      <Card className="space-y-4">
        <div className="flex flex-wrap gap-3">
          <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-2xl bg-brandsoft px-4 font-bold text-brand">
            <FileUp className="size-5" aria-hidden /> {t("im_choose")}
            <input type="file" accept=".csv,text/csv,text/plain" className="sr-only" onChange={onFile} />
          </label>
          <a download="products-template.csv" href={`data:text/csv;charset=utf-8,${encodeURIComponent(TEMPLATE_CSV)}`} className="inline-flex min-h-11 items-center gap-2 rounded-2xl border border-line px-4 text-sm font-bold hover:bg-surface2">
            <Download className="size-4" aria-hidden /> {t("im_template")}
          </a>
        </div>
        <label className="block text-sm font-bold">{t("im_paste")}
          <textarea value={text} onChange={(e) => { setText(e.target.value); setCheck(null); setResult(null); }} rows={7} dir="ltr" spellCheck={false}
            className="mt-2 w-full rounded-2xl border border-line bg-surface p-3 font-mono text-sm outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
        </label>
        {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
        <Button onClick={() => validate.mutate()} disabled={!text.trim() || !cid || tooMany} loading={validate.isPending} className="w-full">{t("im_check")}</Button>
        {tooMany && <p className="text-sm font-bold text-bad">{t("im_limit")}</p>}
      </Card>

      {check && !result && (
        <Card className="space-y-4">
          <div className="flex flex-wrap gap-4 font-bold">
            <span className="text-ok">✓ {check.valid} {t("im_valid")}</span>
            {check.invalid > 0 && <span className="text-bad">✗ {check.invalid} {t("im_invalid")}</span>}
          </div>
          <ul className="max-h-80 divide-y divide-line overflow-auto rounded-2xl border border-line">
            {check.rows.map((r) => (
              <li key={r.row} className="flex items-start gap-3 p-3 text-sm">
                {r.ok ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-ok" aria-hidden /> : <XCircle className="mt-0.5 size-5 shrink-0 text-bad" aria-hidden />}
                <div><span className="font-bold">{t("im_row")} {r.row}</span> <span className="text-soft" dir="auto">{rows[r.row - 1]?.name}</span>
                  {r.errors.map((e, i) => <p key={i} className="text-bad" dir="auto">{e}</p>)}</div>
              </li>
            ))}
          </ul>
          <Button onClick={() => commit.mutate()} disabled={check.valid === 0} loading={commit.isPending} className="w-full">{t("im_commit")} ({check.valid})</Button>
        </Card>
      )}
      {result && (
        <Card className="space-y-2 border-ok/30 bg-oksoft">
          <p className="text-xl font-black text-ok">{t("im_done")}</p>
          <p className="font-bold">{result.created} {t("im_created")} · {result.skipped + result.failed} {t("im_skipped")}</p>
          {result.rows.filter((r) => r.status === "failed").map((r) => <p key={r.row} className="text-sm text-bad" dir="auto">{t("im_row")} {r.row}: {r.errors?.join(", ")}</p>)}
        </Card>
      )}
    </div>
  );
}
