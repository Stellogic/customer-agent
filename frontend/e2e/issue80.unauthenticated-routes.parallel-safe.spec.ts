import { expect, test } from "@playwright/test";
import { newIssue80Context } from "./support/browser-context";

test("parallel-safe：未登录静态路由只执行匿名 Session 读取", async ({ browser }) => {
  const context = await newIssue80Context(browser);
  const customer = await context.newPage();
  await customer.goto("/help");
  await expect(customer).toHaveURL(/\/help\/login\?returnTo=%2Fhelp$/);
  await expect(customer.getByRole("heading", { name: "客户登录" })).toBeVisible();

  const internal = await context.newPage();
  await internal.goto("/internal/approvals");
  await expect(internal).toHaveURL(/\/internal\/login\?returnTo=%2Finternal%2Fapprovals$/);
  await expect(internal.getByRole("heading", { name: "内部工作人员登录" })).toBeVisible();
  await context.close();
});
