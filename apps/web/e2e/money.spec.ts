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

test("expenses: category, on-credit vs paid-now, paying later, approval, and honest money numbers", async ({ page, browser }) => {
  const stamp = Date.now();
  expect((await page.request.post("/api/auth/bootstrap", { data: { business_name: "بقالة", email: `mny-${stamp}@example.com`, password: "correct-horse-battery" } })).status()).toBe(201);
  const { odoo_url, odoo_db } = state();
  const cid = (await (await page.request.post("/api/connections", { data: { name: "Main", base_url: odoo_url, db_name: odoo_db, login: "admin", secret: "admin" } })).json()).id as string;
  const before = (await odoo("account.move", "search_read", [[["move_type", "=", "in_invoice"]]], { fields: ["id"] })).length as number;
  const label = `إيجار ${stamp % 1000}`;

  // ---- a category maps to an operating-expense account (never cost of goods sold)
  await page.goto("/money/categories");
  const options = await page.locator("select option").allInnerTexts();
  expect(options.some((o) => o.includes("Cost of Goods"))).toBe(false);
  await page.locator("select").selectOption({ index: 1 });
  await page.getByLabel("الاسم الذي يظهر لك").fill(label);
  await page.getByRole("button", { name: "أضف فئة" }).click();
  await expect(page.getByText(label)).toBeVisible();
  await page.screenshot({ path: "e2e/shots/50-categories.png", fullPage: true });

  // ---- an expense on credit stays a payable
  await page.goto("/money/expenses/new");
  await page.locator("select").first().selectOption({ label });
  await page.getByLabel("المبلغ", { exact: true }).fill("300");
  await page.getByLabel("البيان").fill("إيجار المحل");
  await page.getByRole("radio", { name: "آجل: أدفعه لاحقًا" }).click();
  await page.screenshot({ path: "e2e/shots/51-new-expense.png", fullPage: true });
  await page.getByRole("button", { name: "سجّل المصروف" }).click();
  await expect(page.getByText("تم تسجيل المصروف وتحقّقنا منه في أودو")).toBeVisible();

  // ---- another one paid at once from the drawer
  await page.goto("/money/expenses/new");
  await page.locator("select").first().selectOption({ label });
  await page.getByLabel("المبلغ", { exact: true }).fill("120");
  await page.getByLabel("البيان").fill("كهرباء");
  await page.getByRole("button", { name: "سجّل المصروف" }).click();
  await expect(page.getByText("تم تسجيل المصروف وتحقّقنا منه في أودو")).toBeVisible();
  await page.goto("/money/expenses");
  await expect(page.getByText("غير مدفوع", { exact: true })).toBeVisible();
  await expect(page.getByText("مدفوع", { exact: true })).toBeVisible();

  // ---- pay part of the credit expense later
  await page.locator("li", { hasText: "إيجار المحل" }).getByRole("button", { name: "ادفع" }).click();
  await page.getByLabel("المبلغ").fill("100");
  await page.getByRole("button", { name: "ادفع", exact: true }).last().click();
  await expect(page.getByText("مدفوع جزئيًا")).toBeVisible();

  // ---- the money screen keeps the figures apart and refuses to invent a profit
  await page.goto("/money");
  await expect(page.getByText("النقدية والبنك").or(page.getByText("الخزنة").first())).toBeVisible();
  await expect(page.getByText("مستحق للموردين")).toBeVisible();
  await expect(page.getByText("غير متاح الآن")).toBeVisible();
  await expect(page.getByText("المستحق (تحمّلته)")).toBeVisible();
  await expect(page.getByText("المدفوع فعلًا")).toBeVisible();
  await expect(page.getByText("ما زال مستحقًا")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/52-money.png", fullPage: true });
  const bills = await odoo("account.move", "search_read", [[["move_type", "=", "in_invoice"], ["ref", "=", false]]], { fields: ["amount_total", "amount_residual", "payment_state"] });
  expect(bills.length).toBeGreaterThanOrEqual(before - before + 2);

  // ---- an accountant's large expense waits for the owner
  const acc = `acc-${stamp}@example.com`;
  expect((await page.request.post("/api/users", { data: { email: acc, password: "account-password-1", role: "accountant" } })).status()).toBe(201);
  const ctx = await browser.newContext();
  const ap = await ctx.newPage();
  await ap.goto("/login");
  await ap.getByLabel("البريد الإلكتروني").fill(acc);
  await ap.getByLabel("كلمة المرور").fill("account-password-1");
  await ap.getByRole("button", { name: "تسجيل الدخول" }).click();
  await expect(ap).toHaveURL(/\/today/);
  await ap.goto("/money/expenses/new");
  await ap.locator("select").first().selectOption({ label });
  await ap.getByLabel("المبلغ", { exact: true }).fill("5000");
  await ap.getByLabel("البيان").fill("معدات كبيرة");
  await ap.getByRole("radio", { name: "آجل: أدفعه لاحقًا" }).click();
  await ap.getByRole("button", { name: "سجّل المصروف" }).click();
  await expect(ap.getByText(/أُرسل للموافقة/)).toBeVisible();
  await ctx.close();
  const mid = (await odoo("account.move", "search_read", [[["move_type", "=", "in_invoice"]]], { fields: ["id"] })).length as number;
  await page.goto("/money/expenses");
  await expect(page.getByText("مصروفات بانتظار الموافقة")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/53-expense-approval.png", fullPage: true });
  await page.getByRole("button", { name: "وافق" }).first().click();
  await expect(page.getByText("مصروفات بانتظار الموافقة")).toBeHidden({ timeout: 20_000 });
  await expect.poll(async () => (await odoo("account.move", "search_read", [[["move_type", "=", "in_invoice"]]], { fields: ["id"] })).length as number, { timeout: 20_000 }).toBe(mid + 1); // booked only after approval
  await expect(page.getByText("معدات كبيرة")).toBeVisible();
});
