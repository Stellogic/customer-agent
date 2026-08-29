import { expect, test, type APIRequestContext } from "@playwright/test";
import { login } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";
import { executeFixtureSql } from "./support/database";

const streamingTicket = "15910000-0000-0000-0000-000000000001";
const streamingGeneration = "15910000-0000-0000-0000-000000000101";
const failedTicket = "15910000-0000-0000-0000-000000000002";
const failedGeneration = "15910000-0000-0000-0000-000000000102";
const abortedTicket = "15910000-0000-0000-0000-000000000003";
const abortedGeneration = "15910000-0000-0000-0000-000000000103";

test("Issue #159 真实 Chromium 恢复慢首字节、断线续流、失败与中止", async ({
  browser,
  request,
}) => {
  test.setTimeout(90_000);
  executeFixtureSql(`
    INSERT INTO support_ticket (
      id, customer_id, order_reference, description, issue_kind, lifecycle_state,
      handling_mode, created_at, first_responded_at, resolution_running_since
    ) VALUES
      ('${streamingTicket}', 'customer-demo', 'ORDER-DELAY-001', 'issue159-stream',
       'LOGISTICS_DELAY', 'INVESTIGATING', 'AGENT', now(), now(), now()),
      ('${failedTicket}', 'customer-demo', 'ORDER-DELAY-001', 'issue159-failed',
       'LOGISTICS_DELAY', 'INVESTIGATING', 'AGENT', now(), now(), now()),
      ('${abortedTicket}', 'customer-demo', 'ORDER-DELAY-001', 'issue159-aborted',
       'LOGISTICS_DELAY', 'INVESTIGATING', 'AGENT', now(), now(), now());
    INSERT INTO agent_processing_generation (
      id, ticket_id, generation_number, thread_id, status, created_at
    ) VALUES
      ('${streamingGeneration}', '${streamingTicket}', 1,
       '15910000-0000-0000-0000-000000000201', 'ACTIVE', now()),
      ('${failedGeneration}', '${failedTicket}', 1,
       '15910000-0000-0000-0000-000000000202', 'ACTIVE', now()),
      ('${abortedGeneration}', '${abortedTicket}', 1,
       '15910000-0000-0000-0000-000000000203', 'ACTIVE', now());
    INSERT INTO public_message (id, ticket_id, message_sequence, author, body, sent_at) VALUES
      ('15910000-0000-0000-0000-000000000301', '${streamingTicket}', 1,
       'CUSTOMER', '请调查这笔订单的物流延迟。', now()),
      ('15910000-0000-0000-0000-000000000302', '${failedTicket}', 1,
       'CUSTOMER', '请调查后告诉我结果。', now()),
      ('15910000-0000-0000-0000-000000000303', '${abortedTicket}', 1,
       'CUSTOMER', '我还会继续补充信息。', now());
  `);

  await publish(request, streamingTicket, streamingGeneration, "loading", { type: "LOADING" });
  const context = await newIssue80Context(browser, { viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  let disconnectTicketStream = false;
  await page.route("**/api/customer/v2/tickets/*/events", (route) =>
    disconnectTicketStream ? route.abort("connectionreset") : route.continue(),
  );
  await login(page, "customer", "customer-demo");
  await page.goto(`/help?ticket=${streamingTicket}`);
  await expect(page.getByText("等待首个内容片段", { exact: true })).toBeVisible();

  await publish(request, streamingTicket, streamingGeneration, "progress", {
    type: "PROGRESS",
    stage: "COMPOSING_REPLY",
  });
  await publish(request, streamingTicket, streamingGeneration, "started", {
    type: "STREAM_STARTED",
  });
  await publish(request, streamingTicket, streamingGeneration, "chunk-0", {
    type: "CONTENT_DELTA",
    chunkIndex: 0,
    delta: "经核验，订单 ORDER-DELAY-001 ",
  });
  await expect(page.getByText(/经核验，订单 ORDER-DELAY-001/)).toBeVisible();

  disconnectTicketStream = true;
  await page.reload();
  await expect(page.getByRole("heading", { name: "正在重新同步工单" })).toBeVisible();
  disconnectTicketStream = false;
  await page.getByRole("button", { name: "立即重试同步" }).click();
  await expect(page.getByText(/经核验，订单 ORDER-DELAY-001/)).toBeVisible();
  await publish(request, streamingTicket, streamingGeneration, "chunk-1", {
    type: "CONTENT_DELTA",
    chunkIndex: 1,
    delta:
      "的本次物流延迟不足 24 小时，当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。",
  });
  executeFixtureSql(
    `UPDATE agent_processing_generation SET status = 'COMPLETED', completed_at = now() WHERE id = '${streamingGeneration}';`,
  );
  await publish(request, streamingTicket, streamingGeneration, "completed", {
    type: "COMPLETED",
  });
  await expect(
    page.getByText(
      "经核验，订单 ORDER-DELAY-001 的本次物流延迟不足 24 小时，当前不符合补偿条件，工单已解决。如有异议，您可在关闭等待期内回复。",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByText("回复已完成", { exact: true })).toBeVisible();

  await publish(request, failedTicket, failedGeneration, "loading", { type: "LOADING" });
  await publish(request, failedTicket, failedGeneration, "failed", { type: "FAILED" });
  await page.goto(`/help?ticket=${failedTicket}`);
  await expect(page.getByText("回复失败，正在转人工处理", { exact: true })).toBeVisible();

  await publish(request, abortedTicket, abortedGeneration, "loading", { type: "LOADING" });
  await publish(request, abortedTicket, abortedGeneration, "aborted", { type: "ABORTED" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/help?ticket=${abortedTicket}`);
  await expect(page.getByText("旧回复已终止", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await context.close();
});

async function publish(
  request: APIRequestContext,
  ticketId: string,
  generationId: string,
  requestId: string,
  data: Record<string, unknown>,
) {
  const response = await request.post(
    `http://backend:8080/internal/agent/tickets/${ticketId}/generations/${generationId}/public-reply-events`,
    {
      headers: {
        Authorization: "Bearer local-agent-machine",
        "X-Agent-Generation-Id": generationId,
        "X-Agent-Operation": "PUBLISH_PUBLIC_REPLY_EVENT",
        "Idempotency-Key": `issue159-${requestId}`,
      },
      data,
    },
  );
  expect(response.status()).toBe(202);
}
