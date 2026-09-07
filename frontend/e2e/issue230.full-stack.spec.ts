import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql, queryFixtureSql } from "./support/database";
import { intakeReply } from "./support/issue173-intake";

test("Issue #230 同订单物流与重复扣款一次确认后独立处理并恢复", async ({ browser }, testInfo) => {
  test.setTimeout(120_000);
  const reference = `ORDER-ISSUE-230-${crypto.randomUUID()}`;
  // 只准备合成订单输入, 工单、事实、提案及公开回复均由真实产品产生。
  executeFixtureSql(`
    INSERT INTO synthetic_order (
      order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
      paid, cancelled, fully_refunded, existing_compensation, policy_version,
      available_compensation_amount, duplicate_charge_suspected
    ) VALUES (
      '${reference}', 'customer-demo', 99.00, 'CNY', 80, 288000,
      true, false, false, false, 'delay-policy-v1', 20.00, true
    );
  `);
  const context = await newAcceptanceContext(browser);
  const supportContext = await newAcceptanceContext(browser);
  try {
    const page = await context.newPage();
    await login(page, "customer", "customer-demo");
    await page.getByLabel("问题描述").fill(`${reference} 物流延迟，而且疑似重复扣款，请核查`);
    await page.getByRole("button", { name: "开始智能受理" }).click();
    await expect(page.getByRole("heading", { name: "再帮我确认一点" })).toBeVisible();
    await expect(page.getByRole("button", { name: /原子创建/ })).toHaveCount(0);
    await page.getByLabel("补充受理信息").fill("我看到扣了两次，请继续核查");
    const clarified = intakeReply(page);
    await page.getByRole("button", { name: "发送给智能受理" }).click();
    const candidate = (await (await clarified).json()) as {
      status: string;
      issues: { kind: string }[];
    };
    expect(candidate.status).toBe("READY_TO_CONFIRM");
    expect(candidate.issues.map((issue) => issue.kind).sort()).toEqual([
      "DUPLICATE_CHARGE", "LOGISTICS_DELAY",
    ]);
    const confirmed = intakeReply(page);
    await page.getByRole("button", { name: "确认并原子创建 2 张工单" }).click();
    const response = await confirmed;
    expect(response.status()).toBe(201);
    const intake = (await response.json()) as {
      status: string;
      ticketIds: string[];
      sharedIntakeRecordId: string;
    };
    expect(intake.status).toBe("CONFIRMED");
    expect(intake.ticketIds).toHaveLength(2);
    expect(new Set(intake.ticketIds).size).toBe(2);
    expect(intake.sharedIntakeRecordId).toMatch(/^[0-9a-f-]{36}$/i);
    await expect(page.getByRole("heading", { name: "2 张工单已创建" })).toBeVisible();

    const tickets = JSON.parse(queryFixtureSql(`
      SELECT json_agg(json_build_object('id', ticket_id, 'kind', issue_kind))
      FROM shared_intake_issue WHERE shared_intake_record_id = '${intake.sharedIntakeRecordId}';
    `)) as { id: string; kind: string }[];
    expect(tickets.map((ticket) => ticket.id).sort()).toEqual([...intake.ticketIds].sort());
    expect(tickets.map((ticket) => ticket.kind).sort()).toEqual(["DUPLICATE_CHARGE", "LOGISTICS_DELAY"]);
    const logisticsId = tickets.find((ticket) => ticket.kind === "LOGISTICS_DELAY")!.id;
    const paymentId = tickets.find((ticket) => ticket.kind === "DUPLICATE_CHARGE")!.id;
    await expect.poll(() => JSON.parse(queryFixtureSql(`
      SELECT json_agg(g.status ORDER BY t.issue_kind)
      FROM agent_processing_generation g JOIN support_ticket t ON t.id = g.ticket_id
      WHERE t.id IN ('${logisticsId}', '${paymentId}') AND g.generation_number = 1;
    `)) as string[], { timeout: 60_000 }).toEqual(["COMPLETED", "COMPLETED"]);

    const callAudit = JSON.parse(queryFixtureSql(`
      SELECT json_agg(json_build_object(
        'invocationId', invocation_id, 'intakeId', intake_id, 'operation', operation,
        'phase', phase, 'status', status, 'springFailureReason', spring_failure_reason,
        'evidence', evidence
      ) ORDER BY started_at) FROM intake_model_call;
    `)) as { invocationId: string; intakeId: string; status: string; evidence: unknown }[];
    expect(callAudit.length).toBeGreaterThan(0);
    expect(callAudit.every((call) => call.status === "SUCCEEDED")).toBe(true);
    // 诊断附件记录真实产品产生的关联标识；模型计量由 runner 与账本交叉核对。
    await testInfo.attach("core-product-evidence", {
      body: JSON.stringify({ sharedIntakeRecordId: intake.sharedIntakeRecordId, tickets, intakeCalls: callAudit }),
      contentType: "application/json",
    });

    await page.goto(`/help?ticket=${logisticsId}`);
    await expect(page.locator(".pending-compensation-card")
      .getByRole("heading", { name: "待审批", exact: true })).toBeVisible();
    const payment = await context.newPage();
    await payment.goto(`/help?ticket=${paymentId}`);
    await expect(payment.getByText("人工客服处理中", { exact: true })).toBeVisible();
    const paymentResponse = await context.request.get(`/api/customer/v2/tickets/${paymentId}`);
    expect(paymentResponse.ok()).toBe(true);
    const paymentSnapshot = (await paymentResponse.json()) as {
      ticket: { id: string; handlingMode: string };
      messages: { author: string; body: string }[];
      pendingCompensation: unknown;
    };
    expect(paymentSnapshot.ticket).toMatchObject({ id: paymentId, handlingMode: "HUMAN" });
    expect(paymentSnapshot.pendingCompensation).toBeNull();
    const paymentReplies = paymentSnapshot.messages.filter((message) => message.author === "AGENT");
    expect(paymentReplies).toHaveLength(1);
    const paymentReply = paymentReplies[0].body;
    expect(paymentReply).toMatch(/支付|付款/);
    expect(paymentReply).toMatch(/不足以确认|尚未确认|无法确认/);
    expect(paymentReply).toMatch(/人工|客服/);
    expect(paymentReply).not.toMatch(/物流延迟|补偿建议正在等待人工审批/);
    await expect(payment.getByText(paymentReply, { exact: true })).toBeVisible();

    const investigations = JSON.parse(queryFixtureSql(`
      SELECT json_agg(json_build_object(
        'kind', t.issue_kind, 'reason', t.human_handoff_reason_code,
        'capabilities', (SELECT json_agg(DISTINCT response_payload->>'capability')
          FROM agent_command_request WHERE generation_id = g.id
            AND operation = 'USE_INVESTIGATION_CAPABILITY'),
        'factTypes', (SELECT json_agg(fact_type) FROM investigation_fact WHERE generation_id = g.id),
        'proposals', (SELECT count(*) FROM compensation_proposal_revision WHERE ticket_id = t.id)
      )) FROM support_ticket t JOIN agent_processing_generation g ON g.ticket_id = t.id
      WHERE t.id IN ('${logisticsId}', '${paymentId}') AND g.generation_number = 1;
    `)) as { kind: string; reason: string | null; capabilities: string[]; factTypes: string[]; proposals: number }[];
    for (const investigation of investigations) {
      expect(investigation.capabilities).toEqual(expect.arrayContaining([
        "CONFIRM_ORDER", "READ_PAYMENT_AND_REFUNDS", "READ_COMPENSATION_AND_PENDING_ACTIONS",
      ]));
      expect(investigation.factTypes).toEqual(expect.arrayContaining([
        "ORDER", "PAYMENT", "ORDER_CANCELLATION", "REFUND_STATUS", "EXISTING_COMPENSATION", "PENDING_ACTION_COUNT",
      ]));
      expect(investigation.capabilities).not.toContain("READ_ORDER_RULES");
      if (investigation.kind === "DUPLICATE_CHARGE") {
        expect(investigation).toMatchObject({ reason: "DUPLICATE_CHARGE", proposals: 0 });
        expect(investigation.capabilities).not.toContain("READ_LOGISTICS");
        expect(investigation.capabilities).not.toContain("READ_APPLICABLE_POLICY");
        for (const fact of ["LOGISTICS_DELAY_HOURS", "LOGISTICS_DELAY_SECONDS", "LOGISTICS_STATUS", "ORDER_RULE", "POLICY"]) {
          expect(investigation.factTypes).not.toContain(fact);
        }
      } else {
        expect(investigation).toMatchObject({ reason: null, proposals: 1 });
        expect(investigation.capabilities).toEqual(expect.arrayContaining(["READ_LOGISTICS", "READ_APPLICABLE_POLICY"]));
      }
    }

    await page.goto("/help");
    await page.reload();
    const overview = page.getByRole("region", { name: "订单工单总览" });
    await expect(overview.getByRole("heading", { name: `订单 ${reference}` })).toBeVisible();
    for (const ticketId of intake.ticketIds) {
      await expect(overview.getByRole("button", { name: `打开工单 ${ticketId}`, exact: true })).toBeVisible();
    }
    await payment.reload();
    await expect(payment.getByText("人工客服处理中", { exact: true })).toBeVisible();
    await expect(payment.getByText(paymentReply, { exact: true })).toBeVisible();
    await overview.getByRole("button", { name: `打开工单 ${logisticsId}`, exact: true }).click();
    await expect(page.locator(".pending-compensation-card")
      .getByRole("heading", { name: "待审批", exact: true })).toBeVisible();

    const support = await supportContext.newPage();
    await login(support, "internal", "support-demo");
    await support.getByRole("table", { name: "待接手工单", exact: true })
      .getByRole("button", { name: `领取工单 ${paymentId}`, exact: true }).click();
    await support.getByRole("button", { name: "确认领取", exact: true }).click();
    await expect(support.getByRole("heading", { name: "人工公开回复" })).toBeVisible();
    await expect(support.getByText(paymentReply, { exact: true })).toBeVisible();
    await support.getByRole("button", { name: "释放领取", exact: true }).click();
  } finally {
    await supportContext.close();
    await context.close();
  }
});
