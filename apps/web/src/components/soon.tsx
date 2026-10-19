"use client";
import { Hammer } from "lucide-react";
import { Card } from "@/components/ui";
import { useLang, type TKey } from "@/lib/i18n";

export function Soon({ title, what }: { title: TKey; what: TKey }) {
  const { t } = useLang();
  return (
    <div className="rise space-y-6">
      <h1 className="text-3xl font-black">{t(title)}</h1>
      <Card className="flex flex-col items-center gap-3 py-14 text-center">
        <div className="grid size-16 place-items-center rounded-3xl bg-accentsoft text-accent"><Hammer className="size-8" aria-hidden /></div>
        <h2 className="text-xl font-black">{t("soon_title")}</h2>
        <p className="font-bold">{t(what)}</p>
        <p className="max-w-sm text-sm text-soft">{t("soon_sub")}</p>
      </Card>
    </div>
  );
}
