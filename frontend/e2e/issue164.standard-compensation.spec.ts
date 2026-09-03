import { expect, test } from "@playwright/test";
import { continueAsNewIfDuplicate, login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql, revokeActiveAssignmentsForSupport } from "./support/database";

test("Issue #164 选择标准补偿并提交审批", async ({ browser }) => {
  test.setTimeout(90_000);
  const customerContext = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  const customer = await customerContext.newPage();
  await login(customer, "customer", "customer-demo");

  const description = `Issue #164 标准补偿 ${crypto.randomUUID()}`;
  await customer.getByLabel("订单编号").fill("ORDER-DELAY-E2E-NORMAL");
  await customer.getByLabel("问题描述").fill(description);
  const createdResponse = customer.waitForResponse(
    (response) =>
      /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(response.url()).pathname) &&
      response.status() === 201,
  );
  await customer.getByRole("button", { name: "开始智能受理" }).click();
  await continueAsNewIfDuplicate(customer);
  await customer.getByRole("button", { name: "确认，就是这个问题" }).click();
  const created = (await (await createdResponse).json()) as { ticketIds: string[] };
  expect(created.ticketIds).toHaveLength(1);
  const ticketId = created.ticketIds[0];
  if (!/^[0-9a-f-]{36}$/i.test(ticketId)) {
    throw new Error(`invalid ticket id: ${ticketId}`);
  }
  await customer.getByRole("button", { name: "转人工处理" }).click();
  await customer.getByRole("button", { name: "确认转人工" }).click();
  await expect(customer.getByText("人工客服处理中")).toBeVisible();

  executeFixtureSql(`
    UPDATE compensation_proposal_revision
      SET status = 'SUPERSEDED'
      WHERE order_reference = 'ORDER-DELAY-E2E-NORMAL'
        AND status = 'PENDING_APPROVAL'
        AND ticket_id <> '${ticketId}';
    UPDATE compensation_reservation
      SET status = 'RELEASED'
      WHERE order_reference = 'ORDER-DELAY-E2E-NORMAL'
        AND status = 'ACTIVE';
  `);

  revokeActiveAssignmentsForSupport("support-demo");
  const supportContext = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  const support = await supportContext.newPage();
  await login(support, "internal", "support-demo");
  await expect(support.getByRole("heading", { name: "客服共享队列" })).toBeVisible();

  await support
    .getByRole("button", { name: `领取工单 ${ticketId}` })
    .first()
    .click();
  await expect(support.getByRole("dialog", { name: "确认领取工单" })).toBeVisible();
  await support.getByRole("button", { name: "确认领取" }).click();
  await expect(support.getByRole("heading", { name: "授权工单详情" })).toBeVisible();
  await expect(support.getByRole("heading", { name: "标准补偿" })).toBeVisible();
  await expect(support.getByText("delay-policy-v1")).toBeVisible();
  const eligibleAmount = support
    .getByRole("region", { name: "标准补偿", exact: true })
    .locator(".support-compensation-facts > div")
    .filter({ has: support.locator("dt").filter({ hasText: /^资格金额$/ }) })
    .locator("dd");
  await expect(eligibleAmount).toHaveText("26.80 CNY");
  await expect(eligibleAmount).toBeVisible();
  await expect(support.getByRole("combobox", { name: "补偿方案" })).toContainText(
    "模拟原路部分退款 · 26.80 CNY",
  );

  await support.setViewportSize({ width: 640, height: 960 });
  await expect
    .poll(async () => {
      const value = await support
        .locator(".support-compensation-facts")
        .evaluate((element) => getComputedStyle(element).gridTemplateColumns);
      return value.split(" ").length;
    })
    .toBe(1);
  await expect
    .poll(() =>
      support.getByRole("button", { name: "提交审批" }).evaluate((button) => {
        const form = button.closest("form");
        if (!form) throw new Error("提交审批按钮必须属于补偿表单");
        return button.getBoundingClientRect().width / form.getBoundingClientRect().width;
      }),
    )
    .toBeGreaterThan(0.9);
  await support.setViewportSize({ width: 1440, height: 960 });

  await support.getByRole("button", { name: "提交审批" }).click();
  await expect(
    support.getByText("标准补偿提案已提交审批。客户只会看到类型、金额和待审批。"),
  ).toBeVisible();

  await expect(customer.getByRole("heading", { name: "待审批" })).toBeVisible();
  const pending = customer.locator(".pending-compensation-card");
  await expect(pending.getByText("模拟原路部分退款")).toBeVisible();
  await expect(pending.getByText("26.80 CNY")).toBeVisible();
  await expect(pending.getByText("待审批", { exact: true })).toHaveCount(2);
  await expect(pending.getByText("现在还没有批准或执行补偿。")).toBeVisible();
  await expect(customer.getByText("已批准")).toHaveCount(0);
  await expect(customer.getByText("已执行")).toHaveCount(0);
  await expect(
    customer.getByText(
      "补偿建议正在等待人工审批。建议类型：模拟原路部分退款，金额：26.80 CNY。最终结果将在处理完成后通知你。",
    ),
  ).toBeVisible();

  await customer.setViewportSize({ width: 640, height: 960 });
  await expect
    .poll(async () => {
      const value = await pending
        .locator("dl")
        .evaluate((element) => getComputedStyle(element).gridTemplateColumns);
      return value.split(" ").length;
    })
    .toBe(1);

  const otherContext = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  const other = await otherContext.newPage();
  await login(other, "internal", "internal-demo");
  await other.goto("/internal/support");
  await expect(other.getByRole("heading", { name: "客服共享队列" })).toBeVisible();
  await expect(other.getByRole("heading", { name: "标准补偿" })).toHaveCount(0);
  await expect(other.getByRole("button", { name: `领取工单 ${ticketId}` })).toHaveCount(0);

  await otherContext.close();
  await supportContext.close();
  await customerContext.close();
});
