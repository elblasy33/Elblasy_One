import type { NextConfig } from "next";

// The browser only ever talks to this origin. /api/* is proxied to the platform API,
// so the httpOnly session cookie stays same-site and Odoo is never reachable from the client.
const API = process.env.ELBLASY_API_URL ?? "http://localhost:8000";

const config: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/:path*` }];
  },
};
export default config;
