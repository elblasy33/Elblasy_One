"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, ArrowRight, Check, CheckCircle2, Minus, Pencil, Plus, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Card, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { errorText, useLang } from "@/lib/i18n";
import { useConnections, usePlan, usePlans } from "@/lib/queries";
import type { Bilingual, Plan, Question, QOption, QuestionnaireOut } from "@/lib/types";

type Answers = Record<string, unknown>;
const DRAFT = "setup-draft";
const REVIEW = "review";

/** The wizard describes the business by how it works (what it sells, how customers buy and pay, what the
 *  goods are like...), never by picking a business type. It starts from the last profile, so it is also
 *  the place to change any answer later; a changed profile only ever produces a new, additive plan. */
export default function SetupPage() {
  const { t } = useLang();
  const conns = useConnections();
  const conn = conns.data?.find((c) => c.status === "active");
  const plans = usePlans(conn?.id);
  const latest = plans.data?.find((p) => p.status !== "superseded");
  const plan = usePlan(conn?.id, latest?.id);
  const router = useRouter();
  useEffect(() => {
    if (conns.isSuccess && !conns.isFetching && !conn) router.replace("/settings/connect");
  }, [conns.isSuccess, conns.isFetching, conn, router]);
  const ready = !!conn && plans.isSuccess && (!latest || plan.isSuccess);
  if (!ready) return <Spinner label={t("loading")} />;
  const saved = plan.data?.plan.profile as Answers | undefined;
  let initial: Answers = saved && !saved.vertical ? saved : {};
  try {
    const draft = JSON.parse(localStorage.getItem(`${DRAFT}-${conn.id}`) ?? "null") as Answers | null;
    if (draft) initial = draft;
  } catch { /* storage unavailable */ }
  return <Wizard key={conn.id} cid={conn.id} initial={initial} editing={!!saved && !saved.vertical} />;
}

