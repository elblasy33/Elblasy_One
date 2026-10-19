"use client";
import { Languages, Store } from "lucide-react";
import type { ReactNode } from "react";
import { useLang } from "@/lib/i18n";

export function AuthShell({ title, children }: { title: string; children: ReactNode }) {
  const { t, lang, setLang } = useLang();
  return (
    <main className="mx-auto grid min-h-dvh w-full max-w-5xl items-center gap-8 px-4 py-8 md:grid-cols-2">
      <section className="rise space-y-4 text-center md:text-start">
        <div className="mx-auto grid size-16 place-items-center rounded-3xl bg-brand text-brandink shadow-card md:mx-0">
          <Store className="size-8" aria-hidden />
        </div>
        <h1 className="text-4xl font-black leading-tight">{t("app")}</h1>
        <p className="text-lg text-soft">{t("tagline")}</p>
        <button onClick={() => setLang(lang === "ar" ? "en" : "ar")} className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-bold text-soft hover:bg-surface2">
          <Languages className="size-4" aria-hidden /> {t("lang_switch")}
        </button>
      </section>
      <section className="rise rounded-[1.75rem] border border-line bg-surface p-6 shadow-card sm:p-8">
        <h2 className="mb-5 text-2xl font-black">{title}</h2>
        {children}
      </section>
    </main>
  );
}
