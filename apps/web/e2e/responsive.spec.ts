import { expect, test } from "@playwright/test";

test("phone layout: bottom navigation, RTL, no horizontal scroll", async ({ page }) => {
  await page.goto("/signup");
  await page.getByLabel("اسم المحل").fill("مكتبة الأمل");
  await page.getByLabel("البريد الإلكتروني").fill(`m-${Date.now()}@example.com`);
  await page.getByLabel("كلمة المرور").fill("correct-horse-battery");
  await page.getByRole("button", { name: "إنشاء حساب جديد" }).click();
  await expect(page).toHaveURL(/\/today/);
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  const nav = page.getByRole("navigation", { name: "القائمة الرئيسية" }).last();
  await expect(nav).toBeVisible();
  await expect(nav.getByRole("link")).toHaveCount(4); // four main places; the rest under "More"
  await nav.getByRole("button", { name: "المزيد" }).click();
  await expect(page.getByRole("navigation", { name: "المزيد" }).getByRole("link", { name: "المشتريات" })).toBeVisible();
  await page.getByRole("navigation", { name: "المزيد" }).getByRole("link", { name: "الإدارة والإعدادات" }).click();
  await expect(page).toHaveURL(/\/settings/);
  await page.goto("/today");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ path: "e2e/shots/m1-today.png", fullPage: true });
  // touch targets are at least 44px tall
  for (const l of await nav.getByRole("link").all()) expect((await l.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await page.getByRole("link", { name: "المبيعات" }).click();
  await expect(page.getByText("لا توجد نقطة بيع مضبوطة بعد")).toBeVisible(); // honest empty state until the shop is connected and set up
});
