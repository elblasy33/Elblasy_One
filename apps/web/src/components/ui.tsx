"use client";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "soft" | "ghost" | "danger";
const variants: Record<Variant, string> = {
  primary: "bg-brand text-brandink hover:brightness-110 shadow-card",
  soft: "bg-brandsoft text-brand hover:brightness-95",
  ghost: "bg-transparent text-ink hover:bg-surface2",
  danger: "bg-bad text-white hover:brightness-110",
};

export function Button({
  variant = "primary", loading, className, children, disabled, ...p
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      {...p}
      disabled={disabled || loading}
      className={cn(
        "inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl px-5 text-base font-bold transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant], className,
      )}
    >
      {loading && <Loader2 className="size-5 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("rounded-card border border-line bg-surface p-5 shadow-card", className)}>{children}</div>;
}

export function Field({ label, hint, error, ...p }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string }) {
  const id = p.id ?? p.name;
  return (
    <label htmlFor={id} className="block">
      <span className="mb-1.5 block text-sm font-bold">{label}</span>
      <input
        {...p} id={id}
        aria-invalid={!!error}
        className="min-h-12 w-full rounded-2xl border border-line bg-surface px-4 text-base outline-none transition focus:border-brand focus:ring-4 focus:ring-brandsoft"
      />
      {hint && !error && <span className="mt-1 block text-xs text-soft">{hint}</span>}
      {error && <span role="alert" className="mt-1 block text-xs font-bold text-bad">{error}</span>}
    </label>
  );
}

type Tone = "ok" | "warn" | "bad" | "brand" | "neutral";
const tones: Record<Tone, string> = {
  ok: "bg-oksoft text-ok", warn: "bg-warnsoft text-warn", bad: "bg-badsoft text-bad",
  brand: "bg-brandsoft text-brand", neutral: "bg-surface2 text-soft",
};
export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-bold", tones[tone])}>{children}</span>;
}

export function ErrorBox({ message, reference }: { message: string; reference?: string | undefined }) {
  return (
    <div role="alert" className="rounded-2xl border border-bad/30 bg-badsoft p-4 text-sm font-semibold text-bad">
      {message}
      {reference && <span className="mt-1 block text-xs opacity-70" dir="ltr">ref: {reference}</span>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 p-10 text-soft" role="status">
      <Loader2 className="size-6 animate-spin" aria-hidden />
      {label && <span>{label}</span>}
    </div>
  );
}
