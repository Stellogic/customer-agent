import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";

test("Issue #98 客户真实创建、交互状态与断线权威恢复视觉", async ({ browser }) => {
  test.setTimeout(60_000);
  const context = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  const page = await context.newPage();
  let disconnectTicketStream = false;
  await page.route("**/api/customer/tickets/*/events", (route) =>
    disconnectTicketStream
      ? route.fulfill({ status: 503, body: "temporarily unavailable" })
      : route.continue(),
  );

  await login(page, "customer", "customer-demo");
  await expect(page.getByRole("heading", { name: /物流遇到问题/ })).toBeVisible();
  await expect(page.getByLabel("订单编号")).toBeVisible();
  await expect(page.getByLabel("问题描述")).toBeVisible();
  await expect(page.getByLabel(/附件|联系方式|商品详情|承诺时间/)).toHaveCount(0);
  await page.screenshot({ path: "/artifacts/issue98-customer-home.png", fullPage: true });

  const description = `Issue #98 真实浏览器体验 ${crypto.randomUUID()}`;
  await page.getByLabel("订单编号").fill("ORDER-DELAY-UNDER-24");
  await page.getByLabel("问题描述").fill(description);
  const createdResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/customer/tickets") && response.status() === 201,
  );
  await page.getByRole("button", { name: "提交物流延迟问题" }).click();
  const created = (await (await createdResponse).json()) as { ticketId: string };
  const shortTicketId = `${created.ticketId.slice(0, 8)}…${created.ticketId.slice(-4)}`;

  await expect(page.getByRole("heading", { name: shortTicketId })).toBeVisible();
  const handoffButton = page.getByRole("button", { name: "转人工处理" });
  await expect(handoffButton).toBeVisible();
  await handoffButton.click();
  await expect(page.getByRole("dialog", { name: "确认转人工处理" })).toBeVisible();
  await page.getByRole("button", { name: "确认转人工" }).click();
  await expect(page.getByText("人工客服处理中")).toBeVisible();
  await expect(handoffButton).toHaveCount(0);

  await expect(page.getByText("调查中", { exact: true })).toBeVisible();
  await expect(page.getByText(description)).toBeVisible();
  await expect(page.getByText(created.ticketId, { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "复制完整工单编号" })).toBeVisible();
  await page.screenshot({ path: "/artifacts/issue98-customer-ticket.png", fullPage: true });

  disconnectTicketStream = true;
  await page.reload();
  await expect(page.getByRole("heading", { name: "正在重新同步工单" })).toBeVisible();
  await expect(page.getByText(`工单 ${shortTicketId}`)).toBeVisible();
  await expect(page.getByText(description)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "提交物流延迟问题" })).toHaveCount(0);
  await page.screenshot({ path: "/artifacts/issue98-connection-recovery.png", fullPage: true });

  await context.close();
});
