import { expect, test, type BrowserContext } from "@playwright/test";
import { login as loginForAudience } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";

declare const process: { env: Record<string, string | undefined> };

const statePath = "/artifacts/customer-session.json";
async function login(context: BrowserContext) {
  const page = await context.newPage();
  await loginForAudience(page, "customer", "customer-demo");
  await expect(page).toHaveURL(/\/help$/);
  return page;
}

test("后端重启后旧 Session 不恢复", async ({ browser }) => {
  test.skip(
    !["restart-prepare", "restart-verify"].includes(process.env.ISSUE80_SESSION_PHASE ?? ""),
  );

  if (process.env.ISSUE80_SESSION_PHASE === "restart-prepare") {
    const context = await newIssue80Context(browser);
    await login(context);
    await context.storageState({ path: statePath });
    await context.close();
    return;
  }

  const context = await newIssue80Context(browser, { storageState: statePath });
  const page = await context.newPage();
  await page.goto("/help");
  await expect(page).toHaveURL(/\/help\/login(?:\?.*)?$/);
  await expect(page.getByRole("heading", { name: "客户登录" })).toBeVisible();
  await context.close();
});

test("默认 30 分钟策略在加速配置下由真实 Session 到期执行", async ({ browser }) => {
  test.skip(process.env.ISSUE80_SESSION_PHASE !== "expiry");
  test.setTimeout(90_000);

  const context = await newIssue80Context(browser);
  const page = await login(context);
  await page.waitForTimeout(65_000);
  const expiredStatus = await page.evaluate(
    async () =>
      (await fetch("/api/auth/session", { credentials: "same-origin", cache: "no-store" })).status,
  );
  expect(expiredStatus).toBe(401);
  await page.goto("/help");
  await expect(page).toHaveURL(/\/help\/login(?:\?.*)?$/);
  await context.close();
});
