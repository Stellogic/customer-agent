import { expect, test, type Page } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql } from "./support/database";

// 隔离静态准备，尚未运行或登记公共门禁；完整 AC 与待接线项见 issue-173-acceptance-plan.md。
// SQL 只准备独有订单，不预造工单、回复、代次、领取、提案或审批结果。
function prepareOrder() {
  const reference = `ORDER-ISSUE-173-${crypto.randomUUID()}`;
  executeFixtureSql(`
    INSERT INTO synthetic_order (
      order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
      paid, cancelled, fully_refunded, existing_compensation, policy_version,
      available_compensation_amount
    ) VALUES (
      '${reference}', 'customer-demo', 268.00, 'CNY', 80, 288000,
      true, false, false, false, 'delay-policy-v1', 268.00
    );
  `);
  return reference;
}

function intakeReply(page: Page) {
  return page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(response.url()).pathname),
  );
}

async function createSingleTicket(page: Page, reference: string, description: string) {
  await page.getByLabel("订单编号").fill(reference);
  await page.getByLabel("问题描述").fill(description);
  await page.getByRole("button", { name: "提交物流延迟问题" }).click();
  await expect(page.getByRole("heading", { name: "请确认我的理解" })).toBeVisible();
  const confirmed = intakeReply(page);
  await page.getByRole("button", { name: "确认，就是这个问题" }).click();
  const response = await confirmed;
  expect(response.status()).toBe(201);
  const result = (await response.json()) as { ticketId: string; confirmed: boolean };
  expect(result.confirmed).toBe(true);
  expect(result.ticketId).toMatch(/^[0-9a-f-]{36}$/i);
  return result.ticketId;
}

