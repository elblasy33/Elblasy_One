"use client";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useConnections, useProducts } from "@/lib/queries";

interface Line { template_id: number; name: string; qty: string }

function RecipeForm() {
  const { t } = useLang();
  const params = useSearchParams();
  const finished = Number(params.get("template") ?? 0);
  const cid = useConnections().data?.find((c) => c.status === "active")?.id;
  const keyFor = useIdempotencyKey();
  const [text, setText] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [yieldQty, setYield] = useState("1");
  const found = useProducts(cid, text.trim(), 0, 8);
  const payload = { template_id: finished, quantity: Number(yieldQty || 1), components: lines.map((l) => ({ template_id: l.template_id, qty: Number(l.qty || 0) })) };
  const save = useMutation({ mutationFn: () => api(`/connections/${cid}/catalog/recipes`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }) });
  const err = save.error instanceof ApiError ? save.error : null;

  if (save.isSuccess)
    return (
      <Card className="rise space-y-3 border-ok/30 bg-oksoft text-center">
        <CheckCircle2 className="pop mx-auto size-12 text-ok" aria-hidden />
        <p className="text-2xl font-black text-ok">{t("rc_saved")}</p>
        <Link href="/inventory" className="font-bold text-brand">{t("np_to_list")}</Link>
      </Card>
    );
  if (!finished) return <ErrorBox message={t("rc_pick")} />;

  return (
    <div className="rise space-y-5">
      <h1 className="text-3xl font-black">{t("rc_title")}</h1>
      <Card className="space-y-3">
        <label className="block text-sm font-bold">{t("rc_search")}
          <input value={text} onChange={(e) => setText(e.target.value)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-4 text-base outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
        </label>
        {text.trim() && found.data && (
          <ul className="divide-y divide-line rounded-2xl border border-line">
            {found.data.items.filter((p) => p.template_id !== finished && p.variant_count === 1 && !lines.some((l) => l.template_id === p.template_id)).map((p) => (
              <li key={p.template_id}>
                <button type="button" onClick={() => { setLines([...lines, { template_id: p.template_id, name: p.name, qty: "1" }]); setText(""); }} className="flex min-h-12 w-full items-center justify-between px-4 text-start hover:bg-surface2">
                  <span className="font-bold">{p.name}</span><Plus className="size-5 text-brand" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {lines.length > 0 && (
        <Card className="space-y-3">
          {lines.map((l, i) => (
            <div key={l.template_id} className="flex items-center gap-3">
              <span className="min-w-0 flex-1 truncate font-bold">{l.name}</span>
              <input aria-label={t("rc_qty")} type="number" inputMode="decimal" min="0" step="any" value={l.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} dir="ltr" className="min-h-11 w-24 rounded-xl border border-line bg-surface px-3 text-center" />
              <button type="button" aria-label="remove" onClick={() => setLines(lines.filter((_, j) => j !== i))} className="grid size-11 place-items-center rounded-xl text-bad hover:bg-badsoft"><Trash2 className="size-5" aria-hidden /></button>
            </div>
          ))}
          <label className="flex items-center justify-between gap-3 border-t border-line pt-3 font-bold">{t("rc_yield")}
            <input type="number" inputMode="decimal" min="0" step="any" value={yieldQty} onChange={(e) => setYield(e.target.value)} dir="ltr" className="min-h-11 w-24 rounded-xl border border-line bg-surface px-3 text-center" />
          </label>
        </Card>
      )}
      {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${err.code === "recipe_rejected" ? err.message : ""}`} reference={err.correlationId} />}
      <Button onClick={() => save.mutate()} disabled={lines.length === 0 || lines.some((l) => !(Number(l.qty) > 0))} loading={save.isPending} className="w-full">{t("rc_save")}</Button>
    </div>
  );
}

export default function RecipePage() {
  return (
    <Suspense fallback={<Spinner />}>
      <RecipeForm />
    </Suspense>
  );
}
