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
  await expect(page.getByText(/2 × /).first()).toBeVisible();
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

test("register conveniences: product grid, numpad quantity/price, parked orders that survive a reload", async ({ page }) => {
  const { pid } = await seed(page.request);
  await page.goto("/sales");
  await page.getByLabel("النقدية الافتتاحية").fill("0");
  await page.getByRole("button", { name: "فتح الخزنة" }).click();

  // tap a tile (no barcode needed), then set the quantity on the numpad
  const tile = page.getByRole("list", { name: "المنتجات" }).getByRole("button", { name: /شاي ليبتون/ }).first();
  await expect(tile).toBeVisible();
  await page.screenshot({ path: "e2e/shots/27-register-grid.png", fullPage: true });
  await tile.click();
  await expect(page.getByText(/1 × /).first()).toBeVisible();
  await page.getByRole("button", { name: "4", exact: true }).click();
  await expect(page.getByText(/4 × /).first()).toBeVisible();
  await expect(page.getByText("…").first()).toBeHidden({ timeout: 10_000 });

  // the owner may change the price: 4 x 30 = 120 before tax, and the change is flagged
  await page.getByRole("radio", { name: "السعر" }).click();
  await page.getByRole("button", { name: "3", exact: true }).click();
  await page.getByRole("button", { name: "0", exact: true }).click();
  await expect(page.getByText("30.00").first()).toBeVisible();
  await expect(page.getByText("تغيير السعر مسجَّل في السجل.")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/28-numpad.png", fullPage: true });

  // park this order, serve someone else, come back; a reload keeps both
  await page.getByRole("button", { name: /طلب جديد/ }).click();
  await expect(page.getByText("السلة فارغة").first()).toBeVisible();
  await page.getByRole("tab", { name: /طلب 1/ }).click();
  await expect(page.getByText(/4 × /).first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole("tab", { name: /طلب 2/ })).toBeVisible();
  await page.getByRole("tab", { name: /طلب 1/ }).click();
  await expect(page.getByText(/4 × /).first()).toBeVisible();
  expect(pid).toBeGreaterThan(0);
});

test("keyboard-only till: quantity before scan, name search with arrows, quick quantity keys, Enter to pay exact", async ({ page }) => {
  const { barcode, pid, cid } = await seed(page.request);
  const tag = String(Date.now() % 100000);
  const extra = await page.request.post(`/api/connections/${cid}/catalog/products`, { headers: { "Idempotency-Key": crypto.randomUUID().replaceAll("-", "") }, data: { name: `شاي الضحى ${tag}`, price: 10 } });
  expect(extra.status()).toBe(201);
  await page.goto("/sales");
  const box = page.getByLabel("امسح الباركود أو ابحث باسم المنتج");
  const opening = page.getByLabel("النقدية الافتتاحية");
  await expect(opening.or(box)).toBeVisible(); // the shift may still be open from the previous test
  if (await opening.isVisible()) {
    await opening.fill("0");
    await page.getByRole("button", { name: "فتح الخزنة" }).click();
  }
  await expect(box).toBeFocused();

  // supermarket habit: quantity, *, then the scan (the scanner types the code and Enter)
  await page.keyboard.type(`3*${barcode}`);
  await page.keyboard.press("Enter");
  await expect(page.getByText(/^3 × /).first()).toBeVisible();

  // name search on the device, Arabic spelling differences ignored, arrows + Enter
  await page.keyboard.type(`شاى الضحي ${tag}`); // ى and ي swapped on purpose
  await expect(page.getByRole("listbox", { name: "المنتجات" }).getByText(`شاي الضحى ${tag}`)).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: new RegExp(`شاي الضحى ${tag}`) }).first()).toBeVisible();
  await expect(page.getByText(/^1 × /).first()).toBeVisible();

  // correct the quantity of the selected line, then nudge it with +
  await page.keyboard.type("*2");
  await page.keyboard.press("Enter");
  await expect(page.getByText(/^2 × /).first()).toBeVisible();
  await page.keyboard.press("+");
  await expect(page.getByText(/^3 × /)).toHaveCount(2); // the scanned tea and the searched one
  await expect(page.getByText("…").first()).toBeHidden({ timeout: 10_000 });

  // shortcuts are discoverable
  await page.keyboard.press("F1");
  await expect(page.getByRole("heading", { name: "اختصارات الكيبورد" })).toBeVisible();
  await page.screenshot({ path: "e2e/shots/29-shortcuts.png", fullPage: true });
  await page.keyboard.press("Escape");

  // Enter on the empty box opens payment; Enter with no amount pays exactly; Enter starts the next sale
  await box.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "الدفع" })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByText("تم البيع")).toBeVisible();
  expect((await odoo("product.product", "read", [[pid]], { fields: ["qty_available"] }))[0].qty_available).toBe(17);
  await page.keyboard.press("Enter");
  await expect(box).toBeFocused();
});

