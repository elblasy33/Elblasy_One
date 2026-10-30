"use client";
import { AlertTriangle, Keyboard, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useLang } from "@/lib/i18n";
import { ACTIONS, comboOf, isModifierOnly, refusal, RISKY, saveBindings, useBindings, type Action } from "@/lib/shortcuts";

/** Change the till shortcuts on this device: press "change", then the new key. Conflicts are swapped on
 *  request, keys the browser or system often keeps are flagged, and keys that would break typing refused. */
export default function ShortcutsPage() {
  const { t } = useLang();
  const keys = useBindings();
  const [listening, setListening] = useState<Action | null>(null);
  const [pending, setPending] = useState<{ action: Action; combo: string; other: Action } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const label = (a: Action) => t(ACTIONS.find((x) => x.id === a)!.label);

  useEffect(() => {
    if (!listening) return;
    const onKey = (e: KeyboardEvent) => {
      if (isModifierOnly(e.key)) return;
      e.preventDefault();
      e.stopPropagation();
      if (e.key === "Escape" && !e.ctrlKey && !e.altKey) { setListening(null); return; }
      const combo = comboOf(e);
      const why = refusal(listening, combo);
      if (why) { setMsg(`${combo}: ${t(why)}`); return; }
      const other = (Object.keys(keys) as Action[]).find((a) => a !== listening && keys[a] === combo);
      setListening(null);
      if (other) { setPending({ action: listening, combo, other }); return; }
      saveBindings({ ...keys, [listening]: combo });
      setMsg(null);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [listening, keys, t]);

  const swap = () => {
    if (!pending) return;
    saveBindings({ ...keys, [pending.action]: pending.combo, [pending.other]: keys[pending.action] });
    setPending(null);
  };

  return (
    <div className="rise mx-auto max-w-3xl space-y-5">
      <header>
        <h1 className="flex items-center gap-3 text-3xl font-black"><Keyboard className="size-8 text-brand" aria-hidden /> {t("ks_title")}</h1>
        <p className="mt-1 text-soft">{t("ks_sub")}</p>
      </header>
      {msg && <div role="alert"><Card className="border-bad/30 bg-badsoft font-bold text-bad">{msg}</Card></div>}
      {pending && (
        <div role="alert"><Card className="space-y-3 border-warn/40 bg-warnsoft">
          <p className="font-bold">{t("ks_conflict").replace("{key}", pending.combo).replace("{other}", label(pending.other))}</p>
          <div className="flex gap-2"><Button onClick={swap}>{t("ks_swap")}</Button><Button variant="ghost" onClick={() => setPending(null)}>{t("cancel")}</Button></div>
        </Card></div>
      )}
      <Card className="p-2">
        <ul className="divide-y divide-line">
          {ACTIONS.map((a) => {
            const k = keys[a.id];
            const risky = RISKY[k];
            return (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-3">
                <div className="min-w-0">
                  <p className="font-bold">{t(a.label)}</p>
                  {risky && <p className="flex items-center gap-1 text-xs text-warn"><AlertTriangle className="size-3.5" aria-hidden /> {t(risky)}</p>}
                  {k !== a.default && <p className="text-xs text-soft">{t("ks_default")}: <span dir="ltr">{a.default}</span></p>}
                </div>
                <div className="flex items-center gap-2">
                  <kbd className={cn("min-w-20 rounded-xl border-2 px-3 py-1.5 text-center font-mono font-black", listening === a.id ? "animate-pulse border-brand bg-brandsoft" : "border-line bg-surface2")} dir="ltr">
                    {listening === a.id ? "…" : k}
                  </kbd>
                  <Button variant={listening === a.id ? "soft" : "ghost"} className="min-h-10 px-3" onClick={() => { setMsg(null); setPending(null); setListening(listening === a.id ? null : a.id); }}
                    aria-label={`${t("ks_change")}: ${t(a.label)}`}>{listening === a.id ? t("ks_press") : t("ks_change")}</Button>
                </div>
              </li>
            );
          })}
        </ul>
      </Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-soft">{t("ks_note")}</p>
        <Button variant="ghost" onClick={() => { saveBindings(Object.fromEntries(ACTIONS.map((a) => [a.id, a.default])) as Record<Action, string>); setMsg(null); setPending(null); }}>
          <RotateCcw className="size-4" aria-hidden /> {t("ks_reset")}
        </Button>
      </div>
    </div>
  );
}
