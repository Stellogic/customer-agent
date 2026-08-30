import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";

// Public-view fixtures isolate layout and interaction. Spring integration tests own timer authority.
for (const width of [1440, 390]) {
  test(`Issue #162 自动解决公开状态与刷新恢复（${width}px）`, async ({ browser }) => {
    const context = await newAcceptanceContext(browser, { viewport: { width, height: 960 } });
    const page = await context.newPage();
    const ticketId = "16200000-0000-0000-0000-000000000001";
    const dueAt = new Date(Date.now() + 240_000).toISOString();
    let status = "PENDING";
    await login(page, "customer", "customer-demo");
    await page.route(`**/api/customer/v2/tickets/${ticketId}`, (route) =>
      route.fulfill({
        json: {
          view: "PUBLIC_CONVERSATION",
          schema: "public-conversation-v2",
          cursor: "public-conversation-v2:2",
          ticket: {
            id: ticketId,
            lifecycleState: status === "RESOLVED" ? "RESOLVED" : "INVESTIGATING",
            handlingMode: "AGENT",
            agentGeneration: 1,
          },
          messages: [],
          clarification: null,
          autoResolution: { status, dueAt: status === "PENDING" ? dueAt : null },
        },
      }),
    );
    // Keep the stream request pending so the fixture does not simulate an EOF/disconnection.
    await page.route(`**/api/customer/v2/tickets/${ticketId}/events`, () => {});
    await page.route(`**/api/customer/tickets/${ticketId}/auto-resolution/cancel`, (route) => {
      expect(route.request().postDataJSON()).toEqual({
        candidateDueAt: dueAt,
        candidateGeneration: 1,
      });
      status = "CANCELLED";
      return route.fulfill({ json: {} });
    });

    await page.goto(`/help?ticket=${ticketId}`);
    const notice = page.getByRole("region", { name: "自动解决状态" });
    await expect(notice.getByText("即将自动解决", { exact: true })).toBeVisible();
    await expect(notice.getByRole("timer")).toBeVisible();
    await expect(notice.locator("time")).toHaveAttribute("datetime", dueAt);
    await page.reload();
    await expect(notice.locator("time")).toHaveAttribute("datetime", dueAt);
    const cancel = notice.getByRole("button", { name: "仍需帮助，取消自动解决" });
    await expect(cancel).toBeVisible();
    const bounds = await cancel.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    await page.screenshot({ path: `/artifacts/issue162-pending-${width}.png`, fullPage: true });
    await cancel.click();
    await expect(notice.getByText("已取消自动解决", { exact: true })).toBeVisible();
    await expect(cancel).toHaveCount(0);
    await page.reload();
    await expect(notice.getByText("已取消自动解决", { exact: true })).toBeVisible();
    await page.screenshot({ path: `/artifacts/issue162-cancelled-${width}.png`, fullPage: true });

    status = "REEVALUATING";
    await page.reload();
    await expect(notice.getByText("正在重新评估", { exact: true })).toBeVisible();
    await page.screenshot({
      path: `/artifacts/issue162-reevaluating-${width}.png`,
      fullPage: true,
    });
    status = "RESOLVED";
    await page.reload();
    await expect(notice.getByText("工单已自动解决", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "发送回复", exact: true })).toBeVisible();
    await page.screenshot({ path: `/artifacts/issue162-resolved-${width}.png`, fullPage: true });
    await context.close();
  });
}
