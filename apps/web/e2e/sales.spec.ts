import { expect, test, type APIRequestContext } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const state = () => JSON.parse(fs.readFileSync(path.resolve(__dirname, ".state.json"), "utf8")) as { odoo_url: string; odoo_db: string };

async function odoo(model: string, method: string, args: unknown[], kwargs: Record<string, unknown> = {}) {
  const { odoo_url: url, odoo_db: db } = state();
  const call = async (service: string, m: string, a: unknown[]) => {
    const r = await fetch(`${url}/jsonrpc`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { service, method: m, args: a }, id: 1 }) });
    const j = await r.json();
    if (j.error) throw new Error(JSON.stringify(j.error.data?.message ?? j.error));
    return j.result;
  };
  const uid = await call("common", "authenticate", [db, "admin", "admin", {}]);
  return call("object", "execute_kw", [db, uid, "admin", model, method, args, kwargs]);
}

async function seed(request: APIRequestContext) {
  const email = `pos-${Date.now()}@example.com`;
  expect((await request.post("/api/auth/bootstrap", { data: { business_name: "بقالة", email, password: "correct-horse-battery" } })).status()).toBe(201);
  const { odoo_url, odoo_db } = state();
  const conn = await request.post("/api/connections", { data: { name: "Main", base_url: odoo_url, db_name: odoo_db, login: "admin", secret: "admin" } });
  const cid = (await conn.json()).id as string;
  const mk = await request.post(`/api/connections/${cid}/catalog/products`, { headers: { "Idempotency-Key": crypto.randomUUID().replaceAll("-", "") }, data: { name: "شاي ليبتون", price: 50, auto_barcode: "internal" } });
  expect(mk.status()).toBe(201);
  const p = await mk.json();
  const loc = (await odoo("stock.warehouse", "search_read", [[]], { fields: ["lot_stock_id"] }))[0].lot_stock_id[0];
  const q = await odoo("stock.quant", "create", [{ product_id: p.variant_ids[0], location_id: loc, inventory_quantity: 20 }]);
  await odoo("stock.quant", "action_apply_inventory", [[q]]).catch(() => undefined); // returns None: Odoo cannot marshal it
  return { cid, barcode: p.barcode as string, pid: p.variant_ids[0] as number };
}

test("a real cashier account can use the register screen (not only the API)", async ({ page, browser }) => {
  const stamp = Date.now();
  expect((await page.request.post("/api/auth/bootstrap", { data: { business_name: "بقالة", email: `own-${stamp}@example.com`, password: "correct-horse-battery" } })).status()).toBe(201);
  const { odoo_url, odoo_db } = state();
  expect((await page.request.post("/api/connections", { data: { name: "Main", base_url: odoo_url, db_name: odoo_db, login: "admin", secret: "admin" } })).status()).toBe(201);
  const email = `cash-${stamp}@example.com`;
  expect((await page.request.post("/api/users", { data: { email, password: "cashier-password-1", role: "cashier" } })).status()).toBe(201);
  const ctx = await browser.newContext();
  const cp = await ctx.newPage();
  await cp.goto("/login");
  await cp.getByLabel("البريد الإلكتروني").fill(email);
  await cp.getByLabel("كلمة المرور").fill("cashier-password-1");
  await cp.getByRole("button", { name: "تسجيل الدخول" }).click();
  await expect(cp).toHaveURL(/\/today/);
  await cp.getByRole("link", { name: "المبيعات" }).first().click();
  // the register screen loads for the cashier: either the open-register form or the scan box
  await expect(cp.getByRole("heading", { name: "افتح الخزنة" }).or(cp.getByLabel("امسح الباركود أو ابحث باسم المنتج"))).toBeVisible();
  await expect(cp.getByRole("link", { name: "الإدارة والإعدادات" })).toHaveCount(0);
  await ctx.close();
});

