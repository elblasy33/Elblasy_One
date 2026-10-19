import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const state = () => JSON.parse(fs.readFileSync(path.resolve(__dirname, ".state.json"), "utf8")) as { odoo_url: string; odoo_db: string };

test("grocery owner adds weighed and made products, builds a recipe, and imports a file", async ({ page }) => {
  // fast path to a configured shop: sign up + connect + plan through the API (the UI path is covered by onboarding.spec)
  const email = `cat-${Date.now()}@example.com`;
  expect((await page.request.post("/api/auth/bootstrap", { data: { business_name: "بقالة", email, password: "correct-horse-battery" } })).status()).toBe(201);
  const { odoo_url, odoo_db } = state();
  const conn = await page.request.post("/api/connections", { data: { name: "Main", base_url: odoo_url, db_name: odoo_db, login: "admin", secret: "admin" } });
  expect(conn.status()).toBe(201);
  const cid = (await conn.json()).id as string;
  const plan = await page.request.post(`/api/connections/${cid}/setup/plans`, { data: { answers: { vertical: "grocery", makes_own_products: true, uses_weighing_scale: true, tracks_expiry: false, needs_variants: false, multiple_uom: false, sells_on_credit: false, buys_on_credit: true, payment_methods: ["cash"], branches: 1 } } });
  expect(plan.status()).toBe(201);

  await page.goto("/inventory");
  await expect(page.getByRole("heading", { name: "المنتجات" })).toBeVisible();
  await page.screenshot({ path: "e2e/shots/10-products-empty.png", fullPage: true });

  // ---- a product sold by weight gets an automatic scale code
  await page.getByRole("link", { name: "منتج جديد" }).click();
  await page.getByLabel("اسم المنتج").fill("طماطم");
  await page.getByLabel("سعر البيع").fill("20");
  await page.getByLabel("سعر الشراء (التكلفة)").fill("12");
  await page.getByRole("switch", { name: /يُباع بالوزن/ }).click();
  await expect(page.getByRole("radio", { name: "كود ميزان تلقائي" })).toHaveAttribute("aria-checked", "true");
  await page.screenshot({ path: "e2e/shots/11-new-weighed.png", fullPage: true });
  await page.getByRole("button", { name: "حفظ المنتج" }).click();
  await expect(page.getByText("تم حفظ المنتج")).toBeVisible();
  const scale = (await page.locator("p.font-mono").innerText()).trim();
  expect(scale).toMatch(/^21\d{11}$/);
  expect(scale.slice(7, 12)).toBe("00000");
  await page.screenshot({ path: "e2e/shots/12-saved.png", fullPage: true });

  // ---- ingredient + a product the shop makes
  await page.getByRole("button", { name: "إضافة منتج آخر" }).click();
  await expect(page.getByRole("switch", { name: /يُباع بالوزن/ })).toHaveAttribute("aria-checked", "false"); // clean form
  await page.getByLabel("اسم المنتج").fill("دقيق");
  await page.getByLabel("سعر البيع").fill("18");
  await page.getByRole("radio", { name: "ولّد تلقائيًا" }).click();
  await page.getByRole("button", { name: "حفظ المنتج" }).click();
  await expect(page.getByText("تم حفظ المنتج")).toBeVisible();
  await page.getByRole("button", { name: "إضافة منتج آخر" }).click();
  await page.getByLabel("اسم المنتج").fill("كيك");
  await page.getByLabel("سعر البيع").fill("60");
  await page.getByRole("switch", { name: /منتج مصنّع/ }).click();
  await page.getByRole("button", { name: "حفظ المنتج" }).click();
  await expect(page.getByText("تم حفظ المنتج")).toBeVisible();
  await page.getByRole("link", { name: "حدّد مكوّناته" }).click();
  await page.getByLabel("ابحث عن مكوّن").fill("دقيق");
  await page.getByRole("button", { name: /دقيق/ }).click();
  await page.getByLabel("الكمية", { exact: true }).first().fill("2");
  await page.screenshot({ path: "e2e/shots/13-recipe.png", fullPage: true });
  await page.getByRole("button", { name: "حفظ الوصفة" }).click();
  await expect(page.getByText("تم حفظ الوصفة")).toBeVisible();

  // ---- list + search by barcode
  await page.goto("/inventory");
  await page.getByPlaceholder("ابحث بالاسم أو الباركود").fill(scale);
  await expect(page.getByText("طماطم")).toBeVisible();
  await expect(page.getByText("بالوزن")).toHaveCount(1);
  await page.getByPlaceholder("ابحث بالاسم أو الباركود").fill("");
  await expect(page.getByText("كيك")).toBeVisible();
  await expect(page.getByText("بالوزن")).toHaveCount(1); // only the tomatoes are sold by weight
  await page.screenshot({ path: "e2e/shots/14-products.png", fullPage: true });

  // ---- import: validated first, nothing created until confirmed
  await page.getByRole("link", { name: "استيراد من ملف" }).click();
  await page.getByLabel("أو الصق المحتوى هنا").fill("name,price,cost,auto_barcode\nرز,25.5,20,internal\nزيت,abc,10,\nملح,5,3,internal\n");
  await page.getByRole("button", { name: "راجع الملف" }).click();
  await expect(page.getByText("✓ 2 سليمة")).toBeVisible();
  await expect(page.getByText("price must be a number")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/15-import-check.png", fullPage: true });
  await page.getByRole("button", { name: /أنشئ الصفوف السليمة/ }).click();
  await expect(page.getByText("تم الاستيراد")).toBeVisible();
  await page.goto("/inventory");
  await page.getByPlaceholder("ابحث بالاسم أو الباركود").fill("رز");
  await expect(page.getByText("رز").first()).toBeVisible();
});
