import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { prepareOrder, intakeReply } from "./support/issue173-intake";

declare const process: { env: Record<string, string | undefined> };

test.use({ screenshot: "only-on-failure" });

// 专用隔离栈只替换 Spring 的外部 Agent HTTP 边界；浏览器、业务服务和数据库均真实。
test("Issue #226 自然语言继续理解，明确确认不再交给模型", async ({ browser }) => {
  expect(process.env.ISSUE226_CONFIRMATION_REGRESSION).toBe("1");
  const reference = prepareOrder();
  const messages: string[] = [];
  async function respond(request: IncomingMessage, response: ServerResponse) {
    if (request.method === "GET" || request.url === "/threads/search") {
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end("{}");
      return;
    }
    let body = "";
    request.setEncoding("utf8");
    for await (const chunk of request) body += chunk;
    const run = JSON.parse(body) as {
      assistant_id: string;
      input: { customer_message: string };
    };
    if (request.url !== "/runs/wait" || run.assistant_id !== "intake_agent") {
      response.writeHead(503);
      response.end();
      return;
    }
    messages.push(run.input.customer_message);
    // 可复现 run12 的误判：即使收到“确认提交”，模型仍返回原来的待确认理解。
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(
      JSON.stringify({
        intake_understanding: {
          intent: "UNDERSTANDING",
          status: "READY_TO_CONFIRM",
          candidate_order_reference: reference,
          issues: [
            { kind: "PACKAGE_NOT_RECEIVED", summary: "包裹未收到" },
            { kind: "DUPLICATE_CHARGE", summary: "重复扣款" },
          ],
          pending_issue_kinds: [],
          remaining_order_references: [],
          assistant_message: "请确认这两个问题。",
        },
      }),
    );
  }
  const server = createServer((request, response) => {
    void respond(request, response).catch(() => {
      response.writeHead(500);
      response.end();
    });
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(2024, "0.0.0.0", resolve);
  });
  const context = await newAcceptanceContext(browser);
  try {
    // backend 的健康检查先于临时 HTTP stub 启动；只等待连通性，不重发业务命令。
    await expect
      .poll(
        async () => {
          const response = await context.request.get("/api/system/status");
          const status = (await response.json()) as { services: { agent: string } };
          return status.services.agent;
        },
        { timeout: 15_000 },
      )
      .toBe("UP");
    const page = await context.newPage();
    await login(page, "customer", "customer-demo");
    const description = `${reference} 的包裹没收到，而且重复扣款`;
    await page.getByLabel("问题描述").fill(description);
    const started = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/customer/v2/intakes",
    );
    await page.getByRole("button", { name: "开始智能受理" }).click();
    const startResponse = await started;
    expect(startResponse.status(), "首次受理 HTTP 状态").toBe(201);
    const initial = (await startResponse.json()) as {
      status: string;
      issues: { kind: string }[];
      candidateOrder: { reference: string } | null;
      ticketIds: string[];
    };
    expect(
      {
        status: initial.status,
        issueKinds: initial.issues.map((issue) => issue.kind),
        candidateMatches: initial.candidateOrder?.reference === reference,
        ticketCount: initial.ticketIds.length,
        modelCalls: messages.length,
      },
      "首次受理应形成可确认的两问题候选，不提前创建工单",
    ).toEqual({
      status: "READY_TO_CONFIRM",
      issueKinds: ["PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE"],
      candidateMatches: true,
      ticketCount: 0,
      modelCalls: 1,
    });
    await expect(page.getByRole("heading", { name: "请确认 2 个问题" })).toBeVisible();
    expect(messages).toEqual([description]);

    const correction = "两个问题都还存在，请再核对一下";
    await page.getByLabel("补充受理信息").fill(correction);
    const understood = intakeReply(page);
    await page.getByRole("button", { name: "发送给智能受理" }).click();
    const understanding = (await (await understood).json()) as { status: string };
    expect(understanding.status).toBe("READY_TO_CONFIRM");
    expect(messages).toEqual([description, correction]);

    const confirmed = intakeReply(page);
    await page.getByRole("button", { name: "确认并原子创建 2 张工单" }).click();
    const result = await confirmed;
    expect(result.status()).toBe(201);
    const snapshot = (await result.json()) as { status: string; ticketIds: string[] };
    expect(snapshot.status).toBe("CONFIRMED");
    expect(snapshot.ticketIds).toHaveLength(2);
    expect(new Set(snapshot.ticketIds).size).toBe(2);
    expect(messages).toEqual([description, correction]);
    await expect(page.getByRole("heading", { name: "2 张工单已创建" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { name: `订单 ${reference}` })).toBeVisible();
    expect(messages).toEqual([description, correction]);
  } finally {
    await context.close();
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
});