test("Issue #173 A：自然语言多问题澄清、一次建单与订单分组恢复", async ({ browser }) => {
  test.setTimeout(90_000);
  const reference = prepareOrder();
  const context = await newAcceptanceContext(browser, { viewport: { width: 390, height: 844 } });
  try {
    const page = await context.newPage();
    await login(page, "customer", "customer-demo");
    await page.getByLabel("问题描述").fill(`${reference} 的包裹没收到，而且疑似重复扣款`);
    await page.getByRole("button", { name: "提交物流延迟问题" }).click();
    await expect(page.getByRole("heading", { name: "再帮我确认一点" })).toBeVisible();
    await expect(page.getByRole("button", { name: /原子创建/ })).toHaveCount(0);
    await page.getByLabel("补充受理信息").fill("是的，确实重复扣款");
    await page.getByRole("button", { name: "发送给智能受理" }).click();
    await expect(page.getByRole("heading", { name: "请确认 2 个问题" })).toBeVisible();
    await expect(page.getByRole("article", { name: /拟建工单/ })).toHaveCount(2);

    const confirmed = intakeReply(page);
    await page.getByRole("button", { name: "确认并原子创建 2 张工单" }).click();
    const response = await confirmed;
    expect(response.status()).toBe(201);
    const result = (await response.json()) as { ticketIds: string[]; sharedIntakeRecordId: string };
    expect(result.ticketIds).toHaveLength(2);
    expect(new Set(result.ticketIds).size).toBe(2);
    expect(result.sharedIntakeRecordId).toMatch(/^[0-9a-f-]{36}$/i);
    await expect(page.getByRole("heading", { name: "2 张工单已创建" })).toBeVisible();

    await page.goto("/help");
    await page.reload();
    const overview = page.getByRole("region", { name: "订单工单总览" });
    await expect(overview.getByRole("heading", { name: `订单 ${reference}` })).toBeVisible();
    for (const ticketId of result.ticketIds) {
      await expect(overview.getByRole("button", { name: `打开工单 ${ticketId}`, exact: true })).toBeVisible();
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
  } finally {
    await context.close();
  }
});

test("Issue #173 B：真实调查后连续追加消息并从断线恢复同一工单", async ({ browser }) => {
  test.setTimeout(120_000);
  const reference = prepareOrder();
  const context = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 960 } });
  try {
    const page = await context.newPage();
    await login(page, "customer", "customer-demo");
    const ticketId = await createSingleTicket(page, reference, "物流延迟，请核实订单后说明处理方案。");
    // 等真实 Agent 经 Spring 形成待审批结果；不注入完成事件或补偿提案。
    await expect(page.getByRole("heading", { name: "待审批", exact: true })).toBeVisible({
      timeout: 60_000,
    });
    const messages = ["补充：物流页面今天仍未更新。", "再次补充：请在此工单继续说明物流进展。"];
    for (const message of messages) {
      await page.getByPlaceholder("继续补充消息", { exact: true }).fill(message);
      const accepted = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/customer/v2/tickets/${ticketId}/messages`,
      );
      await page.getByRole("button", { name: "发送新消息" }).click();
      const response = await accepted;
      expect(response.ok()).toBe(true);
      expect(await response.json()).toMatchObject({
        schema: "public-conversation-v2",
        ticketId,
        accepted: true,
        replayed: false,
      });
      await expect(page.getByText(message, { exact: true })).toHaveCount(1);
      await expect(page.getByRole("button", { name: "发送新消息" })).toBeEnabled();
    }

    // 只中断传输，不伪造 Spring 响应。恢复仍由真实快照与 SSE 完成。
    let disconnected = true;
    await page.route(`**/api/customer/v2/tickets/${ticketId}/events`, (route) =>
      disconnected ? route.abort("connectionreset") : route.continue(),
    );
    await page.reload();
    await expect(page.getByRole("heading", { name: "正在重新同步工单" })).toBeVisible();
    for (const message of messages) {
      await expect(page.getByText(message, { exact: true })).toHaveCount(0);
    }
    disconnected = false;
    await page.getByRole("button", { name: "立即重试同步" }).click();
    for (const message of messages) {
      await expect(page.getByText(message, { exact: true })).toBeVisible();
      await expect(page.getByText(message, { exact: true })).toHaveCount(1);
    }
    await expect(page.getByRole("heading", { name: "正在重新同步工单" })).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: `${ticketId.slice(0, 8)}…${ticketId.slice(-4)}`, exact: true }),
    ).toBeVisible();
  } finally {
    await context.close();
  }
});

test("Issue #173 C：人工领取与公开回复、标准补偿提交和独立审批", async ({ browser }) => {
  test.setTimeout(120_000);
  const reference = prepareOrder();
  const customerContext = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 960 } });
  const supportContext = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 960 } });
  const approverContext = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 960 } });
  try {
    const customer = await customerContext.newPage();
    await login(customer, "customer", "customer-demo");
    const description = `物流延迟，请人工客服处理本工单。${reference}`;
    const ticketId = await createSingleTicket(customer, reference, description);
    await expect(customer.getByText("人工客服处理中", { exact: true })).toBeVisible({
      timeout: 60_000,
    });

    const support = await supportContext.newPage();
    await login(support, "internal", "support-demo");
    await expect(support.getByRole("heading", { name: "客服共享队列" })).toBeVisible();
    await expect(support.getByText(description, { exact: true })).toHaveCount(0);
    await support.getByRole("table", { name: "待接手工单", exact: true })
      .getByRole("button", { name: `领取工单 ${ticketId}`, exact: true }).click();
    await support.getByRole("button", { name: "确认领取", exact: true }).click();
    await expect(support.getByRole("heading", { name: "人工公开回复" })).toBeVisible();
    const reply = `已收到您的补充，正在核实物流。${crypto.randomUUID()}`;
    await support.getByRole("textbox", { name: "公开回复", exact: true }).fill(reply);
    await support.getByRole("button", { name: "发送公开回复" }).click();
    await expect(customer.getByText(reply, { exact: true })).toBeVisible();
    await expect(
      customer.locator(".ant-bubble").filter({ hasText: reply }).locator(".ant-bubble-header"),
    ).toHaveText("客服");
    await support.reload();
    await expect(support.getByRole("heading", { name: "授权工单详情" })).toBeVisible();
    // 同一演示客服可能保留其他场景的领取；从真实已领取列表选回本票，不撤销他票责任。
    const assignedTicket = support.getByRole("button", { name: `打开已领取工单 ${ticketId}`, exact: true });
    if (await assignedTicket.isVisible()) await assignedTicket.click();
    await expect(
      support.getByRole("region", { name: "问题描述" }).getByText(description, { exact: true }),
    ).toBeVisible();
    await expect(support.getByText(reply, { exact: true })).toBeVisible();

    const compensation = support.getByRole("region", { name: "标准补偿", exact: true });
    await expect(compensation.getByRole("combobox", { name: "补偿方案" })).toContainText(
      "模拟原路部分退款 · 26.80 CNY",
    );
    const proposed = support.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/support/workbench/tickets/${ticketId}/compensation-proposals`,
    );
    await compensation.getByRole("button", { name: "提交审批", exact: true }).click();
    const response = await proposed;
    expect(response.ok()).toBe(true);
    const proposal = (await response.json()) as { proposalRevisionId: string };
    expect(proposal.proposalRevisionId).toMatch(/^[0-9a-f-]{36}$/i);
    const pending = customer.locator(".pending-compensation-card");
    await expect(pending.getByRole("heading", { name: "待审批", exact: true })).toBeVisible();
    await expect(pending.getByText("26.80 CNY", { exact: true })).toBeVisible();
    await expect(pending).toContainText("现在还没有批准或执行补偿");
    await customer.setViewportSize({ width: 390, height: 844 });
    await expect(pending.getByText("26.80 CNY", { exact: true })).toBeVisible();

    // 批准后模拟执行可能立即解决工单；先释放本票领取，避免与正常执行收尾争抢控件。
    await support.getByRole("button", { name: "释放领取", exact: true }).click();
    await expect(support.getByText(description, { exact: true })).toHaveCount(0);
    await expect(support.getByText(reply, { exact: true })).toHaveCount(0);

    const approver = await approverContext.newPage();
    await login(approver, "internal", "approver-demo");
    const row = approver.getByRole("row").filter({
      has: approver.locator(`code[title="${proposal.proposalRevisionId}"]`),
    });
    await row.getByRole("button", { name: "领取审批", exact: true }).click();
    await expect(approver.getByRole("heading", { name: reference, exact: true })).toBeVisible();
    await expect(approver.getByText(reply, { exact: true })).toHaveCount(0);
    await approver.getByRole("button", { name: "批准补偿", exact: true }).click();
    const approved = approver.waitForResponse(
      (result) =>
        result.request().method() === "POST" &&
        new URL(result.url()).pathname === `/api/approver/compensation-proposals/${proposal.proposalRevisionId}/approve`,
    );
    await approver.getByRole("dialog", { name: "确认批准补偿" })
      .getByRole("button", { name: "确认批准", exact: true }).click();
    expect((await approved).ok()).toBe(true);
    await expect(approver.getByText("审批责任已结束，已返回队列。", { exact: true })).toBeVisible();
    await expect(approver.getByRole("heading", { name: reference, exact: true })).toHaveCount(0);
    await expect(row).toHaveCount(0);
    // 审批受理不等于执行成功；执行/待对账以及撤权竞态仍在计划中等待接线。
  } finally {
    await approverContext.close();
    await supportContext.close();
    await customerContext.close();
  }
});
