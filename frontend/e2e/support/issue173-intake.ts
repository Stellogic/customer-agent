import { expect, type Page } from "@playwright/test";
import { continueAsNewIfDuplicate } from "./auth";
import { executeFixtureSql } from "./database";

// #173 只准备独有订单；工单、回复、代次和结果均由真实 UI → Spring/LangGraph 产生。
export function prepareOrder({ delayHours = 80, allowance = 268 } = {}) {
  const reference = `ORDER-ISSUE-173-${crypto.randomUUID()}`;
  executeFixtureSql(`
    INSERT INTO synthetic_order (
      order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
      paid, cancelled, fully_refunded, existing_compensation, policy_version,
      available_compensation_amount
    ) VALUES (
      '${reference}', 'customer-demo', 268.00, 'CNY', ${delayHours}, ${delayHours * 3600},
      true, false, false, false, 'delay-policy-v1', ${allowance}
    );
  `);
  return reference;
}

export function intakeReply(page: Page) {
  return page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(response.url()).pathname),
  );
}

export async function createSingleTicket(page: Page, reference: string, description: string) {
  await page.getByLabel("订单编号").fill(reference);
  await page.getByLabel("问题描述").fill(description);
  await page.getByRole("button", { name: "开始智能受理" }).click();
  await continueAsNewIfDuplicate(page);
  const confirmed = intakeReply(page);
  await page.getByRole("button", { name: "确认，就是这个问题" }).click();
  const response = await confirmed;
  expect(response.status()).toBe(201);
  const result = (await response.json()) as { ticketIds: string[]; confirmed: boolean };
  expect(result.confirmed).toBe(true);
  expect(result.ticketIds).toHaveLength(1);
  expect(result.ticketIds[0]).toMatch(/^[0-9a-f-]{36}$/i);
  return result.ticketIds[0];
}
