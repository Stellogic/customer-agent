import { expect, type Page } from "@playwright/test";
import { continueAsNewIfDuplicate } from "./auth";
import { executeFixtureSql } from "./database";

type LogisticsIntakeSnapshot = {
  status: string;
  assistantMessage: string;
  candidateOrder: { reference: string };
  remainingOrderCount: number;
  ticketIds: string[];
  issues: { kind: string }[];
};

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

export async function createSingleTicket(
  page: Page,
  reference: string,
  description: string,
  allowLogisticsClarification = false,
) {
  await page.getByLabel("订单编号").fill(reference);
  await page.getByLabel("问题描述").fill(description);
  const started = allowLogisticsClarification
    ? page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname === "/api/customer/v2/intakes",
      )
    : undefined;
  await page.getByRole("button", { name: "开始智能受理" }).click();
  if (started) {
    const response = await started;
    expect(response.status()).toBe(201);
    const snapshot = (await response.json()) as LogisticsIntakeSnapshot;
    expect(snapshot.candidateOrder.reference).toBe(reference);
    expect(snapshot.remainingOrderCount).toBe(0);
    expect(snapshot.ticketIds).toEqual([]);
    if (snapshot.status === "NEEDS_CLARIFICATION") {
      expect([
        "请确认物流是否已经超过预期时间仍无进展。",
        `你说的是不是订单 ${reference} 的物流延迟问题？也可以直接纠正我的理解。`,
      ]).toContain(snapshot.assistantMessage);
      await expect(page.getByText(snapshot.assistantMessage, { exact: true })).toBeVisible();
      expect(snapshot.issues).toEqual([]);
      const clarified = intakeReply(page);
      await page.getByLabel("补充受理信息").fill("确实延迟，请核实物流状态。");
      await page.getByRole("button", { name: "发送给智能受理", exact: true }).click();
      const clarificationResponse = await clarified;
      expect(clarificationResponse.status()).toBe(201);
      const next = (await clarificationResponse.json()) as LogisticsIntakeSnapshot;
      expect(next.status).toBe("READY_TO_CONFIRM");
      expect(next.candidateOrder.reference).toBe(reference);
      expect(next.remainingOrderCount).toBe(0);
      expect(next.ticketIds).toEqual([]);
      expect(next.issues).toHaveLength(1);
      expect(next.issues[0].kind).toBe("LOGISTICS_DELAY");
    } else {
      expect(snapshot.status).toBe("READY_TO_CONFIRM");
    }
  }
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