function Wizard({ cid, initial, editing }: { cid: string; initial: Answers; editing: boolean }) {
  const { t, tr, dir } = useLang();
  const router = useRouter();
  const [answers, setAnswers] = useState<Answers>(initial);
  const [stage, setStage] = useState<string>(editing ? REVIEW : "selling");
  const q = useQuery({
    queryKey: ["questionnaire", JSON.stringify(answers)],
    queryFn: () => api<QuestionnaireOut>("/setup/questionnaire", { body: { answers } }),
    placeholderData: (p) => p,
  });
  useEffect(() => { try { localStorage.setItem(`${DRAFT}-${cid}`, JSON.stringify(answers)); } catch { /* storage unavailable */ } }, [answers, cid]);
  const build = useMutation({
    mutationFn: () => api<Plan>(`/connections/${cid}/setup/plans`, { body: { answers: q.data?.profile ?? answers } }),
    onSuccess: (p) => { try { localStorage.removeItem(`${DRAFT}-${cid}`); } catch { /* storage unavailable */ } router.replace(`/settings/plans/${p.id}`); },
  });
  const data = q.data;
  if (!data) return <Spinner label={t("loading")} />;
  const stages = data.stages;
  const order = [...stages.map((s) => s.id), REVIEW];
  const at = order.indexOf(stage);
  const Fwd = dir === "rtl" ? ArrowLeft : ArrowRight;
  const Back = dir === "rtl" ? ArrowRight : ArrowLeft;
  const set = (id: string, v: unknown) => setAnswers((a) => ({ ...a, [id]: v }));
  const value = (qq: Question) => (qq.id in answers ? answers[qq.id] : qq.default);
  const current = data.questions.filter((qq) => qq.stage === stage);
  const go = (s: string) => { setStage(s); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const err = build.error instanceof ApiError ? build.error : null;

  return (
    <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="min-w-0 space-y-5">
        <header className="rise">
          <h1 className="text-3xl font-black">{editing ? t("wz_edit_title") : t("setup_title")}</h1>
          <p className="mt-1 text-soft">{t("wz_sub")}</p>
        </header>
        <nav aria-label={t("wz_stages")} className="flex gap-1.5 overflow-x-auto pb-1">
          {order.map((s, i) => {
            const title = s === REVIEW ? t("wz_review") : tr(stages.find((x) => x.id === s)?.title);
            return (
              <button key={s} onClick={() => go(s)} aria-current={s === stage ? "step" : undefined}
                className={cn("flex min-h-11 shrink-0 items-center gap-2 rounded-2xl border-2 px-3 text-sm font-bold", s === stage ? "border-brand bg-brandsoft text-brand" : i < at ? "border-line bg-surface text-ink" : "border-line bg-surface text-soft")}>
                <span className={cn("grid size-6 place-items-center rounded-full text-xs", i < at ? "bg-brand text-brandink" : "bg-surface2")}>{i < at ? <Check className="size-3.5" aria-hidden /> : i + 1}</span>{title}
              </button>
            );
          })}
        </nav>

        {stage !== REVIEW ? (
          <section className="rise space-y-4" key={stage}>
            <p className="text-soft">{tr(stages.find((x) => x.id === stage)?.intro)}</p>
            {current.length === 0 && <Card className="py-8 text-center text-soft">{t("wz_nothing_here")}</Card>}
            {current.map((qq) => (
              <Card key={qq.id} className="space-y-3 p-5">
                <h2 className="text-lg font-black leading-snug">{tr(qq.text)}</h2>
                {qq.hint && <p className="-mt-2 text-sm text-soft">{tr(qq.hint)}</p>}
                <Input q={qq} value={value(qq)} onChange={(v) => set(qq.id, v)} t={t} tr={tr} />
              </Card>
            ))}
            <div className="flex items-center justify-between gap-3">
              {at > 0 ? <Button variant="ghost" onClick={() => go(order[at - 1]!)}><Back className="size-5" aria-hidden /> {t("back")}</Button> : <span />}
              <Button onClick={() => go(order[at + 1]!)}>{t("next")} <Fwd className="size-5" aria-hidden /></Button>
            </div>
          </section>
        ) : (
          <section className="rise space-y-4">
            <p className="text-soft">{t("wz_review_sub")}</p>
            {stages.map((s) => {
              const qs = data.questions.filter((qq) => qq.stage === s.id);
              if (!qs.length) return null;
              return (
                <Card key={s.id} className="space-y-2 p-5">
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="text-lg font-black">{tr(s.title)}</h2>
                    <button onClick={() => go(s.id)} className="inline-flex min-h-10 items-center gap-1 rounded-xl border border-line px-3 text-sm font-bold hover:bg-surface2"><Pencil className="size-4" aria-hidden /> {t("pe_edit")}</button>
                  </div>
                  <dl className="divide-y divide-line">
                    {qs.map((qq) => (
                      <div key={qq.id} className="flex flex-wrap justify-between gap-2 py-2 text-sm">
                        <dt className="text-soft">{tr(qq.text)}</dt>
                        <dd className="font-bold">{show(qq, value(qq), t, tr)}</dd>
                      </div>
                    ))}
                  </dl>
                </Card>
              );
            })}
            {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
            <Button onClick={() => build.mutate()} loading={build.isPending} disabled={(data.preview.unsupported?.length ?? 0) > 0} className="min-h-14 w-full text-lg">
              <Sparkles className="size-5" aria-hidden /> {build.isPending ? t("building") : t("wz_build")}
            </Button>
            <p className="text-center text-xs text-soft">{t("wz_build_note")}</p>
          </section>
        )}
      </div>

      <aside className="space-y-3 lg:sticky lg:top-4 lg:self-start" aria-label={t("wz_profile")}>
        <Card className="space-y-3 p-5">
          <h2 className="flex items-center gap-2 font-black"><Sparkles className="size-5 text-brand" aria-hidden /> {t("wz_profile")}</h2>
          <p className="text-xs text-soft">{t("wz_profile_sub")}</p>
          <ul className="space-y-2 text-sm">
            {data.preview.effects?.map((e) => <li key={e.feature} className="flex gap-2"><CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden /><span>{tr(e)}</span></li>)}
            {!data.preview.effects?.length && <li className="text-soft">{t("wz_basics")}</li>}
          </ul>
          {!!data.preview.limitations?.length && (
            <ul className="space-y-2 border-t border-line pt-3 text-sm">
              {data.preview.limitations.map((l) => <li key={l.code} className="flex gap-2 text-warn"><AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden /><span>{tr(l)}</span></li>)}
            </ul>
          )}
          {!!data.preview.unsupported?.length && (
            <ul className="space-y-2 border-t border-line pt-3 text-sm font-bold text-bad">
              {data.preview.unsupported.map((u) => <li key={u.code}>{u.reason}</li>)}
            </ul>
          )}
        </Card>
      </aside>
    </div>
  );
}

function show(q: Question, v: unknown, t: ReturnType<typeof useLang>["t"], tr: (b: Bilingual | undefined) => string): string {
  if (q.kind === "bool") return v ? t("yes") : t("no");
  if (q.kind === "number") return String(v ?? "");
  const opts = q.options as QOption[];
  const name = (x: unknown) => tr(opts.find((o) => o.value === x)?.text);
  if (q.kind === "multi") return Array.isArray(v) && v.length ? v.map(name).join("، ") : "—";
  return v == null ? t("wz_not_answered") : name(v);
}

function Input({ q, value, onChange, t, tr }: { q: Question; value: unknown; onChange: (v: unknown) => void; t: ReturnType<typeof useLang>["t"]; tr: (b: Bilingual | undefined) => string }) {
  const tile = "rounded-2xl border-2 p-3 text-start transition hover:border-brand active:scale-[0.99]";
  const opts = q.options as QOption[];
  if (q.kind === "bool")
    return (
      <div role="radiogroup" aria-label={tr(q.text)} className="grid grid-cols-2 gap-2">
        {[true, false].map((b) => (
          <button key={String(b)} role="radio" aria-checked={value === b} onClick={() => onChange(b)} className={cn(tile, "min-h-12 text-center font-black", value === b ? "border-brand bg-brandsoft text-brand" : "border-line bg-surface")}>{b ? t("yes") : t("no")}</button>
        ))}
      </div>
    );
  if (q.kind === "choice")
    return (
      <div role="radiogroup" aria-label={tr(q.text)} className="grid gap-2 sm:grid-cols-2">
        {opts.map((o) => (
          <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)} className={cn(tile, value === o.value ? "border-brand bg-brandsoft" : "border-line bg-surface")}>
            <span className="block font-bold">{tr(o.text)}</span>{o.hint && <span className="mt-0.5 block text-xs text-soft">{tr(o.hint)}</span>}
          </button>
        ))}
      </div>
    );
  if (q.kind === "multi") {
    const list = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="grid gap-2 sm:grid-cols-2">
        {opts.map((o) => {
          const on = list.includes(o.value);
          return (
            <button key={o.value} role="checkbox" aria-checked={on} onClick={() => onChange(on ? list.filter((x) => x !== o.value) : [...list, o.value])} className={cn(tile, "flex gap-3", on ? "border-brand bg-brandsoft" : "border-line bg-surface")}>
              <span className={cn("mt-0.5 grid size-5 shrink-0 place-items-center rounded-md border-2", on ? "border-brand bg-brand text-brandink" : "border-line")}>{on && <Check className="size-3.5" aria-hidden />}</span>
              <span><span className="block font-bold">{tr(o.text)}</span>{o.hint && <span className="mt-0.5 block text-xs text-soft">{tr(o.hint)}</span>}</span>
            </button>
          );
        })}
      </div>
    );
  }
  const n = typeof value === "number" ? value : 1;
  const min = q.min ?? 1, max = q.max ?? 100;
  return (
    <div className="flex items-center gap-4">
      <button aria-label="−" onClick={() => onChange(Math.max(min, n - 1))} className="grid size-12 place-items-center rounded-2xl border-2 border-line hover:border-brand"><Minus aria-hidden /></button>
      <output className="min-w-12 text-center text-3xl font-black" aria-live="polite">{n}</output>
      <button aria-label="+" onClick={() => onChange(Math.min(max, n + 1))} className="grid size-12 place-items-center rounded-2xl border-2 border-line hover:border-brand"><Plus aria-hidden /></button>
    </div>
  );
}
