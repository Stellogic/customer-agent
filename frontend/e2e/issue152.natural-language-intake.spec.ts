import { expect, test } from "@playwright/test";
import { continueAsNewIfDuplicate, login } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";

test("Issue #152 自然语言受理先确认后建单并保持窄屏可用", async ({ browser }) => {
  const context = await newIssue80Context(browser, { viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await login(page, "customer", "customer-demo");

  await expect(page.getByLabel("订单编号")).toBeVisible();
  await page.getByLabel("问题描述").fill("ORDER-DELAY-UNDER-24 的包裹好几天没有动了");
  const started = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/customer/v2/intakes" && response.status() === 201,
  );
  await page.getByRole("button", { name: "开始智能受理" }).click();
  const initial = (await (await started).json()) as { ticketId: string | null };

  expect(initial.ticketId).toBeNull();
  await continueAsNewIfDuplicate(page);
  await expect(page.getByRole("article", { name: "订单候选" })).toContainText(
    "ORDER-DELAY-UNDER-24",
  );
  await expect(page.getByRole("article", { name: "订单候选" })).toContainText("仅摘要");
  await expect(page.getByRole("article", { name: "问题理解" })).toContainText(
    "确认前不会创建正式工单",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);

  const confirmed = page.waitForResponse(
    (response) =>
      /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(
        new URL(response.url()).pathname,
      ) && response.status() === 201,
  );
  await page.getByRole("button", { name: "确认，就是这个问题" }).click();
  const result = (await (await confirmed).json()) as { ticketId: string; confirmed: boolean };
  expect(result.confirmed).toBe(true);
  expect(result.ticketId).toMatch(/^[0-9a-f-]{36}$/i);
  await expect(page.getByRole("heading", { name: /…/ })).toBeVisible();
  await context.close();
});

test("Issue #152 受理加载和错误状态不会伪造成功", async ({ browser }) => {
  const context = await newIssue80Context(browser, { viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await login(page, "customer", "customer-demo");
  await page.route("**/api/customer/v2/intakes", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 300));
    await route.fulfill({ status: 503, body: "temporarily unavailable" });
  });
  await page.getByLabel("问题描述").fill("我的包裹物流延迟了");
  await page.getByRole("button", { name: "开始智能受理" }).click();
  await expect(page.getByRole("button", { name: "正在理解你的问题…" })).toBeDisabled();
  await expect(page.getByRole("alert")).toContainText("受理未完成");
  await expect(page.getByRole("heading", { name: "请确认我的理解" })).toHaveCount(0);
  await context.close();
});
