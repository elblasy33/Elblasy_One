import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const state = () => JSON.parse(fs.readFileSync(path.resolve(__dirname, ".state.json"), "utf8")) as { odoo_url: string; odoo_db: string };

async function seed(request: import("@playwright/test").APIRequestContext) {
  const stamp = Date.now();
  const email = `adm-${stamp}@example.com`;
  expect((await request.post("/api/auth/bootstrap", { data: { business_name: "بقالة", email, password: "correct-horse-battery" } })).status()).toBe(201);
  const { odoo_url, odoo_db } = state();
  const conn = await request.post("/api/connections", { data: { name: "Main", base_url: odoo_url, db_name: odoo_db, login: "admin", secret: "admin" } });
  return { stamp, email, cid: (await conn.json()).id as string };
}

test("users: owner creates a cashier with a temporary password, who must change it; role changes end sessions", async ({ page, browser }) => {
  const { stamp } = await seed(page.request);
  const cashier = `new-${stamp}@example.com`;

  await page.goto("/settings/users");
  await page.getByRole("button", { name: "مستخدم جديد" }).click();
  await page.getByLabel("البريد الإلكتروني", { exact: true }).fill(cashier);
  await page.getByLabel("الاسم (اختياري)").fill("سعاد الكاشير");
  await page.getByLabel("كلمة مرور مؤقتة").fill("temporary-pass-12");
  await page.getByRole("button", { name: "إنشاء المستخدم" }).click();
  await expect(page.getByText("سعاد الكاشير")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/60-users.png", fullPage: true });

  // the new user is forced to pick their own password before anything else
  const ctx = await browser.newContext();
  const cp = await ctx.newPage();
  await cp.goto("/login");
  await cp.getByLabel("البريد الإلكتروني").fill(cashier);
  await cp.getByLabel("كلمة المرور").fill("temporary-pass-12");
  await cp.getByRole("button", { name: "تسجيل الدخول" }).click();
  await expect(cp).toHaveURL(/settings\/account/);
  await expect(cp.getByText("عليك اختيار كلمة مرور جديدة قبل المتابعة.")).toBeVisible();
  await cp.getByLabel("كلمة المرور الحالية").fill("temporary-pass-12");
  await cp.getByLabel("كلمة المرور الجديدة").fill("my-own-secret-77");
  await cp.getByRole("button", { name: "غيّر كلمة المرور" }).click();
  await expect(cp.getByText(/تم تغيير كلمة المرور/)).toBeVisible();
  await cp.goto("/sales");
  await expect(cp).toHaveURL(/\/sales/);

  // the owner promotes them; their open session is ended immediately
  await page.goto("/settings/users");
  await page.locator("li", { hasText: "سعاد الكاشير" }).getByRole("button", { name: "تعديل" }).click();
  await page.locator("dialog select").selectOption({ label: "المدير" });
  await page.locator("dialog").getByRole("button", { name: "حفظ" }).first().click();
  await expect(page.locator("li", { hasText: "سعاد الكاشير" }).getByText("المدير")).toBeVisible();
  await cp.reload();
  await expect(cp).toHaveURL(/\/login/);
  await ctx.close();
});

test("audit log, operations, readiness details and alerts are visible to the owner", async ({ page }) => {
  const { cid } = await seed(page.request);
  await page.request.post("/api/users", { data: { email: `a-${Date.now()}@example.com`, password: "account-password-1", role: "cashier" } });

  await page.goto("/settings/audit");
  await expect(page.getByRole("heading", { name: "السجل والعمليات" })).toBeVisible();
  await expect(page.getByText("user.create").first()).toBeVisible();
  await page.getByPlaceholder("ابدأ بـ (مثل stock.)").fill("user.");
  await expect(page.getByText("tenant.bootstrap")).toBeHidden();
  await expect(page.getByRole("link", { name: "تصدير CSV" })).toHaveAttribute("href", /\/api\/audit\/export/);
  await page.screenshot({ path: "e2e/shots/61-audit.png", fullPage: true });
  await page.getByRole("tab", { name: "العمليات" }).click();
  await expect(page.getByText(/لا سجلات|catalog|sales|stock/).first()).toBeVisible();

  await page.goto("/settings/readiness");
  await expect(page.getByRole("heading", { name: "جاهزية النظام" })).toBeVisible();
  await expect(page.getByText("نوع البيئة:")).toBeVisible();
  await expect(page.getByText(/لا مشاكل مانعة|توجد مشاكل مانعة/)).toBeVisible();
  await page.screenshot({ path: "e2e/shots/62-readiness.png", fullPage: true });
  expect((await page.request.get(`/api/connections/${cid}/readiness`)).status()).toBe(200);

  await page.goto("/today");
  await expect(page.getByRole("heading", { name: "تنبيهات تحتاج انتباهك" })).toBeVisible();
  await expect(page.getByText("مبيعات آخر ٧ أيام")).toBeVisible();
  await expect(page.getByText("الأكثر مبيعًا")).toBeVisible();
  // purchases has its own place in the menu; the menu folds to icons to give the page more room
  const nav = page.getByRole("navigation", { name: "القائمة الرئيسية" }).first();
  await expect(nav.getByRole("link", { name: "المشتريات" })).toBeVisible();
  const before = (await page.locator("aside").boundingBox())!.width;
  await page.getByRole("button", { name: "طيّ القائمة" }).click();
  await expect.poll(async () => (await page.locator("aside").boundingBox())!.width).toBeLessThan(before - 80);
  await expect(page.getByRole("link", { name: "المشتريات" }).first()).toBeVisible(); // still reachable by icon
  await page.reload();
  await expect(page.getByRole("button", { name: "فتح القائمة" })).toBeVisible(); // remembered
  await page.getByRole("button", { name: "فتح القائمة" }).click();
  await page.screenshot({ path: "e2e/shots/63-today-alerts.png", fullPage: true });
});

test("the UI explains a service that this Odoo does not have instead of failing", async ({ page }) => {
  await seed(page.request);
  await page.route("**/api/connections/current", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({ response: res, json: { ...body, capabilities: { ...body.capabilities, purchase: false } } });
  });
  await page.goto("/inventory/suppliers");
  await expect(page.getByText("هذه الخدمة غير مفعّلة في أودو")).toBeVisible();
  await expect(page.getByRole("link", { name: "افتح الإعداد" })).toBeVisible();
  await page.screenshot({ path: "e2e/shots/64-capability-off.png", fullPage: true });
});
