import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";
import { executeFixtureSql, queryFixtureSql } from "./support/database";

test("Issue #156 受理协助保持独立责任并由客户最终确认", async ({ browser }) => {
  test.setTimeout(90_000);
  const customerContext = await newIssue80Context(browser, { viewport: { width: 390, height: 844 } });
  const supportContext = await newIssue80Context(browser, { viewport: { width: 1440, height: 900 } });
  const reassignedContext = await newIssue80Context(browser, { viewport: { width: 390, height: 844 } });
  const customer = await customerContext.newPage();
  const support = await supportContext.newPage();
  const reassigned = await reassignedContext.newPage();
  const orderReference = `ORDER-INTAKE-156-${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
  prepareOrder(orderReference);

  try {
    await login(customer, "customer", "customer-demo");
    const intakeResponse = customer.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/customer/v2/intakes" &&
        response.status() === 201,
    );
    await customer.getByLabel("订单编号").fill(orderReference);
    await customer.getByLabel("问题描述").fill("物流一直没有更新，请转人工客服");
    await customer.getByRole("button", { name: "提交物流延迟问题" }).click();
    const intake = (await (await intakeResponse).json()) as { intakeId: string };
    await expect(customer.getByText(/已建立受理协助请求/)).toBeVisible();
    expect(ticketCount(orderReference)).toBe("0");

    const requestId = queryFixtureSql(
      `select id from intake_assistance_request where intake_id = '${intake.intakeId}'::uuid`,
    );
    await login(support, "internal", "support-demo");
    await support.getByRole("button", { name: "受理协助队列" }).click();
    await expect(support.getByRole("heading", { name: "受理协助队列" })).toBeVisible();
    await expect(support.getByText(orderReference)).toHaveCount(0);
    await support.getByRole("button", { name: `领取受理协助 ${requestId}` }).click();
    await expect(support.getByRole("heading", { name: "协助确认受理" })).toBeVisible();

    executeFixtureSql(`
      update intake_assistance_request
      set claim_expires_at = timestamptz '2026-08-09T13:59:59Z'
      where id = '${requestId}'::uuid;
    `);
    await login(reassigned, "internal", "internal-demo");
    await reassigned.goto("/internal/support");
    await expect(reassigned.getByRole("heading", { name: "客服共享队列" })).toBeVisible();
    await reassigned.getByRole("button", { name: "受理协助队列" }).click();
    await reassigned.getByRole("button", { name: `领取受理协助 ${requestId}` }).click();
    await expect(reassigned.getByText("物流一直没有更新，请转人工客服")).toBeVisible();

    await reassigned.getByRole("button", { name: "释放协助" }).click();
    await expect(reassigned.getByRole("heading", { name: "协助确认受理" })).toHaveCount(0);
    await reassigned.getByRole("button", { name: `领取受理协助 ${requestId}` }).click();
    await reassigned.getByLabel("订单候选").selectOption(orderReference);
    await reassigned.getByLabel("物流延迟").check();
    await reassigned.getByLabel("物流延迟摘要").fill("物流多日没有更新");
    await reassigned.getByRole("button", { name: "提交给客户确认" }).click();
    await expect(reassigned.getByText("已提交给客户确认；尚未创建正式工单。")).toBeVisible();
    expect(ticketCount(orderReference)).toBe("0");
    expect(
      queryFixtureSql(
        `select support_id || ':' || coalesce(previous_order_reference, 'NONE') || ':' || ` +
          `jsonb_array_length(previous_issues) || ':' || proposed_order_reference || ':' || ` +
          `(proposed_issues -> 0 ->> 'kind') from intake_assistance_proposal_request ` +
          `where assistance_request_id = '${requestId}'`,
      ),
    ).toBe(`internal-demo:NONE:0:${orderReference}:LOGISTICS_DELAY`);

    await customer.goto(`/help?intake=${intake.intakeId}`);
    await expect(customer.getByRole("heading", { name: "请确认我的理解" })).toBeVisible();
    const confirmResponse = customer.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/customer/v2/intakes/${intake.intakeId}/messages` &&
        response.request().method() === "POST",
    );
    await customer.getByRole("button", { name: "确认，就是这个问题" }).click();
    expect((await confirmResponse).status()).toBe(201);
    await expect(customer.getByText("客服工单", { exact: true })).toBeVisible();
    expect(ticketCount(orderReference)).toBe("1");
    expect(
      queryFixtureSql(
        `select status || ':' || support_id from intake_assistance_request where id = '${requestId}'`,
      ),
    ).toBe("COMPLETED:internal-demo");
    expect(
      await reassigned.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await expect(reassigned.getByRole("heading", { name: "协助确认受理" })).toHaveCount(0, {
      timeout: 60_000,
    });
    await expect(reassigned.getByRole("alert")).toContainText("受理协助权限已撤销");
    expect(
      await reassigned.evaluate(async (completedRequestId) => {
        const response = await fetch(
          `/api/support/intake-assistance/requests/${completedRequestId}`,
          { credentials: "same-origin" },
        );
        return response.status;
      }, requestId),
    ).toBe(404);
  } finally {
    await Promise.all([customer.close(), support.close(), reassigned.close()]);
  }
});

test("Issue #156 受理协助队列呈现 loading、empty 和 error 状态", async ({ browser }) => {
  const context = await newIssue80Context(browser, { viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  let continueSnapshot!: () => void;
  const snapshotGate = new Promise<void>((resolve) => {
    continueSnapshot = resolve;
  });
  await page.route("**/api/support/intake-assistance/snapshot", async (route) => {
    await snapshotGate;
    await route.continue();
  });

  try {
    await login(page, "internal", "support-demo");
    await page.getByRole("button", { name: "受理协助队列" }).click();
    await expect(page.getByText("正在读取受理协助权威快照…")).toBeVisible();
    continueSnapshot();
    await expect(page.getByText("当前没有待处理的受理协助")).toBeVisible();

    await page.unroute("**/api/support/intake-assistance/snapshot");
    await page.route("**/api/support/intake-assistance/snapshot", (route) =>
      route.fulfill({ status: 503, body: "temporarily unavailable" }),
    );
    await page.getByRole("button", { name: "重新同步受理协助" }).click();
    await expect(page.getByRole("alert")).toContainText("受理协助队列加载失败");
  } finally {
    continueSnapshot();
    await page.close();
  }
});

function prepareOrder(orderReference: string) {
  executeFixtureSql(`
    insert into synthetic_order (
      order_reference, customer_id, paid_amount, currency, delay_hours, paid,
      cancelled, fully_refunded, existing_compensation, policy_version,
      available_compensation_amount, delay_seconds
    ) values (
      '${orderReference}', 'customer-demo', 268.00, 'CNY', 80, true,
      false, false, false, 'delay-policy-v1', 268.00, 288000
    );
  `);
}

function ticketCount(orderReference: string) {
  return queryFixtureSql(
    `select count(*) from support_ticket where order_reference = '${orderReference}'`,
  );
}
