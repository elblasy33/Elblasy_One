"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Paperclip } from "lucide-react";
import { useState } from "react";
import { ErrorBox } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";

const MAX = 3 * 1024 * 1024;
const toBase64 = (file: File) => new Promise<string>((resolve, reject) => {
  const r = new FileReader();
  r.onload = () => resolve(String(r.result).split(",")[1] ?? "");
  r.onerror = () => reject(r.error);
  r.readAsDataURL(file);
});

/** Receipts and invoices on one expense: list, download (as a file, never rendered inline) and add. */
export function ExpenseDocs({ cid, billId, canAttach }: { cid: string; billId: number; canAttach: boolean }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const keyFor = useIdempotencyKey();
  const [open, setOpen] = useState(false);
  const [tooBig, setTooBig] = useState(false);
  const docs = useQuery({ queryKey: ["expense-docs", cid, billId], queryFn: () => api<{ items: { id: number; name: string; size: number }[] }>(`/connections/${cid}/money/expenses/${billId}/documents`), enabled: open });
  const up = useMutation({
    mutationFn: async (file: File) => {
      const body = { filename: file.name, data_base64: await toBase64(file) };
      return api(`/connections/${cid}/money/expenses/${billId}/documents`, { body, headers: { "Idempotency-Key": keyFor({ billId, name: file.name, size: file.size, at: file.lastModified }) } });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["expense-docs", cid, billId] }),
  });
  const err = up.error instanceof ApiError ? up.error : null;
  return (
    <div className="w-full">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="inline-flex min-h-9 items-center gap-1 text-sm font-bold text-brand"><Paperclip className="size-4" aria-hidden /> {t("ed_docs")}{docs.data ? ` (${docs.data.items.length})` : ""}</button>
      {open && (
        <div className="mt-2 space-y-2 rounded-2xl bg-surface2 p-3">
          {docs.data?.items.length === 0 && <p className="text-sm text-soft">{t("ed_none")}</p>}
          <ul className="space-y-1">{docs.data?.items.map((d) => <li key={d.id}><a href={`/api/connections/${cid}/money/documents/${d.id}`} className="inline-flex items-center gap-2 text-sm font-bold text-brand underline" dir="auto"><FileText className="size-4" aria-hidden /> {d.name} <span className="text-xs font-normal text-soft" dir="ltr">{Math.max(1, Math.round(d.size / 1024))} KB</span></a></li>)}</ul>
          {canAttach && (
            <label className="block text-sm font-bold">{t("ed_add")}
              <input type="file" accept="application/pdf,image/png,image/jpeg,image/webp" className="mt-1 block w-full text-sm"
                onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; setTooBig(false); if (!f) return; if (f.size > MAX) { setTooBig(true); return; } up.mutate(f); }} />
            </label>
          )}
          {tooBig && <p role="alert" className="text-sm font-bold text-bad">{t("ed_too_big")}</p>}
          {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${err.code === "document_rejected" ? err.message : ""}`} reference={err.correlationId} />}
        </div>
      )}
    </div>
  );
}