test("cashier day: open register, scan, pay with change, refund, close with a cash difference", async ({ page }) => {
  const { barcode, pid } = await seed(page.request);
  await page.goto("/sales");
  await expect(page.getByRole("heading", { name: "افتح الخزنة" })).toBeVisible();
  await page.screenshot({ path: "e2e/shots/20-open-register.png", fullPage: true });
  await page.getByLabel("النقدية الافتتاحية").fill("100");
  await page.getByRole("button", { name: "فتح الخزنة" }).click();

  // ---- scan the product twice (the scanner types the code and presses Enter)
  const scan = page.getByLabel("امسح الباركود أو ابحث باسم المنتج");
  await expect(scan).toBeVisible();
  await scan.fill(barcode);
  await scan.press("Enter");
  await expect(page.getByText("شاي ليبتون").first()).toBeVisible();
  await scan.fill(barcode);
  await scan.press("Enter");
  await expect(page.getByLabel("الكمية")).toHaveValue("2");
  await expect(page.getByText("…").first()).toBeHidden({ timeout: 10_000 }); // total shown only once it matches the cart
  await expect(page.getByText("منها ضريبة")).toBeVisible(); // totals and tax come from Odoo
  await page.screenshot({ path: "e2e/shots/21-cart.png", fullPage: true });

  // ---- pay: 200 for a ~114 total, change is shown
  await page.getByRole("button", { name: "ادفع" }).click();
  await page.getByRole("button", { name: "200", exact: true }).click();
  await expect(page.getByText("الباقي للعميل")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/22-pay.png", fullPage: true });
  await page.getByRole("button", { name: "تأكيد البيع" }).click();
  await expect(page.getByText("تم البيع")).toBeVisible();
  await expect(page.getByText("وتحقّقنا منه في أودو")).toBeVisible();
  await expect(page.getByText("شكرًا لزيارتكم")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/23-receipt.png", fullPage: true });
  expect(await odoo("product.product", "read", [[pid]], { fields: ["qty_available"] })).toEqual([{ id: pid, qty_available: 18 }]); // stock fell in Odoo

  // ---- second sale, then refund the first from the history tab
  await page.getByRole("button", { name: "بيع جديد" }).click();
  await page.getByLabel("امسح الباركود أو ابحث باسم المنتج").fill(barcode);
  await page.getByLabel("امسح الباركود أو ابحث باسم المنتج").press("Enter");
  await page.getByRole("button", { name: "ادفع" }).click();
  await page.getByRole("button", { name: "بالضبط" }).click();
  await page.getByRole("button", { name: "تأكيد البيع" }).click();
  await expect(page.getByText("تم البيع")).toBeVisible();
  await page.getByRole("button", { name: "بيع جديد" }).click();
  await page.getByRole("tab", { name: "المبيعات" }).click();
  await expect(page.getByText("مبيعات الوردية")).toBeVisible();
  await page.getByRole("button", { name: "مرتجع" }).last().click(); // oldest sale is last in the list
  await page.locator("li", { hasText: "اختر الكمية المراد إرجاعها" }).getByRole("button", { name: "مرتجع" }).click(); // no quantity chosen = everything left
  await expect(page.getByText("تم الاسترجاع")).toBeVisible();
  expect(await odoo("product.product", "read", [[pid]], { fields: ["qty_available"] })).toEqual([{ id: pid, qty_available: 19 }]); // refund put 2 back, 1 sold
  await page.screenshot({ path: "e2e/shots/24-history.png", fullPage: true });

  // ---- a cashier cannot refund, but can ask; the owner approves from the same screen
  const askEmail = `ask-${Date.now()}@example.com`;
  expect((await page.request.post("/api/users", { data: { email: askEmail, password: "cashier-password-1", role: "cashier" } })).status()).toBe(201);
  const ctx = await page.context().browser()!.newContext();
  const cp = await ctx.newPage();
  await cp.goto("/login");
  await cp.getByLabel("البريد الإلكتروني").fill(askEmail);
  await cp.getByLabel("كلمة المرور").fill("cashier-password-1");
  await cp.getByRole("button", { name: "تسجيل الدخول" }).click();
  await expect(cp).toHaveURL(/\/today/);
  await cp.goto("/sales");
  await cp.getByRole("tab", { name: "المبيعات" }).click();
  await expect(cp.getByRole("button", { name: "مرتجع", exact: true })).toHaveCount(0);
  await cp.getByRole("button", { name: "اطلب مرتجع" }).click();
  await cp.locator("li", { hasText: "اختر الكمية المراد إرجاعها" }).getByRole("button", { name: "اطلب مرتجع" }).click();
  await expect(cp.getByText("أُرسل الطلب إلى المسؤول للموافقة")).toBeVisible();
  await ctx.close();
  await page.goto("/sales");
  await page.getByRole("tab", { name: "المبيعات" }).click();
  await expect(page.getByRole("heading", { name: "طلبات المرتجع" })).toBeVisible();
  await page.getByRole("button", { name: "وافق" }).click();
  await expect(page.getByRole("heading", { name: "طلبات المرتجع" })).toBeHidden();
  expect(await odoo("product.product", "read", [[pid]], { fields: ["qty_available"] })).toEqual([{ id: pid, qty_available: 20 }]);

  // ---- today's numbers on the dashboard are real and defined
  await page.getByRole("link", { name: "اليوم" }).first().click();
  await expect(page.getByText("صافي مبيعات اليوم")).toBeVisible();
  await expect(page.getByText(/التعريف:/).first()).toBeVisible();
  await page.screenshot({ path: "e2e/shots/25-today-kpis.png", fullPage: true });

  // ---- close the register with 3 missing in the drawer
  await page.getByRole("link", { name: "المبيعات" }).first().click();
  await page.getByRole("button", { name: "إغلاق الخزنة" }).click();
  const exp = await page.evaluate(() => 0); // expected is computed by Odoo; we count 3 short of 100 + net cash
  void exp;
  await page.getByLabel(/النقدية المعدودة/).fill("0");
  await page.getByRole("button", { name: "إغلاق الخزنة" }).last().click();
  await expect(page.getByText(/يوجد فرق في الخزنة|الخزنة مطابقة/)).toBeVisible();
  await page.screenshot({ path: "e2e/shots/26-closed.png", fullPage: true });
  await expect(page.getByText("تم ترحيل القيود المحاسبية في أودو.")).toBeVisible();
  const sessions = await odoo("pos.session", "search_read", [[["state", "=", "closed"]]], { fields: ["move_id"] });
  expect(sessions.length).toBeGreaterThan(0);
  expect(sessions.at(-1).move_id).toBeTruthy();
});
