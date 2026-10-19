"use client";
import { useLang } from "@/lib/i18n";
import type { Receipt as ReceiptData } from "@/lib/types";

export const money = (n: number, dec = 2) => n.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });

export function Receipt({ r, currency }: { r: ReceiptData; currency: string }) {
  const { t } = useLang();
  return (
    <div className="receipt mx-auto w-full max-w-xs rounded-2xl border border-line bg-white p-4 text-sm text-black shadow-card">
      <p className="text-center text-lg font-black">{r.company ?? t("app")}</p>
      <p className="mt-1 text-center text-xs" dir="ltr">{r.date}</p>
      <p className="text-center text-xs">{t("rcpt_ref")}: <span dir="ltr">{r.reference}</span></p>
      <p className="text-center text-xs">{t("rcpt_cashier")}: <span dir="ltr">{r.cashier}</span></p>
      <hr className="my-2 border-dashed border-black/40" />
      <ul className="space-y-1">
        {r.lines.map((l, i) => (
          <li key={i} className="flex justify-between gap-2">
            <span><span dir="ltr" className="text-xs">{l.qty} ×</span> <span dir="auto">{l.name}</span></span>
            <span dir="ltr">{money(l.subtotal_incl)}</span>
          </li>
        ))}
      </ul>
      <hr className="my-2 border-dashed border-black/40" />
      <p className="flex justify-between text-base font-black"><span>{t("pos_total")}</span><span dir="ltr">{money(r.total)} {currency}</span></p>
      <p className="flex justify-between text-xs"><span>{t("pos_tax")}</span><span dir="ltr">{money(r.tax)}</span></p>
      {r.payments.map((p, i) => <p key={i} className="flex justify-between"><span>{p.method}</span><span dir="ltr">{money(p.amount)}</span></p>)}
      <p className="flex justify-between"><span>{t("rcpt_paid")}</span><span dir="ltr">{money(r.paid)}</span></p>
      <p className="flex justify-between font-bold"><span>{t("rcpt_change")}</span><span dir="ltr">{money(r.change)}</span></p>
      <p className="mt-3 text-center text-xs">{t("rcpt_thanks")}</p>
    </div>
  );
}
