"use client";
import { Hourglass, Star, TimerOff } from "lucide-react";
import { Badge, Card } from "@/components/ui";
import { money } from "@/components/receipt";
import { useLang } from "@/lib/i18n";
import { useInsights } from "@/lib/queries";

/** A week of sales as plain bars (no chart library), best sellers, idle stock and goods near expiry. */
export function Insights({ cid }: { cid: string }) {
  const { t, lang } = useLang();
  const q = useInsights(cid);
  const d = q.data;
  if (!d) return null;
  const max = Math.max(1, ...d.sales_by_day.map((x) => x.net));
  const weekday = (iso: string) => new Intl.DateTimeFormat(lang === "ar" ? "ar-EG" : "en", { weekday: "short" }).format(new Date(`${iso}T12:00:00`));
  return (
    <section className="grid gap-4 md:grid-cols-2" aria-label={t("ins_title")}>
      <Card className="space-y-3 md:col-span-2">
        <div className="flex items-baseline justify-between"><h2 className="text-lg font-black">{t("ins_week")}</h2><span className="text-xs text-soft">{t("ins_week_def")}</span></div>
        <div className="flex h-32 items-end gap-2" role="img" aria-label={t("ins_week")}>
          {d.sales_by_day.map((x) => (
            <div key={x.day} className="flex flex-1 flex-col items-center gap-1">
              <span className="text-[10px] font-bold text-soft" dir="ltr">{x.net ? money(x.net, 0) : ""}</span>
              <div className="w-full rounded-t-lg bg-brand/80" style={{ height: `${Math.max(2, (Math.max(0, x.net) / max) * 80)}px` }} />
              <span className="text-[10px] text-soft">{weekday(x.day)}</span>
            </div>
          ))}
        </div>
      </Card>
      <Card className="space-y-2">
        <h2 className="flex items-center gap-2 text-lg font-black"><Star className="size-5 text-brand" aria-hidden /> {t("ins_top")}</h2>
        {d.top_products.length === 0 ? <p className="text-sm text-soft">{t("ins_none")}</p> : (
          <ul className="divide-y divide-line">{d.top_products.map((p) => <li key={p.name} className="flex justify-between py-2"><span dir="auto">{p.name}</span><span className="font-black" dir="ltr">{p.qty} · {money(p.amount)}</span></li>)}</ul>
        )}
      </Card>
      {d.slow_moving && (
        <Card className="space-y-2">
          <h2 className="flex items-center gap-2 text-lg font-black"><TimerOff className="size-5 text-warn" aria-hidden /> {t("ins_slow")} <Badge>{d.slow_moving.count}</Badge></h2>
          <p className="text-xs text-soft">{t("ins_slow_def")}</p>
          {d.slow_moving.items.length === 0 ? <p className="text-sm text-soft">{t("ins_none")}</p> : (
            <ul className="divide-y divide-line">{d.slow_moving.items.map((p) => <li key={p.product_id} className="flex justify-between py-2"><span dir="auto">{p.name}</span><span className="font-black" dir="ltr">{p.qty}{p.value ? ` · ${money(p.value)}` : ""}</span></li>)}</ul>
          )}
        </Card>
      )}
      {d.expiring && d.expiring.count > 0 && (
        <Card className="space-y-2 md:col-span-2">
          <h2 className="flex items-center gap-2 text-lg font-black"><Hourglass className="size-5 text-bad" aria-hidden /> {t("ins_expiring")} <Badge tone="warn">{d.expiring.count}</Badge></h2>
          <ul className="divide-y divide-line">{d.expiring.items.map((x) => <li key={`${x.product}-${x.lot}`} className="flex justify-between py-2"><span dir="auto">{x.product} <span className="text-xs text-soft" dir="ltr">({x.lot})</span></span><span className={x.expired ? "font-black text-bad" : "font-black"} dir="ltr">{x.qty} · {x.expires}</span></li>)}</ul>
        </Card>
      )}
    </section>
  );
}
