import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";

test("Issue #154 桌面端由客户确认继续既有工单且不重复建单", async ({ browser }) => {
  const context = await newIssue80Context(browser, { viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await login(page, "customer", "customer-demo");

  await page
    .getByLabel("问题描述")
    .fill("ORDER-DELAY-001 的物流仍然延迟，请继续处理同一个问题");
  await page.getByRole("button", { name: "开始智能受理" }).click();

  await expect(page.getByRole("heading", { name: "请确认是否继续既有工单" })).toBeVisible();
  await expect(page.getByRole("region", { name: "疑似重复问题" })).toContainText(
    "不会读取或合并既有对话",
  );
  const resolved = page.waitForResponse(
    (response) =>
      /\/api\/customer\/v2\/intakes\/[^/]+\/duplicate-resolution$/.test(
        new URL(response.url()).pathname,
      ) && response.status() === 201,
  );
  await page.getByRole("button", { name: /继续旧工单/ }).first().click();
  const result = (await (await resolved).json()) as {
    ticketIds: string[];
    routedTicketIds: string[];
  };

  expect(result.ticketIds).toHaveLength(0);
  expect(result.routedTicketIds).toHaveLength(1);
  await expect(page.getByRole("heading", { name: "已继续既有工单" })).toBeVisible();
  await expect(page.getByRole("region", { name: "已创建工单" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "继续处理的既有工单" })).toBeVisible();
  await context.close();
});

test("Issue #154 窄屏逐订单确认并保留原始描述续办", async ({ browser }) => {
  const context = await newIssue80Context(browser, { viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await login(page, "customer", "customer-demo");

  await page
    .getByLabel("问题描述")
    .fill("ORDER-DELAY-001 物流延迟，ORDER-DELAY-UNDER-24 的物流也延迟");
  await page.getByRole("button", { name: "开始智能受理" }).click();

  await expect(page.getByRole("article", { name: "订单候选" })).toContainText("ORDER-DELAY-001");
  await expect(page.getByRole("heading", { name: "请确认是否继续既有工单" })).toBeVisible();
  await page.getByRole("button", { name: "这是新问题，继续创建" }).click();
  await expect(page.getByRole("heading", { name: "请确认我的理解" })).toBeVisible();
  await page.getByRole("button", { name: "确认，就是这个问题" }).click();

  await expect(page.getByRole("article", { name: "订单候选" })).toContainText(
    "ORDER-DELAY-UNDER-24",
  );
  await expect(page.getByText(/已确认，当前订单.*原始描述已保留/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "请确认是否继续既有工单" })).toBeVisible();
  await page.getByRole("button", { name: "这是新问题，继续创建" }).click();
  await expect(page.getByRole("heading", { name: "继续下一订单" })).toBeVisible();
  const completed = page.waitForResponse(
    (response) =>
      /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(response.url()).pathname) &&
      response.status() === 201,
  );
  await page.getByRole("button", { name: "确认，就是这个问题" }).click();
  const finalResult = (await (await completed).json()) as {
    confirmed: boolean;
    ticketIds: string[];
  };

  expect(finalResult.confirmed).toBe(true);
  expect(finalResult.ticketIds).toHaveLength(2);
  expect(new Set(finalResult.ticketIds).size).toBe(2);
  await expect(page.getByRole("heading", { name: "2 张工单已创建" })).toBeVisible();
  const overview = page.getByRole("region", { name: "订单工单总览" });
  await expect(overview.getByRole("heading", { name: "订单 ORDER-DELAY-UNDER-24" })).toBeVisible();
  for (const ticketId of finalResult.ticketIds) {
    await expect(overview.getByRole("button", { name: `打开工单 ${ticketId}` })).toBeVisible();
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await context.close();
});
