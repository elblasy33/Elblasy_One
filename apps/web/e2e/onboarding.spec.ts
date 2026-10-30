import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const state = () => JSON.parse(fs.readFileSync(path.resolve(__dirname, ".state.json"), "utf8")) as { odoo_url: string; odoo_db: string };

test("owner signs up, connects Odoo, runs the grocery wizard and the setup is verified", async ({ page }) => {
  const email = `owner-${Date.now()}@example.com`;

  // --- sign up (Arabic, RTL by default)
  await page.goto("/signup");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await page.getByLabel("اسم المحل").fill("بقالة النور");
  await page.getByLabel("البريد الإلكتروني").fill(email);
  await page.getByLabel("كلمة المرور").fill("correct-horse-battery");
  await page.getByRole("button", { name: "إنشاء حساب جديد" }).click();
  await expect(page).toHaveURL(/\/today/);
  await expect(page.getByText("اربط أودو")).toBeVisible(); // honest next step, no fake KPIs
  await page.screenshot({ path: "e2e/shots/01-today-empty.png", fullPage: true });

  // --- connect Odoo
  await page.getByText("اربط أودو").click();
  const { odoo_url, odoo_db } = state();
  await page.getByLabel("عنوان أودو").fill(odoo_url);
  await page.getByLabel("اسم قاعدة البيانات").fill(odoo_db);
  await page.getByLabel("اسم المستخدم").fill("admin");
  await page.getByLabel("مفتاح API أو كلمة المرور").fill("admin");
  await page.screenshot({ path: "e2e/shots/02-connect.png", fullPage: true });
  await page.getByRole("button", { name: "اتصال وفحص" }).click();
  await expect(page).toHaveURL(/\/settings\/setup/);

  // --- wizard: no business type; the shop is described by how it works, stage by stage
  await expect(page.getByRole("navigation", { name: "مراحل الإعداد" })).toBeVisible();
  await expect(page.getByText("ما نوع نشاطك؟")).toHaveCount(0);
  await page.getByRole("checkbox", { name: /حاجات بتعملها أو بتجهزها بنفسك/ }).click(); // goods are ticked by default
  await expect(page.getByText("وصفات وتصنيع: المكونات تتخصم والمنتج يتضاف")).toBeVisible(); // live preview
  await page.waitForTimeout(400);
  await page.screenshot({ path: "e2e/shots/03-wizard-question.png", fullPage: true });
  const pick = async (question: string, answer: string) =>
    page.getByRole("radiogroup", { name: question }).getByRole("radio", { name: answer }).click();
  await page.getByRole("button", { name: "التالي" }).click();
  await pick("بتبيع حاجات بالوزن؟", "نعم");
  await pick("عندك ميزان بيطبع ملصق عليه باركود؟", "نعم");
  await expect(page.getByText("قراءة ملصقات الميزان بالباركود والوزن جواه")).toBeVisible();
  await page.getByRole("button", { name: "التالي" }).click();
  await pick("بتبيع بالآجل (على الحساب)؟", "نعم");
  await pick("وضعك مع ضريبة القيمة المضافة؟", "مسجّل، والضريبة بتتضاف على السعر");
  await page.screenshot({ path: "e2e/shots/04-wizard-payments.png", fullPage: true });
  await page.getByRole("button", { name: "التالي" }).click();
  await page.getByRole("button", { name: "التالي" }).click();
  await page.getByRole("button", { name: "التالي" }).click();
  // review: every answer shown, any stage can be reopened
  await expect(page.getByText("بتبيع بالآجل (على الحساب)؟")).toBeVisible();
  await page.getByRole("button", { name: "تعديل" }).first().click();
  await expect(page.getByRole("checkbox", { name: /حاجات بتعملها/ })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: /المراجعة/ }).click();
  await page.getByRole("button", { name: "جهّز خطة الإعداد" }).click();

  // --- plan review
  await expect(page).toHaveURL(/\/settings\/plans\//);
  await expect(page.getByRole("heading", { name: "سيتم إضافته" })).toBeVisible();
  await expect(page.getByText("تفعيل: التصنيع")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/05-plan.png", fullPage: true });
  await page.getByRole("button", { name: "أوافق على الخطة" }).click();
  await expect(page.getByRole("button", { name: "ابدأ الإعداد" })).toBeVisible();

  // --- run, with confirmation, and watch live progress
  await page.getByRole("button", { name: "ابدأ الإعداد" }).click();
  await expect(page.getByText("ننصح بعمل نسخة احتياطية")).toBeVisible();
  await page.getByRole("button", { name: "تأكيد وبدء الإعداد" }).click();
  await expect(page.getByText("المحل جاهز للتشغيل")).toBeVisible({ timeout: 180_000 });
  await page.screenshot({ path: "e2e/shots/06-done.png", fullPage: true });

  // --- independent evidence from Odoo itself
  const { odoo_url: url, odoo_db: db } = state();
  const rpc = async (service: string, method: string, args: unknown[]) => {
    const body = `<?xml version="1.0"?><methodCall><methodName>${method}</methodName></methodCall>`;
    void body; // XML-RPC via JSON-RPC endpoint instead:
    const r = await fetch(`${url}/jsonrpc`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { service, method, args }, id: 1 }) });
    return (await r.json()).result;
  };
  const uid = await rpc("common", "authenticate", [db, "admin", "admin", {}]);
  const mods = await rpc("object", "execute_kw", [db, uid, "admin", "ir.module.module", "search_read", [[["name", "=", "mrp"]]], { fields: ["state"] }]);
  expect(mods[0].state).toBe("installed");
  const cfgs = await rpc("object", "execute_kw", [db, uid, "admin", "pos.config", "search_count", [[]]]);
  expect(cfgs).toBe(1);

  // --- Today now reflects reality
  await page.getByRole("link", { name: "اليوم" }).first().click();
  await expect(page.getByText("المحل جاهز للتشغيل")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/07-today-ready.png", fullPage: true });

  // --- language switch flips direction
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.getByRole("heading", { name: /Welcome/ })).toBeVisible();
});
