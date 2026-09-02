import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";

test("Issue #153 低置信问题澄清后原子创建同订单多工单", async ({ browser }) => {
  const context = await newIssue80Context(browser, { viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await login(page, "customer", "customer-demo");

  await page.getByLabel("问题描述").fill("ORDER-DELAY-UNDER-24 的包裹没收到，而且疑似重复扣款");
  await page.getByRole("button", { name: "开始智能受理" }).click();

  await expect(page.getByRole("heading", { name: "再帮我确认一点" })).toBeVisible();
  await expect(page.getByText("请确认是否确实发生了两次扣款")).toBeVisible();
  await expect(page.getByRole("article", { name: "问题理解" })).toContainText("包裹未收到");
  await expect(page.getByRole("button", { name: /原子创建/ })).toHaveCount(0);

  await page.getByLabel("补充受理信息").fill("是的，确实重复扣款");
  await page.getByRole("button", { name: "发送给智能受理" }).click();
  await expect(page.getByRole("heading", { name: "请确认 2 个问题" })).toBeVisible();
  await expect(page.getByRole("article", { name: /拟建工单/ })).toHaveCount(2);

  const confirmationRequest = page.waitForRequest((request) =>
    /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(request.url()).pathname),
  );
  const confirmed = page.waitForResponse((response) =>
    /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(response.url()).pathname),
  );
  await page.getByRole("button", { name: "确认并原子创建 2 张工单" }).click();
  const originalRequest = await confirmationRequest;
  const confirmationResponse = await confirmed;
  expect(confirmationResponse.status()).toBe(201);
  const result = (await confirmationResponse.json()) as {
    ticketIds: string[];
    sharedIntakeRecordId: string;
  };

  expect(result.ticketIds).toHaveLength(2);
  expect(new Set(result.ticketIds).size).toBe(2);
  expect(result.sharedIntakeRecordId).toMatch(/^[0-9a-f-]{36}$/i);

  const originalHeaders = await originalRequest.allHeaders();
  const replay = await page.evaluate(
    async ({ url, headers, body }) => {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": headers["content-type"],
          "Idempotency-Key": headers["idempotency-key"],
          "X-CSRF-TOKEN": headers["x-csrf-token"],
        },
        body,
      });
      return { status: response.status, body: await response.json() };
    },
    {
      url: originalRequest.url(),
      headers: originalHeaders,
      body: originalRequest.postData(),
    },
  );
  expect(replay.status).toBe(200);
  expect(replay.body).toMatchObject({
    replayed: true,
    ticketIds: result.ticketIds,
    sharedIntakeRecordId: result.sharedIntakeRecordId,
  });
  await expect(page.getByRole("heading", { name: "2 张工单已创建" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "订单 ORDER-DELAY-UNDER-24" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await context.close();
});

test("Issue #153 桌面确认失败不展示部分创建结果", async ({ browser }) => {
  const context = await newIssue80Context(browser, { viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await login(page, "customer", "customer-demo");
  await page.route("**/api/customer/v2/intakes", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        schema: "customer-intake-v4",
        intakeId: "15300000-0000-0000-0000-000000000001",
        status: "READY_TO_CONFIRM",
        candidateOrder: { reference: "ORDER-MULTI-001", summary: "配送中的合成订单" },
        issue: null,
        issues: [
          { kind: "PACKAGE_NOT_RECEIVED", summary: "包裹未收到" },
          { kind: "DUPLICATE_CHARGE", summary: "重复扣款" },
        ],
        assistantMessage: "请确认；确认后将创建 2 张工单。",
        ticketId: null,
        ticketIds: [],
        sharedIntakeRecordId: null,
        expectedTicketCount: 2,
        confirmed: false,
        replayed: false,
      }),
    });
  });
  await page.route("**/api/customer/v2/intakes/*/messages", async (route) => {
    await route.fulfill({ status: 503, body: "atomic transaction unavailable" });
  });

  await page.getByLabel("问题描述").fill("包裹没收到并且重复扣款");
  await page.getByRole("button", { name: "开始智能受理" }).click();
  await page.getByRole("button", { name: "确认并原子创建 2 张工单" }).click();

  await expect(page.getByRole("alert")).toContainText("不会创建部分工单或重复工单");
  await expect(page.getByRole("heading", { name: "2 张工单已创建" })).toHaveCount(0);
  await context.close();
});
