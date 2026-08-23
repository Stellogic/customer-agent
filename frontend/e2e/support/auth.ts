import { expect, type Page } from "@playwright/test";

const password = "local-demo-password";

export async function login(page: Page, audience: "customer" | "internal", username: string) {
  await page.goto(audience === "customer" ? "/help/login" : "/internal/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).not.toHaveURL(/\/login(?:\?.*)?$/);
}

export { password };
