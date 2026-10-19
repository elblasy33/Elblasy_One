import { expect, test } from "@playwright/test";
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
const qty = async (pid: number) => (await odoo("product.product", "read", [[pid]], { fields: ["qty_available"] }))[0].qty_available as number;

test("stock: count with a reason, minimum and suggestions, approval of a large adjustment, opening balance", async ({ page, browser }) => {
  const stamp = Date.now();
  const owner = `stk-${stamp}@example.com`;
  expect((await page.request.post("/api/auth/bootstrap", { data: { business_name: "بقالة", email: owner, password: "correct-horse-battery" } })).status()).toBe(201);
  const { odoo_url, odoo_db } = state();
  const cid = (await (await page.request.post("/api/connections", { data: { name: "Main", base_url: odoo_url, db_name: odoo_db, login: "admin", secret: "admin" } })).json()).id as string;
  const mk = async (name: string, extra: Record<string, unknown> = {}) => {
    const r = await page.request.post(`/api/connections/${cid}/catalog/products`, { headers: { "Idempotency-Key": crypto.randomUUID().replaceAll("-", "") }, data: { name, price: 40, cost: 20, ...extra } });
    return (await r.json()) as { variant_ids: number[]; barcode?: string };
  };
  const tea = await mk(`شاي ستوك ${stamp % 1000}`);
  const pid = tea.variant_ids[0]!;
  const teaName = `شاي ستوك ${stamp % 1000}`;

  // ---- a count with a recorded reason
  await page.goto("/inventory/stock/count");
  await page.getByLabel("ابحث عن صنف لجرده").fill(teaName);
  await page.getByRole("button", { name: new RegExp(teaName) }).click();
  await page.getByLabel("المعدود").fill("12");
  await page.getByLabel("السبب").selectOption({ label: "وُجدت زيادة" });
  await page.screenshot({ path: "e2e/shots/40-count.png", fullPage: true });
  await page.getByRole("button", { name: "طبّق التسوية" }).click();
  await expect(page.getByText("تم تطبيق التسوية وتحقّقنا منها في أودو")).toBeVisible();
  expect(await qty(pid)).toBe(12);
  const refs = (await odoo("stock.move", "search_read", [[["product_id", "=", pid]]], { fields: ["reference"] })).map((m: { reference: string }) => m.reference);
  expect(refs.some((r: string) => r.includes("found"))).toBe(true); // the reason is stored on the Odoo stock move

  // ---- minimum + suggestion (a recommendation, not an order)
  await page.goto("/inventory/stock");
  await page.getByLabel(`الحد الأدنى ${teaName}`).fill("20");
  const card = page.locator("li", { hasText: teaName }).filter({ has: page.getByLabel(`الحد الأدنى ${teaName}`) });
  await card.getByRole("button", { name: "حفظ" }).click();
  await expect(card.getByText("ناقص", { exact: true })).toBeVisible();
  await expect(page.getByText("هذه توصيات وليست طلبات شراء")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/41-stock-low.png", fullPage: true });
  expect(await odoo("purchase.order", "search_count", [[["order_line.product_id", "=", pid]]])).toBe(0);
  await page.getByRole("button", { name: "جهّز أمر شراء من الاقتراحات" }).click();
  await expect(page).toHaveURL(/purchases\/new/);
  await expect(page.getByText(teaName)).toBeVisible();
  await expect(page.getByRole("button", { name: "تأكيد أمر الشراء" })).toBeDisabled(); // a draft: no supplier chosen, nothing ordered
  expect(await odoo("purchase.order", "search_count", [[["order_line.product_id", "=", pid]]])).toBe(0);

  // ---- a clerk's large adjustment waits for the owner
  const clerk = `clerk-${stamp}@example.com`;
  expect((await page.request.post("/api/users", { data: { email: clerk, password: "clerk-password-123", role: "inventory_operator" } })).status()).toBe(201);
  const ctx = await browser.newContext();
  const cp = await ctx.newPage();
  await cp.goto("/login");
  await cp.getByLabel("البريد الإلكتروني").fill(clerk);
  await cp.getByLabel("كلمة المرور").fill("clerk-password-123");
  await cp.getByRole("button", { name: "تسجيل الدخول" }).click();
  await expect(cp).toHaveURL(/\/today/);
  await cp.goto("/inventory/stock/count");
  await cp.getByLabel("ابحث عن صنف لجرده").fill(teaName);
  await cp.getByRole("button", { name: new RegExp(teaName) }).click();
  await cp.getByLabel("المعدود").fill("5000");
  await cp.getByRole("button", { name: "طبّق التسوية" }).click();
  await expect(cp.getByText(/أُرسلت للموافقة/)).toBeVisible();
  expect(await qty(pid)).toBe(12); // nothing moved
  await ctx.close();

  await page.goto("/inventory/stock");
  await expect(page.getByText("تسويات بانتظار الموافقة")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/42-pending.png", fullPage: true });
  await page.getByRole("button", { name: "وافق" }).first().click();
  await expect.poll(() => qty(pid), { timeout: 20_000 }).toBe(5000);
  await expect(page.getByText("تسويات بانتظار الموافقة")).toBeHidden();

  // ---- opening balance: validated first, posted only by the owner
  const a = await mk(`رصيد ${stamp % 1000}`, { auto_barcode: "internal" });
  const csv = `barcode,qty,unit_cost\n${a.barcode},30,12.5\n9999999999999,4,1\n`;
  await page.goto("/inventory/stock/opening");
  await page.getByLabel("أو الصق المحتوى هنا").fill(csv);
  await page.getByRole("button", { name: "راجع الملف" }).click();
  await expect(page.getByText("✓ 1 سليمة")).toBeVisible();
  await expect(page.getByText("no stocked product has this barcode")).toBeVisible();
  expect(await qty(a.variant_ids[0]!)).toBe(0); // checking posted nothing
  await page.screenshot({ path: "e2e/shots/43-opening-check.png", fullPage: true });
  await page.getByRole("button", { name: /رحّل الرصيد الافتتاحي/ }).click();
  await expect(page.getByText("تم ترحيل الرصيد الافتتاحي")).toBeVisible();
  expect(await qty(a.variant_ids[0]!)).toBe(30);
});
