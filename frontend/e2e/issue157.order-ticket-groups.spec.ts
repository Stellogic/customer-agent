import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";
import { executeFixtureSql, queryFixtureSql } from "./support/database";

const orderReference = "ORDER-ISSUE-157-GROUP";
const raceTicketA = "15710000-0000-0000-0000-000000000001";
const raceTicketB = "15710000-0000-0000-0000-000000000002";
const raceGenerationB = "15710000-0000-0000-0000-000000000102";

test("Issue #157 同订单工单独立启动、分组导航与领取隔离", async ({ browser, request }) => {
  executeFixtureSql(`
    INSERT INTO synthetic_order (
      order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
      paid, cancelled, fully_refunded, existing_compensation, policy_version,
      available_compensation_amount
    ) VALUES (
      '${orderReference}', 'customer-demo', 268.00, 'CNY', 80, 288000,
      true, false, false, false, 'delay-policy-v1', 268.00
    ) ON CONFLICT (order_reference) DO NOTHING;
    INSERT INTO support_ticket (
      id, customer_id, order_reference, description, issue_kind, lifecycle_state,
      handling_mode, created_at, first_responded_at, resolution_running_since
    ) VALUES
      ('${raceTicketA}', 'customer-demo', 'ORDER-DELAY-AMBIGUOUS', 'issue157-race-a',
       'LOGISTICS_DELAY', 'INVESTIGATING', 'AGENT', now(), now(), now()),
      ('${raceTicketB}', 'customer-demo', 'ORDER-DELAY-AMBIGUOUS', 'issue157-race-b',
       'LOGISTICS_DELAY', 'INVESTIGATING', 'AGENT', now(), now(), now());
    INSERT INTO agent_processing_generation (
      id, ticket_id, generation_number, thread_id, status, created_at
    ) VALUES
      ('15710000-0000-0000-0000-000000000101', '${raceTicketA}', 1,
       '15710000-0000-0000-0000-000000000201', 'ACTIVE', now()),
      ('${raceGenerationB}', '${raceTicketB}', 1,
       '15710000-0000-0000-0000-000000000202', 'ACTIVE', now());
    INSERT INTO public_message (id, ticket_id, message_sequence, author, body, sent_at) VALUES
      ('15710000-0000-0000-0000-000000000301', '${raceTicketA}', 1, 'CUSTOMER', 'issue157-race-a', now()),
      ('15710000-0000-0000-0000-000000000302', '${raceTicketB}', 1, 'CUSTOMER', 'issue157-race-b', now());
  `);

  const customerContext = await newIssue80Context(browser, {
    viewport: { width: 1440, height: 900 },
  });
  const customer = await customerContext.newPage();
  await login(customer, "customer", "customer-demo");
  await customer
    .getByLabel("问题描述")
    .fill(`${orderReference} 的包裹至今没收到，而且确实重复扣款`);
  await customer.getByRole("button", { name: "提交物流延迟问题" }).click();
  await expect(customer.getByRole("heading", { name: "请确认 2 个问题" })).toBeVisible();
  const createdResponse = customer.waitForResponse(
    (response) =>
      /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(response.url()).pathname) &&
      response.status() === 201,
  );
  await customer.getByRole("button", { name: "确认并原子创建 2 张工单" }).click();
  const created = (await (await createdResponse).json()) as { ticketIds: string[] };
  expect(created.ticketIds).toHaveLength(2);

  const ticketList = created.ticketIds.map((ticketId) => `'${ticketId}'`).join(",");
  await expect
    .poll(() =>
      queryFixtureSql(`
        SELECT count(*)
          FROM agent_processing_generation g
          JOIN agent_submission s ON s.generation_id = g.id
          WHERE g.ticket_id IN (${ticketList});
      `),
    )
    .toBe("2");
  expect(
    queryFixtureSql(`
      SELECT count(DISTINCT thread_id)
        FROM agent_processing_generation
        WHERE ticket_id IN (${ticketList});
    `),
  ).toBe("2");

  await customer.goto("/help");
  const overview = customer.getByRole("region", { name: "订单工单总览" });
  await expect(overview).toBeVisible();
  const orderGroup = customer
    .getByRole("heading", { name: `订单 ${orderReference}` })
    .locator("..")
    .locator("..");
  await expect(customer.getByRole("heading", { name: `订单 ${orderReference}` })).toBeVisible();
  await expect(customer.getByText("包裹未收到", { exact: true })).toBeVisible();
  await expect(customer.getByText("重复扣款", { exact: true })).toBeVisible();
  await expect(orderGroup).toContainText("2 张独立工单");
  await customer.setViewportSize({ width: 390, height: 844 });
  expect(
    await customer.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);

  const customerHandoff = customer.evaluate(async (ticketId) => {
    const csrf = (await (
      await fetch("/api/auth/csrf", { credentials: "same-origin", cache: "no-store" })
    ).json()) as { token: string; headerName: string };
    const response = await fetch(`/api/customer/tickets/${ticketId}/human-handoff`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": "issue157-concurrent-customer-handoff",
        [csrf.headerName]: csrf.token,
      },
      body: JSON.stringify({ reasonCode: "CUSTOMER_REQUESTED" }),
    });
    return response.status;
  }, raceTicketA);
  const agentClarification = request.post(
    `http://backend:8080/internal/agent/tickets/${raceTicketB}/generations/${raceGenerationB}/clarifications`,
    {
      headers: {
        Authorization: "Bearer local-agent-machine",
        "X-Agent-Generation-Id": raceGenerationB,
        "X-Agent-Operation": "CREATE_CUSTOMER_CLARIFICATION",
        "Idempotency-Key": "issue157-concurrent-agent-clarification",
      },
      data: {
        reasonCode: "ORDER_AMBIGUOUS",
        customerReply: {
          schemaVersion: "customer-reply-v1",
          body: "为确认需要调查的订单，请回复订单确认码（A 或 B）。",
          intent: "CLARIFICATION_REQUIRED",
          evidenceRefs: [],
          escalationRequired: false,
          referencedOrder: "ORDER-DELAY-AMBIGUOUS",
        },
      },
    },
  );
  const [handoffStatus, clarificationResponse] = await Promise.all([
    customerHandoff,
    agentClarification,
  ]);
  expect(handoffStatus).toBe(202);
  expect(clarificationResponse.status()).toBe(200);
  expect(
    queryFixtureSql(`
      SELECT id || ':' || lifecycle_state || ':' || handling_mode
        FROM support_ticket
        WHERE id IN ('${raceTicketA}', '${raceTicketB}')
        ORDER BY id;
    `).split("\n"),
  ).toEqual([`${raceTicketA}:INVESTIGATING:HUMAN`, `${raceTicketB}:WAITING_FOR_CUSTOMER:AGENT`]);
  expect(
    queryFixtureSql(`
      SELECT ticket_id || ':' || body
        FROM public_message
        WHERE ticket_id IN ('${raceTicketA}', '${raceTicketB}')
          AND body IN (
            '已按您的要求转由客服继续处理。客服将在此工单中与您联系。',
            '为确认需要调查的订单，请回复订单确认码（A 或 B）。'
          )
        ORDER BY ticket_id;
    `).split("\n"),
  ).toEqual([
    `${raceTicketA}:已按您的要求转由客服继续处理。客服将在此工单中与您联系。`,
    `${raceTicketB}:为确认需要调查的订单，请回复订单确认码（A 或 B）。`,
  ]);

  const supportContext = await newIssue80Context(browser, {
    viewport: { width: 1440, height: 900 },
  });
  const support = await supportContext.newPage();
  await login(support, "internal", "support-demo");
  const supportGroup = support.getByRole("region", { name: `订单 ${orderReference}` });
  await expect(supportGroup).toContainText("2 张独立工单");
  await support.getByRole("button", { name: `领取工单 ${created.ticketIds[0]}` }).click();
  await support.getByRole("button", { name: "确认领取" }).click();
  await expect(support.getByRole("heading", { name: "授权工单详情" })).toBeVisible();
  const siblingRead = await support.evaluate(async (ticketId) => {
    const response = await fetch(`/api/support/workbench/tickets/${ticketId}`, {
      credentials: "same-origin",
    });
    return response.status;
  }, created.ticketIds[1]);
  expect(siblingRead).toBe(404);

  await supportContext.close();
  await customerContext.close();
});
