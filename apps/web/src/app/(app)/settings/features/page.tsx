"use client";
import { useMutation } from "@tanstack/react-query";
import { SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { errorText, useLang, type TKey } from "@/lib/i18n";
import { useActiveConnection, usePlan, usePlans } from "@/lib/queries";
import type { Plan } from "@/lib/types";

type Answers = Record<string, unknown>;
/** Each switch is one answer of the business profile. Switching it builds a new plan that the owner reviews and
 *  approves; nothing changes in Odoo before that. Switching off only hides the feature here: data that Odoo
 *  already holds for it (units, price lists, points...) is never deleted. */
const SWITCHES: { key: string; feature: string; title: TKey; sub: TKey }[] = [
  { key: "multiple_uom", feature: "uom", title: "fs_uom", sub: "fs_uom_sub" },
  { key: "wholesale_prices", feature: "pricelists", title: "fs_pricelists", sub: "fs_pricelists_sub" },
  { key: "loyalty", feature: "loyalty", title: "fs_loyalty", sub: "fs_loyalty_sub" },
  { key: "makes_own_products", feature: "manufacturing", title: "fs_mrp", sub: "fs_mrp_sub" },
  { key: "uses_weighing_scale", feature: "weighing", title: "fs_weight", sub: "fs_weight_sub" },
  { key: "needs_variants", feature: "variants", title: "fs_variants", sub: "fs_variants_sub" },
  { key: "tracks_expiry", feature: "expiry", title: "fs_expiry", sub: "fs_expiry_sub" },
  { key: "tracks_serials", feature: "serials", title: "fs_serials", sub: "fs_serials_sub" },
  { key: "sells_on_credit", feature: "credit_sales", title: "fs_credit", sub: "fs_credit_sub" },
];

export default function FeaturesPage() {
  const { t } = useLang();
  const router = useRouter();
  const cid = useActiveConnection().data?.id;
  const plans = usePlans(cid);
  const latest = plans.data?.find((p) => p.status !== "superseded");
  const plan = usePlan(cid, latest?.id);
  const [busy, setBusy] = useState<string | null>(null);
  const build = useMutation({
    mutationFn: (answers: Answers) => api<Plan>(`/connections/${cid}/setup/plans`, { body: { answers } }),
    onSuccess: (p) => router.push(`/settings/plans/${p.id}`),
    onSettled: () => setBusy(null),
  });
  if (!cid || plans.isLoading || (latest && !plan.data)) return <Spinner label={t("loading")} />;
  if (!latest) return <Card className="space-y-2 py-10 text-center"><p className="font-black">{t("fs_no_profile")}</p><Link href="/settings/setup" className="font-bold text-brand">{t("settings_setup")}</Link></Card>;
  const profile = { ...(plan.data!.plan.profile as Answers) };
  const features = new Set(plan.data!.plan.features as string[]);
  const flip = (key: string, on: boolean) => {
    const answers: Answers = { ...profile, [key]: on };
    delete answers.vertical; // a profile built from a business type is carried over to the answer-based questions
    const sells = new Set((answers.sells as string[] | undefined) ?? ["goods"]);
    if (key === "makes_own_products" && on) sells.add("made");
    if (key === "tracks_serials" && !on) answers.tracks_serials = false;
    answers.sells = [...sells];
    setBusy(key);
    build.mutate(answers);
  };
  const err = build.error instanceof ApiError ? build.error : null;
  return (
    <div className="rise mx-auto max-w-3xl space-y-5">
      <header>
        <h1 className="flex items-center gap-3 text-3xl font-black"><SlidersHorizontal className="size-8 text-brand" aria-hidden /> {t("fs_title")}</h1>
        <p className="mt-1 text-soft">{t("fs_sub")}</p>
      </header>
      {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
      <Card className="p-2">
        <ul className="divide-y divide-line">
          {SWITCHES.map((s) => {
            const on = features.has(s.feature);
            return (
              <li key={s.key} className="flex items-center justify-between gap-4 px-3 py-4">
                <div className="min-w-0"><p className="font-black">{t(s.title)}</p><p className="text-sm text-soft">{t(s.sub)}</p></div>
                <button type="button" role="switch" aria-checked={on} aria-label={t(s.title)} disabled={!!busy} onClick={() => flip(s.key, !on)}
                  className={cn("h-8 w-14 shrink-0 rounded-full p-1 transition disabled:opacity-50", on ? "bg-brand" : "bg-line")}>
                  <span className={cn("block size-6 rounded-full bg-white transition", on ? "translate-x-6 rtl:-translate-x-6" : "", busy === s.key && "animate-pulse")} />
                </button>
              </li>
            );
          })}
        </ul>
      </Card>
      <p className="text-xs text-soft">{t("fs_note")}</p>
    </div>
  );
}
