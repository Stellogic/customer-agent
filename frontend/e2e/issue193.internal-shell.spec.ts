import { expect, test } from "@playwright/test";
import { newAcceptanceContext } from "./support/browser-context";

// 独立壳层视觉源码：浏览器使用合成 Session，不代表真实后端授权验收。
// 未加入 scripts/browser-acceptance-plan.psd1；执行须另获协调任务放行。
const identities = [
  {
    id: "support-shell-fixture",
    displayName: "客服壳层合成示例",
    subjectType: "INTERNAL",
    roles: ["SUPPORT"],
    capabilities: ["SUPPORT_WORKBENCH_ACCESS", "KNOWLEDGE_READ_ACCESS"],
  },
  {
    id: "approver-shell-fixture",
    displayName: "审批壳层合成示例",
    subjectType: "INTERNAL",
    roles: ["APPROVER"],
    capabilities: ["APPROVAL_WORKBENCH_ACCESS"],
  },
] as const;

for (const identity of identities) {
  for (const width of [1440, 360]) {
    test(`${identity.id} ${width}px：入口、键盘、无业务写入与重新确认身份`, async ({
      browser,
    }, testInfo) => {
      const context = await newAcceptanceContext(browser, { viewport: { width, height: 900 } });
      let authorized = true;
      let sessionReads = 0;
      const businessRequests: string[] = [];
      await context.route("**/api/**", async (route) => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        if (path === "/api/auth/session" && request.method() === "GET") {
          sessionReads += 1;
          await route.fulfill({ status: authorized ? 200 : 401, json: authorized ? identity : {} });
        } else if (path === "/api/auth/csrf") {
          await route.fulfill({ json: { token: "shell-fixture", headerName: "X-CSRF-TOKEN" } });
        } else if (path === "/api/auth/demo-accounts") {
          await route.fulfill({ status: 404 });
        } else {
          businessRequests.push(`${request.method()} ${path}`);
          await route.fulfill({ status: 503 });
        }
      });

      try {
        const page = await context.newPage();
        // 工作区选择页不加载队列数据，避免将已有页面请求误归因于占位入口。
        await page.goto("/internal");
        const header = page.getByRole("banner", { name: "内部工作台", exact: true });
        await expect(header.getByText(`当前工作人员：${identity.displayName}`)).toBeVisible();
        if (width === 360) {
          const expand = header.getByRole("button", { name: "展开侧栏", exact: true });
          await expect(expand).toBeVisible();
          await expand.focus();
          await page.keyboard.press("Enter");
        }
        const shortcuts = page.getByRole("navigation", { name: "快捷入口" });
        await expect(shortcuts).toBeVisible();
        if (identity.roles[0] === "SUPPORT") {
          await expect(shortcuts.getByRole("link", { name: /我的工单/ })).toHaveAttribute(
            "href",
            "/internal/support",
          );
          await expect(shortcuts.getByRole("link", { name: /SLA 监控/ })).toHaveAttribute(
            "href",
            "/internal/support",
          );
          await expect(shortcuts.getByRole("link", { name: "知识库" })).toHaveAttribute(
            "href",
            "/internal/knowledge",
          );
        } else {
          await expect(shortcuts.getByRole("link")).toHaveCount(0);
        }
        const template = shortcuts.getByRole("button", { name: "模板中心" });
        await template.focus();
        await page.keyboard.press("Enter");
        const templateDialog = page.getByRole("dialog", { name: "模板中心 · 开发中" });
        await expect(templateDialog.getByRole("status")).toContainText("未提交业务请求");
        await page.keyboard.press("Escape");
        await expect(templateDialog).toBeHidden();
        await expect(template).toBeFocused();
        await expect(template).toHaveCSS("outline-style", "solid");
        await page.screenshot({
          path: testInfo.outputPath(`shell-${width}-focus.png`),
          fullPage: true,
        });

        await page.getByRole("button", { name: "收起侧栏", exact: true }).click();
        await expect(header.getByRole("button", { name: "展开侧栏", exact: true })).toBeFocused();
        await expect(shortcuts).toBeHidden();
        await header.getByRole("button", { name: "通知中心" }).click();
        const notifications = page.getByRole("dialog", { name: "通知中心 · 开发中" });
        await expect(notifications.getByRole("status")).toContainText("未更改任何业务状态");
        await page.screenshot({ path: testInfo.outputPath(`shell-${width}-notification.png`) });
        await notifications.getByRole("button", { name: "知道了" }).click();
        expect(businessRequests).toEqual([]);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        );

        // 模拟重新同步时 Session 失效，旧壳由既有 SessionGate 卸载。
        authorized = false;
        const before = sessionReads;
        await header.getByRole("link", { name: "重新同步", exact: true }).click();
        await expect(page.getByRole("heading", { name: "内部工作人员登录" })).toBeVisible();
        await expect(header).toHaveCount(0);
        await expect(page.getByText(`当前工作人员：${identity.displayName}`)).toHaveCount(0);
        expect(sessionReads).toBeGreaterThan(before);
        expect(businessRequests).toEqual([]);
        await page.screenshot({ path: testInfo.outputPath(`shell-${width}-session-expired.png`) });
      } finally {
        await context.close();
      }
    });
  }
}

test("独立壳 loading/error：身份未确认时不暴露内部入口", async ({ browser }, testInfo) => {
  const context = await newAcceptanceContext(browser, { viewport: { width: 360, height: 800 } });
  let releaseSession: () => void = () => undefined;
  const pending = new Promise<void>((resolve) => {
    releaseSession = resolve;
  });
  await context.route("**/api/auth/session", async (route) => {
    await pending;
    await route.fulfill({ status: 503 });
  });
  try {
    const page = await context.newPage();
    await page.goto("/internal", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("status", { name: "正在确认当前身份" })).toBeVisible();
    await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "true");
    await expect(page.getByRole("navigation", { name: "快捷入口" })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath("shell-loading.png"), fullPage: true });
    releaseSession();
    await expect(page.getByRole("alert")).toContainText("当前身份暂时无法确认");
    await expect(page.getByRole("navigation", { name: "快捷入口" })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath("shell-error.png"), fullPage: true });
  } finally {
    releaseSession();
    await context.close();
  }
});
