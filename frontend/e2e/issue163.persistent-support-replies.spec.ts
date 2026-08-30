import { expect, test } from "@playwright/test";
import { continueAsNewIfDuplicate, login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql, revokeActiveAssignmentsForSupport } from "./support/database";

test("Issue #163 持久化领取、人工公开回复与刷新恢复", async ({ browser }) => {
  test.setTimeout(90_000);
  const customerContext = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  const customer = await customerContext.newPage();
  await login(customer, "customer", "customer-demo");

  const description = `Issue #163 持久化回复 ${crypto.randomUUID()}`;
  const replyBody = `负责客服公开回复 ${crypto.randomUUID().slice(0, 8)}`;
  await customer.getByLabel("订单编号").fill("ORDER-DELAY-UNDER-24");
  await customer.getByLabel("问题描述").fill(description);
  const createdResponse = customer.waitForResponse(
    (response) =>
      /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(
        new URL(response.url()).pathname,
      ) && response.status() === 201,
  );
  await customer.getByRole("button", { name: "提交物流延迟问题" }).click();
  await continueAsNewIfDuplicate(customer);
  await customer.getByRole("button", { name: "确认，就是这个问题" }).click();
  const created = (await (await createdResponse).json()) as { ticketId: string };
  await customer.getByRole("button", { name: "转人工处理" }).click();
  await customer.getByRole("button", { name: "确认转人工" }).click();
  await expect(customer.getByText("人工客服处理中")).toBeVisible();

  revokeActiveAssignmentsForSupport("support-demo");
  const supportContext = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  const support = await supportContext.newPage();
  await login(support, "internal", "support-demo");
  await expect(support.getByRole("heading", { name: "客服共享队列" })).toBeVisible();
  await expect(support.getByText(description)).toHaveCount(0);

  await support.setViewportSize({ width: 640, height: 960 });
  const queueScroller = support.locator(".queue-table-wrap").first();
  await expect(queueScroller).toBeVisible();
  await expect
    .poll(() => queueScroller.evaluate((element) => element.scrollWidth > element.clientWidth))
    .toBe(true);
  await expect(support.getByLabel("授权详情等待区")).toHaveCSS("position", "static");

  await support.getByRole("button", { name: `领取工单 ${created.ticketId}` }).first().click();
  await expect(support.getByRole("dialog", { name: "确认领取工单" })).toBeVisible();
  await support.getByRole("button", { name: "确认领取" }).click();
  await expect(support.getByRole("heading", { name: "授权工单详情" })).toBeVisible();
  await expect(support.locator(".support-ticket-detail")).toHaveCSS("position", "static");
  await expect(support.getByRole("heading", { name: "人工公开回复" })).toBeVisible();
  await expect(support.getByRole("button", { name: "释放领取" })).toBeVisible();
  await support.setViewportSize({ width: 1440, height: 960 });
  await expect(support.getByRole("heading", { name: "授权工单详情" })).toBeVisible();
  await expect(support.getByRole("heading", { name: "人工公开回复" })).toBeVisible();
  await support.getByRole("textbox", { name: "公开回复" }).fill(replyBody);
  await support.getByRole("button", { name: "发送公开回复" }).click();
  await expect(support.getByText("公开回复已由 Spring 保存并对客户可见。")).toBeVisible();
  await expect(support.getByText(replyBody, { exact: true })).toBeVisible();

  await expect(customer.getByText(replyBody, { exact: true })).toBeVisible();
  await expect(
    customer.locator(".ant-bubble").filter({ hasText: replyBody }).locator(".ant-bubble-header"),
  ).toHaveText("客服");

  await support.reload();
  await expect(support.getByRole("heading", { name: "授权工单详情" })).toBeVisible();
  await expect(
    support.getByRole("region", { name: "问题描述" }).getByText(description, { exact: true }),
  ).toBeVisible();
  await expect(support.getByText(replyBody, { exact: true })).toBeVisible();
  await expect(support.getByRole("heading", { name: "人工公开回复" })).toBeVisible();

  const otherContext = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  const other = await otherContext.newPage();
  await login(other, "internal", "internal-demo");
  await expect(other.getByRole("heading", { name: "客服共享队列" })).toBeVisible();
  await expect(other.getByText(description, { exact: true })).toHaveCount(0);
  await expect(other.getByRole("heading", { name: "授权工单详情" })).toHaveCount(0);
  await expect(other.getByRole("button", { name: `领取工单 ${created.ticketId}` })).toHaveCount(0);

  executeFixtureSql(`
    UPDATE support_assignment
      SET status = 'REVOKED', revoked_at = clock_timestamp()
      WHERE ticket_id = '${created.ticketId}' AND status = 'ACTIVE';
  `);
  await expect(support.getByRole("alert")).toContainText("客服分配已失效", { timeout: 60_000 });
  await expect(support.getByRole("heading", { name: "授权工单详情" })).toHaveCount(0);
  await expect(support.getByText(replyBody, { exact: true })).toHaveCount(0);

  await otherContext.close();
  await supportContext.close();
  await customerContext.close();
});
