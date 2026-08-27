import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql } from "./support/database";

test("Issue #99 客服真实登录、最小队列、确认领取与撤权清屏", async ({ browser }, testInfo) => {
  const customerContext = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  const customer = await customerContext.newPage();
  await login(customer, "customer", "customer-demo");

  const description = `Issue #99 授权详情 ${crypto.randomUUID()}`;
  await customer.getByLabel("订单编号").fill("ORDER-DELAY-UNDER-24");
  await customer.getByLabel("问题描述").fill(description);
  const createdResponse = customer.waitForResponse(
    (response) =>
      /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(
        new URL(response.url()).pathname,
      ) && response.status() === 201,
  );
  await customer.getByRole("button", { name: "提交物流延迟问题" }).click();
  await expect(customer.getByRole("heading", { name: "请确认我的理解" })).toBeVisible();
  await customer.getByRole("button", { name: "确认，就是这个问题" }).click();
  const created = (await (await createdResponse).json()) as { ticketId: string };
  await customer.getByRole("button", { name: "转人工处理" }).click();
  await customer.getByRole("button", { name: "确认转人工" }).click();
  await expect(customer.getByText("人工客服处理中")).toBeVisible();

  const supportContext = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  const support = await supportContext.newPage();
  let detailReads = 0;
  support.on("request", (request) => {
    if (
      request.method() === "GET" &&
      new URL(request.url()).pathname === `/api/support/workbench/tickets/${created.ticketId}`
    ) {
      detailReads += 1;
    }
  });
  await login(support, "internal", "support-demo");

  const shortTicketId = `${created.ticketId.slice(0, 8)}…${created.ticketId.slice(-4)}`;
  await expect(support.getByText(shortTicketId).first()).toBeVisible();
  await expect(support.getByText(created.ticketId, { exact: true })).toHaveCount(0);
  await expect(support.getByText(description)).toHaveCount(0);
  expect(detailReads).toBe(0);
  await support.screenshot({
    path: testInfo.outputPath("support-minimum-queue.png"),
    fullPage: true,
  });

  await support.setViewportSize({ width: 640, height: 960 });
  const queueScroller = support.locator(".queue-table-wrap").first();
  await expect(queueScroller).toBeVisible();
  await expect
    .poll(() => queueScroller.evaluate((element) => element.scrollWidth > element.clientWidth))
    .toBe(true);
  await expect(support.getByLabel("授权详情等待区")).toHaveCSS("position", "static");

  await support
    .getByRole("button", { name: `领取工单 ${created.ticketId}` })
    .first()
    .click();
  await expect(support.getByRole("dialog", { name: "确认领取工单" })).toBeVisible();
  expect(detailReads).toBe(0);
  await support.getByRole("button", { name: "确认领取" }).click();

  await expect(support.getByRole("heading", { name: "授权工单详情" })).toBeVisible();
  await support.setViewportSize({ width: 1440, height: 960 });
  const basicInformation = support.getByLabel("工单基本信息");
  await expect(basicInformation.getByText("customer-demo", { exact: true })).toBeVisible();
  await expect(basicInformation.getByText("ORDER-DELAY-UNDER-24", { exact: true })).toBeVisible();
  await expect(
    support.getByRole("region", { name: "问题描述" }).getByText(description, { exact: true }),
  ).toBeVisible();
  await expect(support.getByRole("heading", { name: "公开沟通" })).toBeVisible();
  await expect(support.getByRole("heading", { name: "调查事实" })).toBeVisible();
  await expect(support.getByRole("heading", { name: "业务时间线" })).toBeVisible();
  expect(detailReads).toBe(1);
  await support.screenshot({
    path: testInfo.outputPath("support-authorized-detail.png"),
    fullPage: true,
  });

  executeFixtureSql(`
    UPDATE support_assignment
      SET status = 'REVOKED', revoked_at = clock_timestamp()
      WHERE ticket_id = '${created.ticketId}' AND status = 'ACTIVE';
  `);
  await expect(support.getByRole("alert")).toContainText("客服分配已失效", { timeout: 60_000 });
  await expect(support.getByRole("heading", { name: "授权工单详情" })).toHaveCount(0);
  await expect(support.getByText(description, { exact: true })).toHaveCount(0);
  await expect(support.getByLabel("授权详情等待区")).toBeVisible();
  await support.screenshot({
    path: testInfo.outputPath("support-revoked-cleared.png"),
    fullPage: true,
  });

  await supportContext.close();
  await customerContext.close();
});
