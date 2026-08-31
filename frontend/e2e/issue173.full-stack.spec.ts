import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { queryFixtureSql } from "./support/database";
import { createSingleTicket, intakeReply, prepareOrder } from "./support/issue173-intake";

// 已登记串行门禁，仍未运行；完整 AC 与待接线项见 issue-173-acceptance-plan.md。

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

test("Issue #173 D：真实低风险回复产生五分钟候选，刷新后仍可取消", async ({ browser }) => {
  test.setTimeout(90_000);
  const reference = prepareOrder({ delayHours: 23 });
  const context = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 960 } });
  try {
    const page = await context.newPage();
    await login(page, "customer", "customer-demo");
    // 使用 #162 的真实白名单问句；不把任意物流诉求或模型置信度当作自动解决资格。
    const ticketId = await createSingleTicket(page, reference, "请解释物流状态");
    const notice = page.getByRole("region", { name: "自动解决状态" });
    const cancel = notice.getByRole("button", { name: "仍需帮助，取消自动解决" });
    await expect(cancel).toBeVisible({ timeout: 60_000 });
    const candidate = JSON.parse(queryFixtureSql(`
      SELECT json_build_object('waitSeconds', extract(epoch FROM due_at - created_at)::integer, 'dueAt', due_at)
      FROM ticket_auto_resolution WHERE ticket_id = '${ticketId}' AND status = 'PENDING';
    `)) as { waitSeconds: number; dueAt: string };
    expect(candidate.waitSeconds).toBe(300);

    const reloaded = page.waitForResponse(
      (response) => response.request().method() === "GET" &&
        new URL(response.url()).pathname === `/api/customer/v2/tickets/${ticketId}`,
    );
    await page.reload();
    const response = await reloaded;
    expect(response.ok()).toBe(true);
    const snapshot = await response.json();
    expect(snapshot).toMatchObject({
      ticket: { id: ticketId, lifecycleState: "INVESTIGATING", handlingMode: "AGENT" },
      autoResolution: { status: "PENDING" },
    });
    expect(Date.parse(snapshot.autoResolution.dueAt)).toBe(Date.parse(candidate.dueAt));
    // 默认 Compose 固定 Spring 时钟，浏览器可能已显示“正在重新核验”；不由浏览器归零断言解决。
    await expect(cancel).toBeVisible();
    const cancelled = page.waitForResponse(
      (result) => result.request().method() === "POST" &&
        new URL(result.url()).pathname === `/api/customer/tickets/${ticketId}/auto-resolution/cancel`,
    );
    await cancel.click();
    const cancelResponse = await cancelled;
    expect(cancelResponse.ok()).toBe(true);
    expect(cancelResponse.request().postDataJSON()).toEqual({
      candidateDueAt: snapshot.autoResolution.dueAt,
      candidateGeneration: snapshot.ticket.agentGeneration,
    });
    await expect(notice.getByText("已取消自动解决", { exact: true })).toBeVisible();
    await page.reload();
    await expect(notice.getByText("已取消自动解决", { exact: true })).toBeVisible();
    expect(queryFixtureSql(`
      SELECT t.lifecycle_state || ':' || a.status
      FROM support_ticket t JOIN ticket_auto_resolution a ON a.ticket_id = t.id
      WHERE t.id = '${ticketId}';
    `)).toBe("INVESTIGATING:CANCELLED");
  } finally {
    await context.close();
  }
});

