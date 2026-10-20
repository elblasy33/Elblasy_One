"use client";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Minus, Plus, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { errorText, useLang, type TKey } from "@/lib/i18n";
import { useConnections } from "@/lib/queries";
import type { Plan, Question, QuestionnaireOut } from "@/lib/types";

type Answers = Record<string, unknown>;
const EMOJI: Record<string, string> = {
  grocery: "🛒", bookstore: "📚", shoes: "👟", clothing: "👕", electronics: "📱", general: "🏪",
  cash: "💵", card: "💳", wallet: "📱", bank_transfer: "🏦",
};
const label = (t: (k: TKey) => string, q: string, o: string) => t((q === "vertical" ? `v_${o}` : `p_${o}`) as TKey);

export default function SetupWizard() {
  const { t, tr, dir } = useLang();
  const router = useRouter();
  const conns = useConnections();
  const conn = conns.data?.find((c) => c.status === "active");
  const [answers, setAnswers] = useState<Answers>({});
  const [qs, setQs] = useState<Question[]>([]);
  const [idx, setIdx] = useState(0);
  const ask = useMutation({ mutationFn: (a: Answers) => api<QuestionnaireOut>("/setup/questionnaire", { body: { answers: a } }) });
  const build = useMutation({
    mutationFn: () => api<Plan>(`/connections/${conn?.id}/setup/plans`, { body: { answers } }),
    onSuccess: (p) => router.replace(`/settings/plans/${p.id}`),
  });
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    ask.mutate({}, { onSuccess: (r) => setQs(r.questions) });
  }, [ask]);
  useEffect(() => {
    if (conns.isSuccess && !conns.isFetching && !conn) router.replace("/settings/connect");
  }, [conns.isSuccess, conns.isFetching, conn, router]);

  const q = qs[idx];
  const done = qs.length > 0 && idx >= qs.length;
  const Fwd = dir === "rtl" ? ArrowLeft : ArrowRight;
  const Back = dir === "rtl" ? ArrowRight : ArrowLeft;

  const answer = (id: string, v: unknown) => {
    const next = { ...answers, [id]: v };
    setAnswers(next);
    ask.mutate(next, { onSuccess: (r) => { setQs(r.questions); setIdx((i) => i + 1); } });
  };

  const err = (build.error ?? ask.error) instanceof ApiError ? ((build.error ?? ask.error) as ApiError) : null;
  if (!qs.length) return <Spinner label={t("loading")} />;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <header className="rise">
        <h1 className="text-3xl font-black">{t("setup_title")}</h1>
        <p className="mt-1 text-soft">{t("setup_sub")}</p>
      </header>
      <div className="h-2 overflow-hidden rounded-full bg-surface2" role="progressbar" aria-valuemin={0} aria-valuemax={qs.length} aria-valuenow={Math.min(idx, qs.length)}>
        <div className="h-full rounded-full bg-brand transition-all duration-500" style={{ width: `${(Math.min(idx, qs.length) / qs.length) * 100}%` }} />
      </div>

      {q && !done && (
        <Card key={q.id} className="rise space-y-6 p-6 sm:p-8">
          <p className="text-sm font-bold text-soft">{t("question_of")} {idx + 1} / {qs.length}</p>
          <h2 className="text-2xl font-black leading-snug">{tr(q.text)}</h2>
          <QuestionInput q={q} value={answers[q.id]} onAnswer={(v) => answer(q.id, v)} busy={ask.isPending} t={t} />
          {idx > 0 && (
            <button onClick={() => setIdx(idx - 1)} className="inline-flex items-center gap-2 text-sm font-bold text-soft hover:text-ink">
              <Back className="size-4" aria-hidden /> {t("back")}
            </button>
          )}
        </Card>
      )}

      {done && (
        <Card className="rise space-y-5 p-8 text-center">
          <div className="mx-auto grid size-16 place-items-center rounded-3xl bg-accentsoft text-accent"><Sparkles className="size-8" aria-hidden /></div>
          <p className="text-xl font-black">{t("build_plan")}</p>
          {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
          <Button onClick={() => build.mutate()} loading={build.isPending} className="w-full">
            {build.isPending ? t("building") : <>{t("build_plan")} <Fwd className="size-5" aria-hidden /></>}
          </Button>
          <button onClick={() => setIdx(0)} className="text-sm font-bold text-soft hover:text-ink">{t("back")}</button>
        </Card>
      )}
    </div>
  );
}

function QuestionInput({ q, value, onAnswer, busy, t }: { q: Question; value: unknown; onAnswer: (v: unknown) => void; busy: boolean; t: (k: TKey) => string }) {
  const [multi, setMulti] = useState<string[]>(Array.isArray(value) ? (value as string[]) : ((q.default as string[] | null) ?? []));
  const [num, setNum] = useState<number>(typeof value === "number" ? value : ((q.default as number | null) ?? 1));
  const tile = "min-h-20 rounded-2xl border-2 border-line bg-surface p-4 text-lg font-black transition hover:border-brand hover:bg-brandsoft active:scale-[0.98] disabled:opacity-50";
  if (q.kind === "choice")
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {q.options.map((o) => (
          <button key={o} disabled={busy} onClick={() => onAnswer(o)} className={cn(tile, "flex items-center gap-3", value === o && "border-brand bg-brandsoft")}>
            <span className="text-3xl" aria-hidden>{EMOJI[o]}</span> {label(t, q.id, o)}
          </button>
        ))}
      </div>
    );
  if (q.kind === "bool")
    return (
      <div className="grid grid-cols-2 gap-3">
        {[true, false].map((b) => (
          <button key={String(b)} disabled={busy} onClick={() => onAnswer(b)} className={cn(tile, "text-center text-xl", value === b && "border-brand bg-brandsoft")}>
            {b ? `✅ ${t("yes")}` : `✖️ ${t("no")}`}
          </button>
        ))}
      </div>
    );
  if (q.kind === "multi")
    return (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          {q.options.map((o) => {
            const on = multi.includes(o);
            return (
              <button key={o} aria-pressed={on} onClick={() => setMulti(on ? multi.filter((x) => x !== o) : [...multi, o])} className={cn(tile, "flex items-center gap-3", on && "border-brand bg-brandsoft")}>
                <span className="text-2xl" aria-hidden>{EMOJI[o]}</span> {label(t, q.id, o)}
              </button>
            );
          })}
        </div>
        <Button disabled={busy || multi.length === 0} onClick={() => onAnswer(multi)} className="w-full">{t("next")}</Button>
      </div>
    );
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-center gap-6">
        <button aria-label="−" onClick={() => setNum(Math.max(1, num - 1))} className="grid size-14 place-items-center rounded-2xl border-2 border-line text-2xl hover:border-brand"><Minus aria-hidden /></button>
        <output className="min-w-16 text-center text-5xl font-black" aria-live="polite">{num}</output>
        <button aria-label="+" onClick={() => setNum(Math.min(100, num + 1))} className="grid size-14 place-items-center rounded-2xl border-2 border-line text-2xl hover:border-brand"><Plus aria-hidden /></button>
      </div>
      <Button disabled={busy} onClick={() => onAnswer(num)} className="w-full">{t("next")}</Button>
    </div>
  );
}
