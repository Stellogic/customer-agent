import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";

test("Issue #129 客户人工偏好围栏真实 Flash 迟到自动回复", async ({ browser }) => {
  test.setTimeout(90_000);
  const context = await newAcceptanceContext(browser, {
    viewport: { width: 1440, height: 960 },
  });
  const page = await context.newPage();
  await login(page, "customer", "customer-demo");
  await page.getByLabel("订单编号").fill("ORDER-DELAY-001");
  await page
    .getByLabel("问题描述")
    .fill("这是合成客户数据：请调查物流延迟，但我随后会明确要求人工处理。");
  const createdResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/customer/tickets") && response.status() === 201,
  );
  await page.getByRole("button", { name: "提交物流延迟问题" }).click();
  await createdResponse;

  const handoff = page.getByRole("button", { name: "转人工处理" });
  await expect(handoff).toBeVisible();
  await page.waitForTimeout(1_500);
  await handoff.click();
  await page.getByRole("button", { name: "确认转人工" }).click();
  await expect(page.getByText("人工客服处理中", { exact: true })).toBeVisible();
  await expect(
    page.getByText("为确保处理安全，此工单已转由客服继续调查。客服将在此工单中与您联系。", {
      exact: true,
    }),
  ).toBeVisible();

  await page.waitForTimeout(20_000);
  await expect(page.getByText("人工客服处理中", { exact: true })).toBeVisible();
  await expect(page.getByText(/补偿建议正在等待人工审批|当前不符合补偿条件/)).toHaveCount(0);
  await context.close();
});
