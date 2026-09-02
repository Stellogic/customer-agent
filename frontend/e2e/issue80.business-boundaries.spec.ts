import { expect, test } from "@playwright/test";
import { continueAsNewIfDuplicate, login } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";

const otherCustomerTicketId = "80000000-0000-0000-0000-000000000009";

test("客户公开投影、客服最小队列与领取详情保持资源授权边界", async ({ browser }) => {
  const customerContext = await newIssue80Context(browser);
  const customer = await customerContext.newPage();
  await login(customer, "customer", "customer-demo");

  const description = `Issue #80 浏览器资源边界 ${crypto.randomUUID()}`;
  await customer.getByLabel("订单编号").fill("ORDER-DELAY-UNDER-24");
  await customer.getByLabel("问题描述").fill(description);
  const createdResponse = customer.waitForResponse(
    (response) =>
      /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(response.url()).pathname) &&
      response.status() === 201,
  );
  await customer.getByRole("button", { name: "开始智能受理" }).click();
  await continueAsNewIfDuplicate(customer);
  await customer.getByRole("button", { name: "确认，就是这个问题" }).click();
  const created = (await (await createdResponse).json()) as { ticketId: string };
  expect(created.ticketId).toMatch(/^[0-9a-f-]{36}$/i);
  await expect(
    customer.getByRole("heading", {
      name: `${created.ticketId.slice(0, 8)}…${created.ticketId.slice(-4)}`,
    }),
  ).toBeVisible();

  const customerProjection = await customer.evaluate(async (ticketId) => {
    const response = await fetch(`/api/customer/v2/tickets/${ticketId}`, {
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "X-Synthetic-Customer-Id": "someone-else",
        "X-Synthetic-Support-Id": "support-demo",
        "X-Synthetic-Approver-Id": "approver-demo",
      },
    });
    return { status: response.status, body: await response.text() };
  }, created.ticketId);
  expect(customerProjection.status).toBe(200);
  expect(JSON.parse(customerProjection.body)).toMatchObject({
    view: "CUSTOMER_PUBLIC",
    ticket: { id: created.ticketId },
  });
  expect(customerProjection.body).not.toMatch(
    /internalNote|investigationFacts|businessTimeline|leaseToken|evidenceSnapshot/i,
  );

  const otherCustomerStatus = await customer.evaluate(async (ticketId) => {
    return (
      await fetch(`/api/customer/v2/tickets/${ticketId}`, {
        credentials: "same-origin",
        cache: "no-store",
      })
    ).status;
  }, otherCustomerTicketId);
  expect(otherCustomerStatus).toBe(404);

  const forgedSupportStatus = await customer.evaluate(async () => {
    return (
      await fetch("/api/support/queue", {
        credentials: "same-origin",
        headers: { "X-Synthetic-Support-Id": "support-demo" },
      })
    ).status;
  });
  expect(forgedSupportStatus).toBe(403);

  await customer.getByRole("button", { name: "转人工处理" }).dispatchEvent("click");
  await customer.getByRole("button", { name: "确认转人工" }).click();
  await expect(customer.getByText("人工客服处理中")).toBeVisible();

  const anonymousContext = await newIssue80Context(browser);
  const anonymous = await anonymousContext.newPage();
  await anonymous.goto("/help/login");
  const forgedAnonymousStatus = await anonymous.evaluate(async (ticketId) => {
    return (
      await fetch(`/api/customer/v2/tickets/${ticketId}`, {
        headers: { "X-Synthetic-Customer-Id": "customer-demo" },
      })
    ).status;
  }, created.ticketId);
  expect(forgedAnonymousStatus).toBe(401);
  await anonymousContext.close();

  const supportContext = await newIssue80Context(browser);
  const support = await supportContext.newPage();
  await login(support, "internal", "support-demo");
  await expect(
    support.getByText(`${created.ticketId.slice(0, 8)}…${created.ticketId.slice(-4)}`).first(),
  ).toBeVisible();

  const minimumQueueItem = await support.evaluate(async (ticketId) => {
    const snapshot = (await (
      await fetch("/api/support/workbench/snapshot?schema=support-workbench-v2", {
        credentials: "same-origin",
        cache: "no-store",
      })
    ).json()) as { sharedQueue: Array<Record<string, unknown>> };
    return snapshot.sharedQueue.find((item) => item.ticketId === ticketId);
  }, created.ticketId);
  expect(Object.keys(minimumQueueItem ?? {}).sort()).toEqual(
    [
      "enteredAt",
      "handlingMode",
      "issueKind",
      "lifecycleState",
      "orderReference",
      "ticketId",
    ].sort(),
  );
  expect(JSON.stringify(minimumQueueItem)).not.toMatch(
    /customerId|description|investigation|message|timeline/i,
  );

  const staleCursorStatus = await support.evaluate(async () => {
    return (
      await fetch("/api/support/workbench/events", {
        credentials: "same-origin",
        headers: { "Last-Event-ID": "support-workbench-v0:9", Accept: "text/event-stream" },
      })
    ).status;
  });
  expect(staleCursorStatus).toBe(409);

  const hiddenResourceStatus = await support.evaluate(async () => {
    return (
      await fetch("/api/support/workbench/tickets/00000000-0000-0000-0000-000000000080", {
        credentials: "same-origin",
      })
    ).status;
  });
  expect(hiddenResourceStatus).toBe(404);

  await support.getByRole("button", { name: `领取工单 ${created.ticketId}` }).click();
  await support.getByRole("button", { name: "确认领取" }).click();
  await expect(support.getByRole("heading", { name: "授权工单详情" })).toBeVisible();
  await expect(
    support
      .getByLabel("工单基本信息")
      .getByText("ORDER-DELAY-UNDER-24", { exact: true }),
  ).toBeVisible();
  await expect(
    support.getByRole("region", { name: "问题描述" }).getByText(description),
  ).toBeVisible();

  await supportContext.close();
  await customerContext.close();
});
