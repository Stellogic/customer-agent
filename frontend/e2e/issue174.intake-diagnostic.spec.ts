import { mkdirSync, writeFileSync } from "node:fs";
import { expect, test, type Response } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { prepareOrder } from "./support/issue173-intake";

// 独立诊断，不改变 L174-01 的 5 秒通过条件，也不创建工单。
test("Issue #174 intake diagnostic", async ({ browser }) => {
  test.setTimeout(90_000);
  const context = await newAcceptanceContext(browser, { viewport: { width: 390, height: 844 } });
  const observations: object[] = [];
  let headingWithinFiveSeconds: boolean | null = null;
  let stage = "START";
  async function summarize(response: Response, started: number) {
    const elapsedMs = Date.now() - started;
    const body = await response.json().catch(() => null);
    const states = ["READY_TO_CONFIRM", "NEEDS_CLARIFICATION", "CONFIRMED"];
    const kinds = ["LOGISTICS_DELAY", "PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE"];
    const status = states.includes(body?.status) ? body.status : "OTHER";
    const assisted = body?.assistantMessage === "已建立受理协助请求；客服只能协助确认订单与拟建问题，仍需由你确认后才会创建正式工单。";
    observations.push({
      httpStatus: response.status(), elapsedMs, status, assisted,
      issueCount: Array.isArray(body?.issues) ? body.issues.length : null,
      issueKinds: Array.isArray(body?.issues)
        ? body.issues.map((issue: { kind?: string }) => kinds.includes(issue.kind ?? "") ? issue.kind : "OTHER")
        : [],
    });
    return { status, assisted };
  }
  try {
    const page = await context.newPage();
    await login(page, "customer", "customer-demo");
    const reference = prepareOrder();
    await page.getByLabel("问题描述").fill(`${reference} 的包裹没收到，而且疑似重复扣款`);
    stage = "INITIAL_REQUEST";
    let started = Date.now();
    const initial = page.waitForResponse(r => r.request().method() === "POST" &&
      new URL(r.url()).pathname === "/api/customer/v2/intakes", { timeout: 30_000 });
    await page.getByRole("button", { name: "开始智能受理" }).click();
    const initialResult = await summarize(await initial, started);
    if (initialResult.assisted) { stage = "INITIAL_ASSISTED"; return; }
    if (initialResult.status !== "NEEDS_CLARIFICATION") { stage = "INITIAL_RESULT_DIFFERENT"; return; }
    await page.getByLabel("补充受理信息").fill("是的，确实重复扣款");
    stage = "FOLLOWUP_REQUEST";
    started = Date.now();
    const followup = page.waitForResponse(r => r.request().method() === "POST" &&
      /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(r.url()).pathname),
    { timeout: 30_000 }).then(r => summarize(r, started)).catch(() => { stage = "FOLLOWUP_RESPONSE_UNAVAILABLE"; });
    await page.getByRole("button", { name: "发送给智能受理" }).click();
    headingWithinFiveSeconds = await expect(page.getByRole("heading", { name: "请确认 2 个问题" }))
      .toBeVisible({ timeout: 5000 }).then(() => true, () => false);
    await followup;
    if (stage === "FOLLOWUP_REQUEST") stage = "OBSERVED";
  } finally {
    // 只写受控状态、数量和耗时；不写 URL/ID、正文、响应、凭据、trace 或页面快照。
    mkdirSync("/diagnostics", { recursive: true });
    writeFileSync("/diagnostics/intake-diagnostic.json", JSON.stringify({
      schema: "issue174-intake-diagnostic-v1", releaseAcceptance: false,
      stage, headingWithinFiveSeconds, observations,
    }, null, 2));
    await context.close();
  }
});
