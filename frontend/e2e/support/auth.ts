import { expect, type Page } from "@playwright/test";

const password = "local-demo-password";

export async function login(page: Page, audience: "customer" | "internal", username: string) {
  await page.goto(audience === "customer" ? "/help/login" : "/internal/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).not.toHaveURL(/\/login(?:\?.*)?$/);
}

export async function continueAsNewIfDuplicate(page: Page) {
  const duplicateHeading = page.getByRole("heading", { name: "请确认是否继续既有工单" });
  await expect(
    page.getByRole("heading", { name: /请确认我的理解|请确认是否继续既有工单/ }),
  ).toBeVisible();
  if (await duplicateHeading.isVisible()) {
    await page.getByRole("button", { name: "这是新问题，继续创建" }).click();
  }
  await expect(page.getByRole("heading", { name: "请确认我的理解" })).toBeVisible();
}

export { password };
