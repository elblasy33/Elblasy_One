import { expect, test } from "@playwright/test";

test("a cashier sees only what the server lets them do", async ({ page, browser }) => {
  const owner = `o-${Date.now()}@example.com`;
  const cashier = `c-${Date.now()}@example.com`;
  const pw = "correct-horse-battery";
  const r = await page.request.post("/api/auth/bootstrap", { data: { business_name: "T", email: owner, password: pw } });
  expect(r.status()).toBe(201);
  expect((await page.request.post("/api/users", { data: { email: cashier, password: pw, role: "cashier" } })).status()).toBe(201);

  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  await p.goto("/login");
  await p.getByLabel("البريد الإلكتروني").fill(cashier);
  await p.getByLabel("كلمة المرور").fill(pw);
  await p.getByRole("button", { name: "تسجيل الدخول" }).click();
  await expect(p).toHaveURL(/\/today/);
  const nav = p.getByRole("navigation", { name: "القائمة الرئيسية" }).first();
  await expect(nav.getByRole("link", { name: "المبيعات" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "الإدارة والإعدادات" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "المخزون" })).toHaveCount(0);
  // hiding the menu is cosmetic: the API itself refuses
  expect((await p.request.get("/api/connections")).status()).toBe(403);
  await ctx.close();
});


test("pages ship strict security headers and run without CSP violations", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", (m) => { if (/Content Security Policy|Refused to/i.test(m.text())) violations.push(m.text()); });
  const res = await page.goto("/login");
  const h = res!.headers();
  expect(h["x-frame-options"]).toBe("DENY");
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["referrer-policy"]).toBe("no-referrer");
  expect(h["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(h["content-security-policy"]).toContain("object-src 'none'");
  await expect(page.getByRole("button", { name: "تسجيل الدخول" })).toBeVisible();
  expect(violations).toEqual([]);
  const api = await page.request.get("/api/healthz");
  expect(api.headers()["x-content-type-options"]).toBe("nosniff");
  expect(api.headers()["cache-control"]).toBe("no-store");
});