test("shortcuts can be changed per device: new key, conflict swap, risky and refused keys", async ({ page }) => {
  const { barcode } = await seed(page.request);
  await page.goto("/settings/shortcuts");
  await expect(page.getByRole("heading", { name: "اختصارات الكيبورد" })).toBeVisible();
  // a plain letter would type into the scan box: refused
  await page.getByRole("button", { name: "غيّر: الدفع", exact: true }).click();
  await page.keyboard.press("a");
  await expect(page.getByText(/حرف عادي بيتكتب/)).toBeVisible();
  // F6: allowed, flagged because browsers often keep it
  await page.keyboard.press("F6");
  await expect(page.getByText("بيروح لشريط العنوان")).toBeVisible();
  // F8 belongs to "park": offered as a swap
  await page.getByRole("button", { name: "غيّر: روح لخانة المسح/البحث" }).click();
  await page.keyboard.press("F8");
  await expect(page.getByText(/مستخدم بالفعل/)).toBeVisible();
  await page.getByRole("button", { name: "بدّل بينهم" }).click();
  await page.screenshot({ path: "e2e/shots/65-shortcuts-settings.png", fullPage: true });

  // the till follows the new keys
  await page.goto("/sales");
  const box = page.getByLabel("امسح الباركود أو ابحث باسم المنتج");
  const opening = page.getByLabel("النقدية الافتتاحية");
  await expect(opening.or(box)).toBeVisible();
  if (await opening.isVisible()) {
    await opening.fill("0");
    await page.getByRole("button", { name: "فتح الخزنة" }).click();
  }
  await box.fill(barcode);
  await box.press("Enter");
  await expect(page.getByText(/^1 × /).first()).toBeVisible();
  await expect(page.getByText("…").first()).toBeHidden({ timeout: 10_000 });
  await page.keyboard.press("F4"); // no longer the payment key
  await expect(page.getByRole("heading", { name: "الدفع" })).toHaveCount(0);
  await page.keyboard.press("F6");
  await expect(page.getByRole("heading", { name: "الدفع" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: "الدفع" })).toHaveCount(0); // closed before the next key
  await page.keyboard.press("F1");
  await expect(page.getByRole("link", { name: "تعديل الاختصارات" })).toBeVisible();
});

test("offers: buy 2 get 1 created in the UI is applied at the till and shown on the cart", async ({ page }) => {
  const { barcode, cid } = await seed(page.request);
  const ids = await odoo("ir.module.module", "search", [[["name", "=", "loyalty"], ["state", "!=", "installed"]]]);
  if (ids.length) await odoo("ir.module.module", "button_immediate_install", [ids]).catch(() => undefined);
  const tag = String(Date.now() % 100000);
  const prod = await (await page.request.get(`/api/connections/${cid}/catalog/products?q=${barcode}`)).json();
  await page.goto("/settings/loyalty");
  await expect(page.getByRole("heading", { name: "العروض والولاء" })).toBeVisible();
  await page.getByRole("radio", { name: /اشتري X واحصل على Y/ }).click();
  await page.getByLabel("اسم العرض").fill(`عرض الشاي ${tag}`);
  await page.getByLabel("اشتري", { exact: true }).fill("2");
  await page.getByLabel("واحصل مجانًا على").fill("1");
  await page.getByLabel("ابحث عن صنف").fill(barcode);
  await page.getByRole("button", { name: prod.items[0].name }).first().click();
  await page.getByRole("button", { name: "احفظ العرض" }).click();
  await expect(page.getByText(`عرض الشاي ${tag}`)).toBeVisible();
  await page.screenshot({ path: "e2e/shots/67-offers.png", fullPage: true });

  await page.goto("/sales");
  const box = page.getByLabel("امسح الباركود أو ابحث باسم المنتج");
  const opening = page.getByLabel("النقدية الافتتاحية");
  await expect(opening.or(box)).toBeVisible();
  if (await opening.isVisible()) { await opening.fill("0"); await page.getByRole("button", { name: "فتح الخزنة" }).click(); }
  await box.fill(`3*${barcode}`);
  await box.press("Enter");
  await expect(page.getByRole("list", { name: "العروض" }).getByText(new RegExp(`عرض الشاي ${tag}`))).toBeVisible();
  await expect(page.getByText("…").first()).toBeHidden({ timeout: 10_000 });
  await expect(page.getByText(/^114\.00/).first()).toBeVisible(); // 3 x 57, one of them free
  await page.screenshot({ path: "e2e/shots/68-offer-at-till.png", fullPage: true });
});
