import { writeFileSync } from "node:fs";
import { expect, test, type Response } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { queryFixtureSql } from "./support/database";
import { prepareOrder } from "./support/issue173-intake";
import {
  assessIntakeProgress,
  diagnosticKinds,
  type DiagnosticKind,
  type IntakeObservation,
} from "../src/test-support/issue215-intake-diagnostic";

declare const process: { env: Record<string, string | undefined> };

// 独立于 #174 冻结验收；最多初次受理、两次澄清和一次最终确认。
test("Issue #215 双问题受理经澄清后一次创建两张工单", async ({ browser }) => {
  const evidenceDir = process.env.ISSUE215_DIAGNOSTIC_DIR;
  if (process.env.ISSUE215_DIAGNOSTIC_ENABLED !== "1" || !evidenceDir) {
    throw new Error("#215 诊断必须由持锁并冻结预算的入口显式启用");
  }
  test.setTimeout(120_000);
  const context = await newAcceptanceContext(browser, { viewport: { width: 390, height: 844 } });
  const observations: IntakeObservation[] = [];
  let verdict = "NOT_COMPLETED";
  let reference = "";
  let intakeId = "";

  async function observe(response: Response): Promise<IntakeObservation> {
    const body = (await response.json()) as {
      intakeId?: string;
      status?: string;
      candidateOrder?: { reference?: string };
      issues?: { kind: string }[];
    };
    // 标识只在内存中用于本次受理的定向查询，不进入断言输出或证据。
    const validId = typeof body.intakeId === "string" && /^[0-9a-f-]{36}$/i.test(body.intakeId);
    expect(validId, "响应必须包含有效受理标识").toBe(true);
    if (intakeId) expect(body.intakeId === intakeId, "追加响应必须属于同一受理").toBe(true);
    intakeId = body.intakeId!;
    const database = JSON.parse(
      queryFixtureSql(`
      SELECT json_build_object(
        'issueKinds', COALESCE((SELECT json_agg(issue_kind ORDER BY ordinal)
          FROM customer_intake_issue WHERE intake_id = '${intakeId}'), '[]'::json),
        'pendingKinds', COALESCE((SELECT json_agg(issue_kind ORDER BY ordinal)
          FROM customer_intake_pending_issue WHERE intake_id = '${intakeId}'), '[]'::json),
        'assistanceCount', (SELECT count(*) FROM intake_assistance_request WHERE intake_id = '${intakeId}'),
        'ticketCount', (SELECT count(*) FROM shared_intake_issue si JOIN shared_intake_record sr
          ON si.shared_intake_record_id = sr.id WHERE sr.intake_id = '${intakeId}')
      );
    `),
    ) as Pick<IntakeObservation, "issueKinds" | "pendingKinds" | "assistanceCount" | "ticketCount">;
    const safeKind = (kind: string) =>
      diagnosticKinds.includes(kind as DiagnosticKind) ? kind : "OTHER";
    const observation: IntakeObservation = {
      httpStatus: response.status(),
      status: ["NEEDS_CLARIFICATION", "READY_TO_CONFIRM", "CONFIRMED"].includes(body.status ?? "")
        ? body.status!
        : "OTHER",
      candidateMatches: body.candidateOrder?.reference === reference,
      responseIssueKinds: (body.issues ?? []).map((issue) => safeKind(issue.kind)),
      issueKinds: database.issueKinds.map(safeKind),
      pendingKinds: database.pendingKinds.map(safeKind),
      assistanceCount: database.assistanceCount,
      ticketCount: database.ticketCount,
    };
    observations.push(observation);
    return observation;
  }

  try {
    const page = await context.newPage();
    await login(page, "customer", "customer-demo");
    reference = prepareOrder();
    await page.getByLabel("问题描述").fill(`${reference} 的包裹没收到，而且疑似重复扣款`);
    const initialResponse = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" && new URL(r.url()).pathname === "/api/customer/v2/intakes",
      { timeout: 30_000 },
    );
    await page.getByRole("button", { name: "开始智能受理" }).click();
    const initial = await observe(await initialResponse);
    verdict = assessIntakeProgress(initial);
    expect(["READY_TO_REPLY", "READY_TO_CONFIRM"].includes(verdict)).toBe(true);
    const replies = {
      PACKAGE_NOT_RECEIVED: {
        question: "请确认包裹是否至今仍未收到。",
        answer: "是的，包裹至今仍未收到",
      },
      DUPLICATE_CHARGE: {
        question: "你提到疑似重复扣款，请确认是否确实发生了两次扣款。",
        answer: "是的，确实重复扣款",
      },
    };
    let before = initial;
    for (let step = 0; step < 2 && before.pendingKinds.length; step++) {
      const current = replies[before.pendingKinds[0] as DiagnosticKind];
      await expect(page.getByText(current.question, { exact: true })).toBeVisible();
      await page.getByLabel("补充受理信息").fill(current.answer);
      const followupResponse = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(r.url()).pathname),
        { timeout: 30_000 },
      );
      await page.getByRole("button", { name: "发送给智能受理" }).click();
      const followup = await observe(await followupResponse);
      verdict = assessIntakeProgress(before, followup);
      expect(verdict).toBe("HEAD_ADVANCED");
      before = followup;
    }
    expect(before.status).toBe("READY_TO_CONFIRM");
    await expect(page.getByRole("heading", { name: "请确认 2 个问题" })).toBeVisible();
    const confirmation = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(r.url()).pathname),
      { timeout: 30_000 },
    );
    await page.getByRole("button", { name: "确认并原子创建 2 张工单" }).click();
    const confirmedResponse = await confirmation;
    const confirmed = await observe(confirmedResponse);
    const created = (await confirmedResponse.json()) as {
      ticketIds?: string[];
      sharedIntakeRecordId?: string;
    };
    verdict = "CONFIRMATION_FAILED";
    expect(confirmed.httpStatus).toBe(201);
    expect(confirmed.status).toBe("CONFIRMED");
    expect(confirmed.assistanceCount).toBe(0);
    expect(confirmed.ticketCount).toBe(2);
    expect(created.ticketIds?.length === 2 && new Set(created.ticketIds).size === 2).toBe(true);
    expect(
      typeof created.sharedIntakeRecordId === "string" &&
        /^[0-9a-f-]{36}$/i.test(created.sharedIntakeRecordId),
    ).toBe(true);
    await expect(page.getByRole("heading", { name: "2 张工单已创建" })).toBeVisible();
    verdict = "PASS";
  } catch {
    if (["NOT_COMPLETED", "READY_TO_REPLY", "READY_TO_CONFIRM", "HEAD_ADVANCED"].includes(verdict))
      verdict = "EXECUTION_FAILED";
    throw new Error(`INTAKE_DIAGNOSTIC_FAILED verdict=${verdict}`);
  } finally {
    writeFileSync(
      `${evidenceDir}/intake-diagnostic.json`,
      JSON.stringify(
        {
          schema: "issue215-intake-diagnostic-v3",
          releaseAcceptance: false,
          verdict,
          observations,
        },
        null,
        2,
      ),
    );
    await context.close();
  }
});
