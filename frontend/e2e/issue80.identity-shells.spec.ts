import { expect, test, type BrowserContext } from "@playwright/test";
import { login } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";

async function freshPage(context: BrowserContext, path: string) {
  const page = await context.newPage();
  await page.goto(path);
  return page;
}

test.describe("Issue #80 五类身份的 Shell 与静态路由", () => {
  test("未登录直达客户和内部 URL 时进入对应登录页", async ({ browser }) => {
    const context = await newIssue80Context(browser);
    const customer = await freshPage(context, "/help");
    await expect(customer).toHaveURL(/\/help\/login\?returnTo=%2Fhelp$/);
    await expect(customer.getByRole("heading", { name: "客户登录" })).toBeVisible();

    const internal = await freshPage(context, "/internal/approvals");
    await expect(internal).toHaveURL(/\/internal\/login\?returnTo=%2Finternal%2Fapprovals$/);
    await expect(internal.getByRole("heading", { name: "内部工作人员登录" })).toBeVisible();
    await context.close();
  });

  const identities = [
    {
      username: "customer-demo",
      audience: "customer" as const,
      landing: "/help",
      shell: "客户帮助中心",
      visibleMenus: [] as string[],
      forbidden: "/internal/support",
    },
    {
      username: "support-demo",
      audience: "internal" as const,
      landing: "/internal/support",
      shell: "内部工作台",
      visibleMenus: ["客服工作区"],
      forbidden: "/internal/approvals",
    },
    {
      username: "approver-demo",
      audience: "internal" as const,
      landing: "/internal/approvals",
      shell: "内部工作台",
      visibleMenus: ["审批工作区"],
      forbidden: "/internal/support",
    },
    {
      username: "internal-demo",
      audience: "internal" as const,
      landing: "/internal",
      shell: "内部工作台",
      visibleMenus: ["客服工作区", "审批工作区"],
    },
  ] as const;

  for (const identity of identities) {
    test(`${identity.username} 只看到本身份 Shell、菜单和默认落点`, async ({ page }) => {
      await login(page, identity.audience, identity.username);
      await expect(page).toHaveURL(new RegExp(`${identity.landing.replaceAll("/", "\\/")}$`));
      if (identity.audience === "customer") {
        await expect(page.getByRole("banner", { name: identity.shell })).toBeVisible();
      } else {
        await expect(page.getByRole("banner").filter({ hasText: "统一内部工作台" })).toBeVisible();
      }

      for (const menu of identity.visibleMenus) {
        await expect(page.getByRole("link", { name: menu, exact: true })).toBeVisible();
      }
      if (identity.username === "support-demo") {
        await expect(page.getByRole("link", { name: "审批工作区", exact: true })).toHaveCount(0);
      }
      if (identity.username === "approver-demo") {
        await expect(page.getByRole("link", { name: "客服工作区", exact: true })).toHaveCount(0);
      }
      if (identity.username === "customer-demo") {
        await expect(page.getByRole("navigation", { name: "内部工作区" })).toHaveCount(0);
      }

      if ("forbidden" in identity) {
        await page.goto(identity.forbidden);
        await expect(page.getByRole("heading", { name: "403" })).toBeVisible();
      } else {
        await page.goto("/internal/support");
        await expect(page.getByRole("heading", { name: "客服共享队列" })).toBeVisible();
        await page.goto("/internal/approvals");
        await expect(
          page.getByRole("heading", { level: 1, name: /待审批补偿|补偿提案审批/ }),
        ).toBeVisible();
      }
    });
  }
});
