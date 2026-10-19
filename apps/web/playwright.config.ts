import { defineConfig, devices } from "@playwright/test";

const API_ENV = {
  ELBLASY_DATABASE_URL: "postgresql+psycopg://elblasy:elblasy@localhost:5433/elblasy_e2e",
  ELBLASY_JWT_SECRET: "e2e-jwt-secret-0123456789-0123456789",
  ELBLASY_SECRET_KEYS: "Ga3C7qH0wq9e8o6dK5u2tY1xV4nB7mZ0cL3jR6sP9aE=",
  ELBLASY_ENVIRONMENT: "test",
  ELBLASY_COOKIE_SECURE: "false",
  ELBLASY_ALLOW_PRIVATE_ODOO_HOSTS: "true",
  ELBLASY_ALLOW_INSECURE_ODOO_HTTP: "true",
};

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  workers: 1,
  fullyParallel: false,
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  reporter: [["list"]],
  use: { baseURL: "http://localhost:3100", locale: "ar-EG", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /(responsive|catalog|sales|purchasing|stock)\.spec\.ts/ },
    // runs after onboarding, which installs manufacturing and creates the POS in the shared Odoo copy
    { name: "stock", use: { ...devices["Desktop Chrome"] }, testMatch: /stock\.spec\.ts/, dependencies: ["purchasing"] },
    { name: "purchasing", use: { ...devices["Desktop Chrome"] }, testMatch: /purchasing\.spec\.ts/, dependencies: ["sales"] },
    { name: "sales", use: { ...devices["Desktop Chrome"] }, testMatch: /sales\.spec\.ts/, dependencies: ["catalog"] },
    { name: "catalog", use: { ...devices["Desktop Chrome"] }, testMatch: /catalog\.spec\.ts/, dependencies: ["desktop"] },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /responsive\.spec\.ts/ },
    
  ],
  webServer: [
    {
      command: "uv run uvicorn elblasy_api.main:app --port 8100",
      cwd: "../../services/api",
      url: "http://localhost:8100/healthz",
      env: API_ENV,
      reuseExistingServer: false,
    },
    {
      command: "pnpm build && pnpm exec next start -p 3100",
      url: "http://localhost:3100/login",
      env: { ELBLASY_API_URL: "http://localhost:8100" },
      timeout: 240_000,
      reuseExistingServer: false,
    },
  ],
});
