import type { Metadata, Viewport } from "next";
import { Cairo } from "next/font/google";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
import type { Lang } from "@/lib/types";
import "./globals.css";

const cairo = Cairo({ subsets: ["arabic", "latin"], variable: "--font-cairo", display: "swap" });

export const metadata: Metadata = { title: "البلاسي ون · Elblasy One", description: "Simple shop management on Odoo" };
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default async function RootLayout({ children }: { children: ReactNode }) {
  const lang: Lang = (await cookies()).get("lang")?.value === "en" ? "en" : "ar";
  return (
    <html lang={lang} dir={lang === "ar" ? "rtl" : "ltr"} className={cairo.variable}>
      <body className="min-h-dvh antialiased">
        <Providers lang={lang}>{children}</Providers>
      </body>
    </html>
  );
}
