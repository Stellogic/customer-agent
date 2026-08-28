import { expect, test, type Page } from "@playwright/test";
import { login } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";
import { executeFixtureSql, queryFixtureSql } from "./support/database";

test("Issue #155 桌面端在七日精确边界归档并重新核对变化事实", async ({ browser }) => {
  const context = await newIssue80Context(browser, { viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const orderReference = "ORDER-INTAKE-155-DESKTOP";
  prepareOrder(orderReference);
  await login(page, "customer", "customer-demo");

  const intakeId = await startIntake(page, orderReference);
  executeFixtureSql(`
    update customer_intake
    set expires_at = timestamptz '2026-08-09T14:00:00Z'
    where id = '${intakeId}'::uuid;
    update synthetic_order
    set delay_hours = 81, delay_seconds = 291600
    where order_reference = '${orderReference}';
  `);

  await page.goto("/help");
  await page.getByRole("button", { name: "查找未完成受理" }).click();
  await expect(page.getByRole("heading", { name: "已归档受理" })).toBeVisible();
  expect(
    queryFixtureSql(`select retention_state from customer_intake where id = '${intakeId}'`),
  ).toBe("ARCHIVED");
  expect(
    queryFixtureSql(
      `select count(*) from support_ticket where order_reference = '${orderReference}'`,
    ),
  ).toBe("0");

  await page.getByRole("button", { name: "恢复并重新核对事实" }).click();
  await expect(page.getByText("订单事实已变化，请重新确认")).toBeVisible();
  await expect(page.getByRole("heading", { name: "请确认我的理解" })).toBeVisible();
  expect(
    queryFixtureSql(`select retention_state from customer_intake where id = '${intakeId}'`),
  ).toBe("ACTIVE");
  expect(
    queryFixtureSql(
      `select count(*) from support_ticket where order_reference = '${orderReference}'`,
    ),
  ).toBe("0");
  await context.close();
});

test("Issue #155 窄屏恢复活动受理且隔离其他客户记录", async ({ browser }) => {
  const context = await newIssue80Context(browser, { viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const orderReference = "ORDER-INTAKE-155-NARROW";
  prepareOrder(orderReference);
  await login(page, "customer", "customer-demo");

  const intakeId = await startIntake(page, orderReference);
  executeFixtureSql(`
    update customer_intake
    set updated_at = timestamptz '2026-08-09T14:00:01Z',
        expires_at = timestamptz '2026-08-16T14:00:01Z'
    where id = '${intakeId}'::uuid;
    insert into customer_intake (
      id, customer_id, start_request_key, start_digest, original_message, status,
      candidate_order_reference, candidate_order_version, candidate_order_summary,
      issue_kind, issue_summary, assistant_message, created_at, updated_at, expires_at
    ) select
      '15500000-0000-0000-0000-000000000099'::uuid, 'customer-other', 'other-request',
      repeat('a', 64), '其他客户的受理', status, candidate_order_reference,
      candidate_order_version, candidate_order_summary, issue_kind, issue_summary,
      '其他客户私有记录', created_at, updated_at, expires_at
    from customer_intake where id = '${intakeId}'::uuid
    on conflict do nothing;
    insert into customer_intake_issue (intake_id, ordinal, issue_kind, issue_summary)
    select '15500000-0000-0000-0000-000000000099'::uuid, ordinal, issue_kind, issue_summary
    from customer_intake_issue where intake_id = '${intakeId}'::uuid
    on conflict do nothing;
    insert into customer_intake_transcript (id, intake_id, ordinal, author, body, created_at)
    values (
      '15500000-0000-0000-0000-000000000098'::uuid,
      '15500000-0000-0000-0000-000000000099'::uuid,
      1, 'CUSTOMER', '其他客户私有消息', timestamptz '2026-08-09T14:00:00Z'
    ) on conflict do nothing;
  `);

  await page.goto("/help");
  await page.getByRole("button", { name: "查找未完成受理" }).click();
  await expect(page.getByRole("heading", { name: "请确认我的理解" })).toBeVisible();
  await expect(page.getByText("其他客户私有消息")).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get("intake")).toBe(intakeId);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await context.close();
});

async function startIntake(page: Page, orderReference: string) {
  const response = page.waitForResponse(
    (candidate) =>
      new URL(candidate.url()).pathname === "/api/customer/v2/intakes" &&
      candidate.status() === 201,
  );
  await page.getByLabel("订单编号").fill(orderReference);
  await page.getByLabel("问题描述").fill("物流已经延迟，请帮我核对");
  await page.getByRole("button", { name: "提交物流延迟问题" }).click();
  const body = (await (await response).json()) as { intakeId: string };
  await expect(page.getByRole("heading", { name: "请确认我的理解" })).toBeVisible();
  return body.intakeId;
}

function prepareOrder(orderReference: string) {
  executeFixtureSql(`
    insert into synthetic_order (
      order_reference, customer_id, paid_amount, currency, delay_hours, paid,
      cancelled, fully_refunded, existing_compensation, policy_version,
      available_compensation_amount, delay_seconds
    ) values (
      '${orderReference}', 'customer-demo', 268.00, 'CNY', 80, true,
      false, false, false, 'delay-policy-v1', 268.00, 288000
    ) on conflict (order_reference) do update
    set delay_hours = excluded.delay_hours, delay_seconds = excluded.delay_seconds;
  `);
}
