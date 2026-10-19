"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { LangProvider } from "@/lib/i18n";
import type { Lang } from "@/lib/types";

export function Providers({ lang, children }: { lang: Lang; children: ReactNode }) {
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
          },
        },
      }),
  );
  return (
    <LangProvider initial={lang}>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </LangProvider>
  );
}
