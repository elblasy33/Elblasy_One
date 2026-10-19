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

test("owner buys goods: supplier, order, partial receipt, bill, partial payment, statement", async ({ page }) => {
  const email = `buy-${Date.now()}@example.com`;
  expect((await page.request.post("/api/auth/bootstrap", { data: { business_name: "بقالة", email, password: "correct-horse-battery" } })).status()).toBe(201);
  const { odoo_url, odoo_db } = state();
  const cid = (await (await page.request.post("/api/connections", { data: { name: "Main", base_url: odoo_url, db_name: odoo_db, login: "admin", secret: "admin" } })).json()).id as string;
  const mk = await page.request.post(`/api/connections/${cid}/catalog/products`, { headers: { "Idempotency-Key": crypto.randomUUID().replaceAll("-", "") }, data: { name: "أرز المشتريات", price: 30, cost: 20 } });
  const pid = (await mk.json()).variant_ids[0] as number;
  const supplierName = `مورد النور ${Date.now() % 1000}`;

  // ---- supplier
  await page.goto("/inventory/suppliers");
  await expect(page.getByText("لا موردين بعد")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/30-suppliers-empty.png", fullPage: true });
  await page.getByRole("button", { name: "مورد جديد" }).click();
  await page.getByLabel("اسم المورد", { exact: true }).fill(supplierName);
  await page.getByLabel("الهاتف", { exact: true }).fill("01001234567");
  await page.getByRole("button", { name: "حفظ المورد" }).click();
  await expect(page.getByText(supplierName)).toBeVisible();

  // ---- purchase order
  await page.getByRole("link", { name: "المشتريات" }).first().click();
  await page.getByRole("link", { name: "أمر شراء جديد" }).click();
  await page.locator("select").selectOption({ label: supplierName });
  await page.getByLabel("ابحث عن منتج للشراء").fill("أرز");
  await page.getByRole("button", { name: /أرز المشتريات/ }).click();
  await page.getByLabel("الكمية", { exact: true }).fill("10");
  await page.getByLabel("سعر الوحدة").fill("20");
  await page.screenshot({ path: "e2e/shots/31-new-po.png", fullPage: true });
  await page.getByRole("button", { name: "تأكيد أمر الشراء" }).click();
  await expect(page.getByText("تم تأكيد أمر الشراء")).toBeVisible();
  await page.getByRole("link", { name: "استلام بضاعة" }).click();

  // ---- ordered is not received is not on hand
  await expect(page.getByText("لم يُستلم")).toBeVisible();
  await expect(page.getByText(/في الطريق\s*10/)).toBeVisible();
  expect((await odoo("product.product", "read", [[pid]], { fields: ["qty_available"] }))[0].qty_available).toBe(0);

  // ---- partial receipt of 6
  await page.getByRole("button", { name: "استلام بضاعة" }).click();
  await page.getByLabel("الكمية", { exact: true }).fill("6");
  await page.getByRole("button", { name: "تأكيد الاستلام" }).click();
  await expect(page.getByText("تم الاستلام وتحقّقنا من المخزون")).toBeVisible();
  await expect(page.getByText("استلام جزئي")).toBeVisible();
  await expect(page.getByText(/الموجود\s*6/)).toBeVisible();
  await expect(page.getByText(/في الطريق\s*4/)).toBeVisible();
  expect((await odoo("product.product", "read", [[pid]], { fields: ["qty_available"] }))[0].qty_available).toBe(6);
  await page.screenshot({ path: "e2e/shots/32-po-partial.png", fullPage: true });

  // ---- bill what arrived, then pay part of it
  await page.getByRole("button", { name: "إنشاء فاتورة المورد" }).click();
  await expect(page.getByText("تم ترحيل فاتورة المورد")).toBeVisible();
  await expect(page.getByText("غير مدفوعة")).toBeVisible();
  await page.getByRole("button", { name: "ادفع", exact: true }).click();
  await page.getByLabel("المبلغ", { exact: true }).fill("50");
  await page.getByRole("button", { name: "ادفع", exact: true }).last().click();
  await expect(page.getByText("تم تسجيل الدفع")).toBeVisible();
  await expect(page.getByText("مدفوعة جزئيًا")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/33-po-billed-paid.png", fullPage: true });

  // ---- the supplier's statement shows the balance, bill and payment
  await page.goto("/inventory/suppliers");
  await page.getByText(supplierName).click();
  await expect(page.getByText("إجمالي المستحق")).toBeVisible();
  await expect(page.getByText("الفواتير")).toBeVisible();
  await expect(page.getByText("الدفعات")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/34-statement.png", fullPage: true });
  const bills = await odoo("account.move", "search_read", [[["move_type", "=", "in_invoice"], ["partner_id.name", "=", supplierName]]], { fields: ["state", "amount_total", "payment_state"] });
  expect(bills).toHaveLength(1);
  expect(bills[0].state).toBe("posted");
  expect(Math.abs(bills[0].amount_total - 6 * 20 * 1.14)).toBeLessThan(0.02);
  expect(bills[0].payment_state).toBe("partial");
});
