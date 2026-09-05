import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { queryFixtureSql } from "./support/database";
import { createSingleTicket, prepareOrder } from "./support/issue173-intake";

test("Issue #174 L174-04：真实客户知识引用与客服辅助", async ({ browser }) => {
  test.setTimeout(180_000);
  const customerContext = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  const supportContext = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  try {
    const customer = await customerContext.newPage();
    await login(customer, "customer", "customer-demo");
    const publicReference = prepareOrder();
    const publicTicket = await createSingleTicket(
      customer,
      publicReference,
      "物流节点超过承诺时间没有更新时该怎么处理？请说明依据并展示来源。",
    );
    await expect
      .poll(
        () =>
          queryFixtureSql(`
          SELECT status FROM agent_processing_generation
          WHERE ticket_id = '${publicTicket}' ORDER BY generation_number DESC LIMIT 1;
        `),
        { timeout: 90_000 },
      )
      .toBe("COMPLETED");
    const customerEvidence = JSON.parse(
      queryFixtureSql(`
      SELECT json_build_object('body', body, 'knowledge', knowledge)
      FROM public_message
      WHERE ticket_id = '${publicTicket}' AND author = 'AGENT'
      ORDER BY message_sequence DESC LIMIT 1;
    `),
    ) as { body: string; knowledge: { status: string; sources: unknown[] } };
    expect(customerEvidence.knowledge.status).toBe("SUPPORTED");
    expect(customerEvidence.knowledge.sources).toHaveLength(1);
    expect(customerEvidence.body).toMatch(/物流|配送/);
    expect(customerEvidence.body).toMatch(/节点|时间|核对|说明/);
    await expect(customer.getByText("配送问题的信息补充指南", { exact: true })).toBeVisible();
    await expect(customer.locator(".customer-knowledge-sources time").first()).toHaveAttribute(
      "datetime",
      "2026-09-01T00:00:00Z",
    );

    const humanReference = prepareOrder();
    await customer.goto("/help");
    const humanTicket = await createSingleTicket(
      customer,
      humanReference,
      "物流延迟，请人工客服处理本工单，并说明适用政策。",
    );
    await expect(customer.getByText("人工客服处理中", { exact: true })).toBeVisible({
      timeout: 90_000,
    });
    const support = await supportContext.newPage();
    await login(support, "internal", "support-demo");
    await support
      .getByRole("table", { name: "待接手工单", exact: true })
      .getByRole("button", { name: `领取工单 ${humanTicket}`, exact: true })
      .click();
    await support.getByRole("button", { name: "确认领取", exact: true }).click();
    const assistance = support.getByRole("region", { name: "客服辅助入口" });
    await assistance
      .getByLabel("辅助查询（最多200字）")
      .fill("物流节点超过承诺时间没有更新时该怎么处理？请给出处。");
    const beforeMessages = queryFixtureSql(
      `SELECT count(*) FROM public_message WHERE ticket_id = '${humanTicket}';`,
    );
    const requested = support.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname ===
          `/api/support/workbench/tickets/${humanTicket}/assistance/requests`,
    );
    await assistance.getByRole("button", { name: "政策查询", exact: true }).click();
    const response = await requested;
    const responseText = await response.text();
    expect(response.status(), responseText).toBe(200);
    const result = JSON.parse(responseText) as {
      view: {
        status: string;
        text?: string;
        citations?: Array<{
          articleId: string;
          version: string;
          title: string;
          updatedAt: string;
          snippet: string;
        }>;
      };
    };
    expect(result.view.status).toBe("ready");
    expect(result.view.text).toMatch(/物流|订单/);
    expect(result.view.text).toMatch(/核对|节点|延迟/);
    expect(result.view.citations).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          articleId: "logistics-delay",
          version: "v2",
          title: "物流延迟处理说明",
          updatedAt: "2026-08-28T00:00:00Z",
          snippet: expect.stringMatching(/核对订单与物流|物流节点超过承诺时间/),
        }),
      ]),
    );
    await expect(assistance.getByRole("alert")).toHaveCount(0);
    await expect(assistance.getByText("物流延迟处理说明", { exact: true })).toBeVisible();
    expect(
      queryFixtureSql(`SELECT count(*) FROM public_message WHERE ticket_id = '${humanTicket}';`),
    ).toBe(beforeMessages);
    await expect(support.getByRole("textbox", { name: "公开回复", exact: true })).toBeEnabled();
  } finally {
    await supportContext.close();
    await customerContext.close();
  }
});

test("Issue #174 L174-05：签收未收到安全转人工且无补偿副作用", async ({ browser }) => {
  test.setTimeout(120_000);
  const reference = prepareOrder({ logisticsStatus: "SIGNED" });
  const context = await newAcceptanceContext(browser, { viewport: { width: 390, height: 844 } });
  try {
    const page = await context.newPage();
    await login(page, "customer", "customer-demo");
    const ticketId = await createSingleTicket(
      page,
      reference,
      "物流页面显示已签收，但我实际没有收到包裹，请核实后处理，不要直接赔付。",
    );
    await expect(page.getByText("人工客服处理中", { exact: true })).toBeVisible({
      timeout: 90_000,
    });
    expect(
      queryFixtureSql(`
      SELECT handling_mode || ':' || lifecycle_state || ':' || human_handoff_reason_code
      FROM support_ticket WHERE id = '${ticketId}';
    `),
    ).toBe("HUMAN:INVESTIGATING:PACKAGE_SIGNED_NOT_RECEIVED");
    expect(
      queryFixtureSql(`
      SELECT (SELECT count(*) FROM compensation_proposal_revision WHERE ticket_id = '${ticketId}') || ':' ||
             (SELECT count(*) FROM compensation_execution execution
               JOIN compensation_proposal_revision revision
                 ON revision.id = execution.proposal_revision_id
              WHERE revision.ticket_id = '${ticketId}');
    `),
    ).toBe("0:0");
    await page.reload();
    await expect(page.getByText("人工客服处理中", { exact: true })).toBeVisible();
  } finally {
    await context.close();
  }
});
