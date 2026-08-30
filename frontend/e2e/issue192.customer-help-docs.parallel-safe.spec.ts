import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";

test("parallel-safe：客户壳帮助入口、信任说明与开发中无写副作用", async ({ browser }, testInfo) => {
  const context = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 900 } });
  const writes: string[] = [];
  await context.route("**/api/**", (route) => {
    const request = route.request();
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
    }
    return route.continue();
  });

  const page = await context.newPage();
  await login(page, "customer", "customer-demo");
  await expect(page.getByRole("navigation", { name: "客户导航" })).toBeVisible();
  await expect(page.getByRole("link", { name: "帮助文档" })).toBeVisible();
  await expect(page.getByRole("region", { name: "信任说明" })).toContainText("确认后才创建工单");
  await expect(page.getByRole("heading", { name: "AI 调查" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "人工客服" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "补偿审批" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("desktop-help-home.png"), fullPage: true });

  const writesAfterHome = writes.length;
  await page.getByRole("button", { name: "服务时间承诺（开发中）" }).focus();
  await expect(page.getByRole("button", { name: "服务时间承诺（开发中）" })).toBeFocused();
  await page.getByRole("button", { name: "服务时间承诺（开发中）" }).click();
  await expect(page.getByRole("status")).toContainText("服务时间承诺入口正在开发中");
  expect(writes.slice(writesAfterHome)).toEqual([]);

  await page.getByRole("link", { name: "阅读补偿说明" }).click();
  await expect(page).toHaveURL(/\/help\/docs#compensation$/);
  await expect(page.getByRole("heading", { name: "客户帮助中心信任说明" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "AI 调查只提供建议" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "人工客服承担公开回复责任" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "待审批还不是已经获得补偿" })).toBeVisible();
  await expect(page.getByRole("link", { name: "帮助文档" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByText("通常 24 小时内回复")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("desktop-help-docs.png"), fullPage: true });

  const writesAfterDocs = writes.length;
  await page.getByRole("button", { name: "服务时间承诺（开发中）" }).click();
  await expect(page.getByRole("status")).toContainText("服务时间承诺入口正在开发中");
  expect(writes.slice(writesAfterDocs)).toEqual([]);

  await page.locator("body").press("Tab");
  await expect(page.getByRole("link", { name: "Stellogic 客户帮助中心" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "帮助中心" })).toBeFocused();
  await page.keyboard.press("Tab");
  const docsLink = page.getByRole("link", { name: "帮助文档" });
  await expect(docsLink).toBeFocused();
  await expect(docsLink).toHaveCSS("outline-style", "solid");
  await page.screenshot({ path: testInfo.outputPath("keyboard-focus-help-docs.png") });

  const narrow = await context.newPage();
  await narrow.setViewportSize({ width: 360, height: 800 });
  await narrow.goto("/help");
  await expect(narrow.getByRole("link", { name: "帮助文档" })).toBeVisible();
  await expect(narrow.getByRole("region", { name: "信任说明" })).toBeVisible();
  await expect(narrow.getByRole("heading", { name: "补偿审批" })).toBeVisible();
  await narrow.screenshot({ path: testInfo.outputPath("narrow-help-home.png"), fullPage: true });
  await narrow.getByRole("link", { name: "帮助文档" }).click();
  await expect(narrow.getByRole("heading", { name: "客户帮助中心信任说明" })).toBeVisible();
  await narrow.screenshot({ path: testInfo.outputPath("narrow-help-docs.png"), fullPage: true });

  await context.close();
});
