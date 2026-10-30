"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Factory, Package, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { money } from "@/components/receipt";
import { Badge, Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useActiveConnection, useProducts } from "@/lib/queries";

interface Line { template_id: number; name: string; qty: string; cost?: number }
type Kind = "manufacture" | "kit";
interface Bom { found: boolean; kind?: Kind; quantity?: number; components?: { template_id: number; name: string; qty: number; cost?: number }[]; unit_cost?: number; price?: number; margin?: number }

function RecipeForm() {
  const { t } = useLang();
  const finished = Number(useSearchParams().get("template") ?? 0);
  const cid = useActiveConnection().data?.id;
  const bom = useQuery({ queryKey: ["bom", cid, finished], queryFn: () => api<Bom>(`/connections/${cid}/catalog/recipes/${finished}`), enabled: !!cid && !!finished });
  if (!finished) return <ErrorBox message={t("rc_pick")} />;
  if (!bom.data) return <Spinner label={t("loading")} />;
  return <Editor key={JSON.stringify(bom.data)} cid={cid!} finished={finished} bom={bom.data} />;
}

/** One screen for both ways a product can be made of others: a recipe made in batches (production orders),
 *  or a kit sold as one item whose parts leave stock at the sale. Editing changes future use only. */
function Editor({ cid, finished, bom }: { cid: string; finished: number; bom: Bom }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const keyFor = useIdempotencyKey();
  const editing = bom.found;
  const [kind, setKind] = useState<Kind>(bom.kind ?? "manufacture");
  const [text, setText] = useState("");
  const [lines, setLines] = useState<Line[]>((bom.components ?? []).map((c) => ({ template_id: c.template_id, name: c.name, qty: String(c.qty), ...(c.cost !== undefined ? { cost: c.cost } : {}) })));
  const [yieldQty, setYield] = useState(String(bom.quantity ?? 1));
  const found = useProducts(cid, text.trim(), 0, 8);
  const payload = { template_id: finished, kind, quantity: kind === "kit" ? 1 : Number(yieldQty || 1), replace: editing,
    components: lines.map((l) => ({ template_id: l.template_id, qty: Number(l.qty || 0) })) };
  const save = useMutation({
    mutationFn: () => api<{ recipe: Bom }>(`/connections/${cid}/catalog/recipes`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["bom"] }); void qc.invalidateQueries({ queryKey: ["recipes"] }); },
  });
  const err = save.error instanceof ApiError ? save.error : null;
  const showCost = lines.every((l) => l.cost !== undefined) && bom.price !== undefined && lines.length > 0;
  const perUnit = showCost ? lines.reduce((s, l) => s + Number(l.qty || 0) * (l.cost ?? 0), 0) / (kind === "kit" ? 1 : Number(yieldQty || 1)) : 0;

  if (save.isSuccess)
    return (
      <Card className="rise space-y-3 border-ok/30 bg-oksoft text-center">
        <CheckCircle2 className="pop mx-auto size-12 text-ok" aria-hidden />
        <p className="text-2xl font-black text-ok">{t(kind === "kit" ? "rc_kit_saved" : "rc_saved")}</p>
        {save.data.recipe.unit_cost !== undefined && <p className="font-bold">{t("rc_unit_cost")}: <span dir="ltr">{money(save.data.recipe.unit_cost)}</span> · {t("rc_margin")}: <span dir="ltr">{money(save.data.recipe.margin ?? 0)}</span></p>}
        <Link href={kind === "kit" ? "/inventory" : "/inventory/production"} className="font-bold text-brand">{t(kind === "kit" ? "np_to_list" : "rc_go_produce")}</Link>
      </Card>
    );

  return (
    <div className="rise space-y-5">
      <h1 className="text-3xl font-black">{editing ? t("rc_edit_title") : t("rc_title")}</h1>
      <div role="radiogroup" aria-label={t("rc_kind")} className="grid gap-3 sm:grid-cols-2">
        {([["manufacture", Factory, "rc_kind_make", "rc_kind_make_sub"], ["kit", Package, "rc_kind_kit", "rc_kind_kit_sub"]] as const).map(([k, Icon, title, sub]) => (
          <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => setKind(k)}
            className={cn("rounded-2xl border-2 p-4 text-start transition", kind === k ? "border-brand bg-brandsoft" : "border-line bg-surface hover:border-brand")}>
            <span className="flex items-center gap-2 font-black"><Icon className="size-5 text-brand" aria-hidden /> {t(title)}</span>
            <span className="mt-1 block text-sm text-soft">{t(sub)}</span>
          </button>
        ))}
      </div>
      {editing && <p className="text-sm text-soft">{t("rc_edit_note")}</p>}
      <Card className="space-y-3">
        <label className="block text-sm font-bold">{t("rc_search")}
          <input value={text} onChange={(e) => setText(e.target.value)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-4 text-base outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" />
        </label>
        {text.trim() && found.data && (
          <ul className="divide-y divide-line rounded-2xl border border-line">
            {found.data.items.filter((p) => p.template_id !== finished && p.variant_count === 1 && !lines.some((l) => l.template_id === p.template_id)).map((p) => (
              <li key={p.template_id}>
                <button type="button" onClick={() => { setLines([...lines, { template_id: p.template_id, name: p.name, qty: "1", ...(p.cost !== undefined ? { cost: p.cost } : {}) }]); setText(""); }} className="flex min-h-12 w-full items-center justify-between px-4 text-start hover:bg-surface2">
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
              {l.cost !== undefined && <span className="hidden text-xs text-soft sm:inline" dir="ltr">{money(l.cost)}</span>}
              <input aria-label={`${t("rc_qty")}: ${l.name}`} type="number" inputMode="decimal" min="0" step="any" value={l.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} dir="ltr" className="min-h-11 w-24 rounded-xl border border-line bg-surface px-3 text-center" />
              <button type="button" aria-label="remove" onClick={() => setLines(lines.filter((_, j) => j !== i))} className="grid size-11 place-items-center rounded-xl text-bad hover:bg-badsoft"><Trash2 className="size-5" aria-hidden /></button>
            </div>
          ))}
          {kind === "manufacture" && (
            <label className="flex items-center justify-between gap-3 border-t border-line pt-3 font-bold">{t("rc_yield")}
              <input type="number" inputMode="decimal" min="0" step="any" value={yieldQty} onChange={(e) => setYield(e.target.value)} dir="ltr" className="min-h-11 w-24 rounded-xl border border-line bg-surface px-3 text-center" />
            </label>
          )}
          {showCost && (
            <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3 text-sm">
              <Badge>{t("rc_unit_cost")}: <span dir="ltr">{money(perUnit)}</span></Badge>
              <Badge>{t("prod_price")}: <span dir="ltr">{money(bom.price ?? 0)}</span></Badge>
              <Badge tone={(bom.price ?? 0) - perUnit >= 0 ? "ok" : "bad"}>{t("rc_margin")}: <span dir="ltr">{money((bom.price ?? 0) - perUnit)}</span></Badge>
            </div>
          )}
        </Card>
      )}
      {err && <ErrorBox message={err.code === "network" ? t("err_network") : `${errorText(t, err.code)} ${err.code === "recipe_rejected" ? err.message : ""}`} reference={err.correlationId} />}
      <Button onClick={() => save.mutate()} disabled={lines.length === 0 || lines.some((l) => !(Number(l.qty) > 0))} loading={save.isPending} className="w-full">{t(kind === "kit" ? "rc_kit_save" : "rc_save")}</Button>
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
