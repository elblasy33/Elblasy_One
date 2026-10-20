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

test("wholesale order on credit: customer, price per line, deliver, invoice, owed shows up", async ({ page }) => {
  const email = `so-${Date.now()}@example.com`;
  expect((await page.request.post("/api/auth/bootstrap", { data: { business_name: "جملة", email, password: "correct-horse-battery" } })).status()).toBe(201);
  const { odoo_url, odoo_db } = state();
  const cid = (await (await page.request.post("/api/connections", { data: { name: "Main", base_url: odoo_url, db_name: odoo_db, login: "admin", secret: "admin" } })).json()).id as string;
  const mk = await page.request.post(`/api/connections/${cid}/catalog/products`, { headers: { "Idempotency-Key": crypto.randomUUID().replaceAll("-", "") }, data: { name: "سكر الجملة", price: 100 } });
  const pid = (await mk.json()).variant_ids[0] as number;
  const loc = (await odoo("stock.warehouse", "search_read", [[]], { fields: ["lot_stock_id"] }))[0].lot_stock_id[0];
  const q = await odoo("stock.quant", "create", [{ product_id: pid, location_id: loc, inventory_quantity: 20 }]);
  await odoo("stock.quant", "action_apply_inventory", [[q]]).catch(() => undefined);

  await page.goto("/sales-orders");
  await expect(page.getByRole("heading", { name: "أوامر البيع" })).toBeVisible();
  await page.getByRole("link", { name: "أمر بيع جديد" }).click();
  await page.getByRole("button", { name: "اختر العميل" }).click();
  await page.getByRole("button", { name: "عميل جديد" }).click();
  await page.getByLabel("اسم العميل").fill("تاجر الجملة");
  await page.getByRole("button", { name: "حفظ العميل" }).click();
  await expect(page.getByRole("button", { name: /تاجر الجملة/ })).toBeVisible();

  await page.getByLabel("ابحث عن منتج للشراء").fill("سكر");
  await page.getByRole("button", { name: /سكر الجملة/ }).click();
  await page.getByLabel("الكمية", { exact: true }).fill("5");
  await page.getByLabel("سعر الوحدة").fill("60"); // wholesale, not the shelf price of 100
  await expect(page.getByText(/^300(\.00)?$/).first()).toBeVisible();
  await page.getByLabel("سلّم البضاعة الآن (تخرج من المخزون)").uncheck(); // do the steps one by one this time
  await page.getByLabel("أصدر فاتورة الآن (تُسجَّل مديونية على العميل)").uncheck();
  await page.screenshot({ path: "e2e/shots/70-new-sales-order.png", fullPage: true });
  await page.getByRole("button", { name: "إنشاء أمر البيع" }).click();
  await expect(page.getByText("تم إنشاء أمر البيع")).toBeVisible();
  await page.getByRole("link", { name: "فتح الأمر" }).click();
  await expect(page.getByText("لم يُسلَّم")).toBeVisible();

  await page.getByRole("button", { name: "سلّم البضاعة" }).click();
  await expect(page.getByText("تم التسليم وخرجت البضاعة من المخزون")).toBeVisible();
  expect((await odoo("product.product", "read", [[pid]], { fields: ["qty_available"] }))[0].qty_available).toBe(15);

  await page.getByRole("button", { name: "إصدار فاتورة" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "إصدار فاتورة" }).click();
  await expect(page.getByText("صدرت الفاتورة وسُجّلت على العميل")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/71-sales-order.png", fullPage: true });
  const bills = await odoo("account.move", "search_read", [[["move_type", "=", "out_invoice"], ["partner_id.name", "=", "تاجر الجملة"]]], { fields: ["state", "amount_residual", "amount_total"] });
  expect(bills).toHaveLength(1);
  expect(bills[0].state).toBe("posted");
  expect(bills[0].amount_residual).toBe(bills[0].amount_total);

  await page.getByRole("link", { name: "تحصيل من العميل" }).click();
  await expect(page.getByText("تاجر الجملة").first()).toBeVisible();
  await expect(page.getByText("إجمالي المستحق عليه").or(page.getByText("المستحق")).first()).toBeVisible();
});