test("Issue #173 E：同订单两提案竞争30元额度，只允许一笔26.80元批准", async ({ browser }) => {
  test.setTimeout(150_000);
  const reference = prepareOrder({ allowance: 30 });
  const customerContext = await newAcceptanceContext(browser);
  const supportContext = await newAcceptanceContext(browser);
  const approverContext = await newAcceptanceContext(browser);
  try {
    const customer = await customerContext.newPage();
    await login(customer, "customer", "customer-demo");
    const ticketIds: string[] = [];
    for (const description of ["物流延迟，请人工客服核实。", "物流延迟，请人工客服继续处理新问题。"]) {
      await customer.goto("/help");
      ticketIds.push(await createSingleTicket(customer, reference, description));
      await expect(customer.getByText("人工客服处理中", { exact: true })).toBeVisible({ timeout: 60_000 });
    }
    expect(new Set(ticketIds).size).toBe(2);

    const supportPages = [await supportContext.newPage(), await supportContext.newPage()];
    await login(supportPages[0], "internal", "support-demo");
    await supportPages[1].goto("/internal/support");
    for (const [index, page] of supportPages.entries()) {
      await page.getByRole("table", { name: "待接手工单", exact: true })
        .getByRole("button", { name: `领取工单 ${ticketIds[index]}`, exact: true }).click();
      await page.getByRole("button", { name: "确认领取", exact: true }).click();
      await expect(page.locator(".support-ticket-detail").getByText(
        `${ticketIds[index].slice(0, 8)}…${ticketIds[index].slice(-4)}`, { exact: true },
      )).toBeVisible();
      await expect(page.getByRole("region", { name: "标准补偿", exact: true })
        .getByRole("combobox", { name: "补偿方案" })).toContainText("26.80 CNY");
    }
    const proposals = await Promise.all(supportPages.map(async (page, index) => {
      const proposed = page.waitForResponse(
        (response) => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/support/workbench/tickets/${ticketIds[index]}/compensation-proposals`,
      );
      await page.getByRole("button", { name: "提交审批", exact: true }).click();
      const response = await proposed;
      expect(response.status()).toBe(201);
      const proposal = (await response.json()) as { proposalRevisionId: string };
      expect(proposal.proposalRevisionId).toMatch(/^[0-9a-f-]{36}$/i);
      return proposal;
    }));
    expect(new Set(proposals.map((proposal) => proposal.proposalRevisionId)).size).toBe(2);
    expect(queryFixtureSql(`
      SELECT pending_proposal_amount = 53.60 AND active_reservation_amount = 0 AND consumed_amount = 0
      FROM order_compensation_allowance WHERE order_reference = '${reference}';
    `)).toBe("t");
    // 与 C 相同，在批准可能触发自动执行前释放本场景领取；不撤销其他场景的客服责任。
    for (const page of supportPages) {
      await page.getByRole("button", { name: "释放领取", exact: true }).click();
    }

    const approverPages = [await approverContext.newPage(), await approverContext.newPage()];
    await login(approverPages[0], "internal", "approver-demo");
    await approverPages[1].goto("/internal/approvals");
    for (const [index, page] of approverPages.entries()) {
      await page.getByRole("row").filter({
        has: page.locator(`code[title="${proposals[index].proposalRevisionId}"]`),
      }).getByRole("button", { name: "领取审批", exact: true }).click();
      await expect(page.getByRole("heading", { name: reference, exact: true })).toBeVisible();
      await page.getByRole("button", { name: "批准补偿", exact: true }).click();
      await expect(page.getByRole("dialog", { name: "确认批准补偿" })).toBeVisible();
    }

    // 两个真实 UI 请求都到达后再同时放行；只延迟传输，不替换请求、响应或服务端锁。
    let readyCount = 0;
    let releaseRequests: () => void = () => {};
    const bothReady = new Promise<void>((resolve) => { releaseRequests = resolve; });
    for (const [index, page] of approverPages.entries()) {
      await page.route(`**/api/approver/compensation-proposals/${proposals[index].proposalRevisionId}/approve`, async (route) => {
        readyCount += 1;
        if (readyCount === 2) releaseRequests();
        await bothReady;
        await route.continue();
      });
    }
    const approvals = await Promise.all(approverPages.map(async (page, index) => {
      const approved = page.waitForResponse(
        (response) => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/approver/compensation-proposals/${proposals[index].proposalRevisionId}/approve`,
      );
      await page.getByRole("dialog", { name: "确认批准补偿" })
        .getByRole("button", { name: "确认批准", exact: true }).click();
      return approved;
    }));
    expect(approvals.map((response) => response.status()).sort()).toEqual([200, 409]);
    for (const page of approverPages) {
      await expect(page.getByRole("heading", { name: reference, exact: true })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "批准补偿", exact: true })).toHaveCount(0);
    }
    // 执行可能仍在预占，也可能已经消费；互斥汇总应始终只占26.80，剩余3.20，执行记录只有一笔。
    expect(queryFixtureSql(`
      SELECT active_reservation_amount + consumed_amount = 26.80
        AND total_available_compensation_amount - active_reservation_amount = 3.20
        AND (SELECT count(*) FROM compensation_execution WHERE order_reference = '${reference}') = 1
      FROM order_compensation_allowance WHERE order_reference = '${reference}';
    `)).toBe("t");
  } finally {
    await approverContext.close();
    await supportContext.close();
    await customerContext.close();
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
