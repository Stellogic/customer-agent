import { expect, test } from "@playwright/test";
import { newIssue80Context } from "./support/browser-context";

test("parallel-safe：静态加载、错误和 404 状态不读写共享数据库", async ({ browser }, testInfo) => {
  const context = await newIssue80Context(browser, { viewport: { width: 1440, height: 900 } });

  const notFound = await context.newPage();
  await notFound.goto("/not-a-business-resource");
  await expect(notFound.getByRole("heading", { name: "没有找到这个页面" })).toBeVisible();
  await notFound.keyboard.press("Tab");
  await expect(notFound.getByRole("link", { name: "前往客户登录" })).toBeFocused();
  await notFound.screenshot({ path: testInfo.outputPath("parallel-safe-404.png") });

  const error = await context.newPage();
  await error.route("**/api/auth/session", (route) =>
    route.fulfill({ status: 503, body: "temporarily unavailable" }),
  );
  await error.goto("/help");
  await expect(error.getByRole("heading", { name: "暂时无法进入工作区" })).toBeVisible();

  const loading = await context.newPage();
  let releaseSession: (() => void) | undefined;
  await loading.route("**/api/auth/session", async (route) => {
    await new Promise<void>((resolve) => {
      releaseSession = resolve;
    });
    await route.fulfill({ status: 401 });
  });
  await loading.goto("/help", { waitUntil: "domcontentloaded" });
  await expect(loading.locator("main[aria-busy='true']")).toBeVisible();
  releaseSession?.();
  await expect(loading).toHaveURL(/\/help\/login\?returnTo=%2Fhelp$/);
  await context.close();
});
