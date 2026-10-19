import type { NextConfig } from "next";

// The browser only ever talks to this origin. /api/* is proxied to the platform API,
// so the httpOnly session cookie stays same-site and Odoo is never reachable from the client.
const API = process.env.ELBLASY_API_URL ?? "http://localhost:8000";
const dev = process.env.NODE_ENV !== "production";

// Content-Security-Policy. Next.js bootstraps pages with inline scripts, so 'unsafe-inline' is still
// needed for scripts until a nonce-based policy is added (see docs/adr/0005-csp.md); every other
// directive is strict: no plugins, no framing, same-origin connections and forms only.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'" + (dev ? " ws: wss:" : ""),
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  ...(dev ? [] : [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]),
];

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/:path*` }];
  },
};
export default config;
