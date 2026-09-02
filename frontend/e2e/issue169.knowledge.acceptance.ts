import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";

declare const process: { env: Record<string, string | undefined> };

// 单独的真实服务验收入口；必须由本票HTTP/PG阶段准备已接受的合成工单。
for (const width of [1440, 390]) {
  test(`客户真实来源、窄屏与断线恢复（${width}px）`, async ({ browser }, testInfo) => {
    const ticketId = process.env.ISSUE169_BROWSER_TICKET;
    if (!ticketId) throw new Error("缺少本票真实HTTP阶段准备的工单，不能用页面fixture替代");
    const context = await newAcceptanceContext(browser, { viewport: { width, height: 960 } });
    try {
      const page = await context.newPage();
      await login(page, "customer", "customer-demo");
      const url = `/api/customer/v2/tickets/${ticketId}`;
      const response = await context.request.get(url);
      expect(response.status()).toBe(200);
      const raw = await response.text();
      expect(raw).toContain("配送问题的信息补充指南");
      expect(raw).not.toMatch(/"(?:articleId|chunkId|sourceFile|vectorScore|snippet)"/);
      await page.goto(`/help?ticket=${ticketId}`);
      const title = page.getByText("配送问题的信息补充指南", { exact: true });
      await expect(title).toBeVisible();
      await expect(page.locator(".customer-knowledge-sources time").first()).toHaveAttribute(
        "datetime",
        "2026-09-01T00:00:00Z",
      );
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        width,
      );
      await title.scrollIntoViewIfNeeded();
      await page
        .locator(".customer-knowledge-sources")
        .screenshot({ path: testInfo.outputPath(`sources-${width}.png`) });

      // 仅制造网络断线，不替换Spring快照或来源正文。
      const events = `**/api/customer/v2/tickets/${ticketId}/events`;
      await page.route(events, (route) => route.abort("connectionfailed"));
      await page.reload();
      await expect(
        page.getByText("连接恢复中，正在重新确认本次回复的知识来源。", { exact: true }),
      ).toBeVisible();
      await expect(title).toHaveCount(0);
      await page.unroute(events);
      await expect(title).toBeVisible({ timeout: 20_000 });
      await title.scrollIntoViewIfNeeded();
      await page
        .locator(".customer-knowledge-sources")
        .screenshot({ path: testInfo.outputPath(`recovered-${width}.png`) });
    } finally {
      await context.close();
    }
  });
}
