import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql, queryFixtureSql } from "./support/database";
import { intakeReply } from "./support/issue173-intake";

for (const fullyRefunded of [false, true]) {
  test(`Issue #229 ${fullyRefunded ? "已全额退款" : "尚未全额退款"}的重复扣款诉求仍交人工核查`, async ({
    browser,
  }) => {
    test.setTimeout(90_000);
    const reference = `ORDER-ISSUE-229-${crypto.randomUUID()}`;
    // 仅准备本轮合成订单。保留非零物流事实, 检查支付调查不读取它。
    executeFixtureSql(`
      INSERT INTO synthetic_order (
        order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
        paid, cancelled, fully_refunded, existing_compensation, policy_version,
        available_compensation_amount, duplicate_charge_suspected
      ) VALUES (
        '${reference}', 'customer-demo', 99.00, 'CNY', 80, 288000,
        true, false, ${fullyRefunded}, false, 'delay-policy-v1', 20.00, true
      );
    `);
    const context = await newAcceptanceContext(browser);
    const supportContext = await newAcceptanceContext(browser);
    try {
      const page = await context.newPage();
      await login(page, "customer", "customer-demo");
      await page.getByLabel("问题描述").fill(`${reference} 疑似重复扣款，请帮我核实`);
      await page.getByRole("button", { name: "开始智能受理" }).click();
      await expect(page.getByRole("heading", { name: "再帮我确认一点" })).toBeVisible();
      await page.getByLabel("补充受理信息").fill("我看到扣了两次，请继续核查");
      const clarified = intakeReply(page);
      await page.getByRole("button", { name: "发送给智能受理" }).click();
      const candidate = (await (await clarified).json()) as {
        status: string;
        issues: { kind: string }[];
      };
      expect(candidate.status).toBe("READY_TO_CONFIRM");
      expect(candidate.issues.map((issue) => issue.kind)).toEqual(["DUPLICATE_CHARGE"]);
      const confirmed = intakeReply(page);
      await page.getByRole("button", { name: "确认，就是这个问题" }).click();
      const accepted = await confirmed;
      expect(accepted.status()).toBe(201);
      const intake = (await accepted.json()) as { status: string; ticketIds: string[] };
      expect(intake.status).toBe("CONFIRMED");
      expect(intake.ticketIds).toHaveLength(1);
      const ticketId = intake.ticketIds[0];
      expect(ticketId).toMatch(/^[0-9a-f-]{36}$/i);
      await expect(page.getByText("人工客服处理中", { exact: true })).toBeVisible({
        timeout: 60_000,
      });

      const snapshotResponse = await context.request.get(`/api/customer/v2/tickets/${ticketId}`);
      expect(snapshotResponse.ok()).toBe(true);
      const snapshot = (await snapshotResponse.json()) as {
        ticket: { id: string; handlingMode: string };
        messages: { author: string; body: string }[];
      };
      expect(snapshot.ticket).toMatchObject({ id: ticketId, handlingMode: "HUMAN" });
      const replies = snapshot.messages.filter((message) => message.author === "AGENT");
      expect(replies).toHaveLength(1);
      const reply = replies[0].body;
      expect(reply).toMatch(/支付|付款|已付/);
      expect(reply).toMatch(
        fullyRefunded
          ? /已(?:完成)?(?:全额|全部)退款|全额退款状态为已完成/
          : /未(?:完成)?(?:全额|全部)退款|全额退款状态为未完成/,
      );
      expect(reply).toMatch(/无法|不能|不足以确认|尚未确认|尚未.*核实|待.*核实/);
      expect(reply).toMatch(/人工|客服/);
      expect(reply).not.toMatch(/已查明.*原因|已确认.*重复扣款|已为您退款|已为你退款/);
      await expect(page.getByText(reply, { exact: true })).toBeVisible();
      const replyIndex = snapshot.messages.findIndex((message) => message.body === reply);
      expect(
        snapshot.messages.slice(replyIndex + 1).some((message) => message.author === "SUPPORT"),
      ).toBe(true);

      const evidence = JSON.parse(
        queryFixtureSql(`
          SELECT json_build_object(
            'generationStatus', g.status, 'reason', t.human_handoff_reason_code,
            'capabilities', (SELECT json_agg(DISTINCT response_payload->>'capability')
              FROM agent_command_request WHERE generation_id = g.id
                AND operation = 'USE_INVESTIGATION_CAPABILITY'),
            'factTypes', (SELECT json_agg(fact_type) FROM investigation_fact WHERE generation_id = g.id),
            'refundStatus', (SELECT fact_value FROM investigation_fact
              WHERE generation_id = g.id AND fact_type = 'REFUND_STATUS'),
            'acceptedConclusions', (SELECT count(*) FROM audit_event
              WHERE ticket_id = t.id AND event_type = 'AGENT_CONCLUSION_ACCEPTED'),
            'proposals', (SELECT count(*) FROM compensation_proposal_revision WHERE ticket_id = t.id),
            'executions', (SELECT count(*) FROM compensation_execution WHERE order_reference = t.order_reference),
            'autoResolutions', (SELECT count(*) FROM ticket_auto_resolution WHERE ticket_id = t.id)
            , 'queueEntries', (SELECT count(*) FROM shared_support_queue_entry
              WHERE ticket_id = t.id AND reason_code = 'AGENT_HUMAN_HANDOFF')
          ) FROM support_ticket t JOIN agent_processing_generation g ON g.ticket_id = t.id
          WHERE t.id = '${ticketId}' AND g.generation_number = 1;
        `),
      ) as {
        generationStatus: string;
        reason: string;
        capabilities: string[];
        factTypes: string[];
        refundStatus: string;
        acceptedConclusions: number;
        proposals: number;
        executions: number;
        autoResolutions: number;
        queueEntries: number;
      };
      expect(evidence).toMatchObject({
        generationStatus: "COMPLETED",
        reason: "DUPLICATE_CHARGE",
        refundStatus: fullyRefunded ? "FULLY_REFUNDED" : "NOT_FULLY_REFUNDED",
        acceptedConclusions: 1,
        proposals: 0,
        executions: 0,
        autoResolutions: 0,
        queueEntries: 1,
      });
      expect(evidence.capabilities).toEqual(
        expect.arrayContaining([
          "CONFIRM_ORDER",
          "READ_PAYMENT_AND_REFUNDS",
          "READ_COMPENSATION_AND_PENDING_ACTIONS",
        ]),
      );
      expect(evidence.factTypes).toEqual(
        expect.arrayContaining([
          "ORDER",
          "PAYMENT",
          "ORDER_CANCELLATION",
          "REFUND_STATUS",
          "EXISTING_COMPENSATION",
          "PENDING_ACTION_COUNT",
        ]),
      );
      for (const capability of ["READ_LOGISTICS", "READ_ORDER_RULES", "READ_APPLICABLE_POLICY"]) {
        expect(evidence.capabilities).not.toContain(capability);
      }
      for (const fact of [
        "LOGISTICS_DELAY_HOURS",
        "LOGISTICS_DELAY_SECONDS",
        "LOGISTICS_STATUS",
        "ORDER_RULE",
        "POLICY",
      ]) {
        expect(evidence.factTypes).not.toContain(fact);
      }
      const reloaded = page.waitForResponse(
        (response) =>
          response.request().method() === "GET" &&
          new URL(response.url()).pathname === `/api/customer/v2/tickets/${ticketId}`,
      );
      await page.reload();
      const restored = (await (await reloaded).json()) as typeof snapshot;
      expect(restored.ticket).toMatchObject({ id: ticketId, handlingMode: "HUMAN" });
      expect(restored.messages).toEqual(snapshot.messages);
      await expect(page.getByText(reply, { exact: true })).toBeVisible();
      await expect(page.getByText("人工客服处理中", { exact: true })).toBeVisible();

      if (!fullyRefunded) {
        const support = await supportContext.newPage();
        await login(support, "internal", "support-demo");
        await expect(support.getByRole("heading", { name: "客服共享队列" })).toBeVisible();
        await expect(
          support.getByRole("button", { name: `领取工单 ${ticketId}`, exact: true }),
        ).toBeVisible();
        await support
          .getByRole("table", { name: "待接手工单", exact: true })
          .getByRole("button", { name: `领取工单 ${ticketId}`, exact: true })
          .click();
        await support.getByRole("button", { name: "确认领取", exact: true }).click();
        await expect(support.getByRole("heading", { name: "人工公开回复" })).toBeVisible();
        await expect(support.getByText(reply, { exact: true })).toBeVisible();
        await support.getByRole("button", { name: "释放领取", exact: true }).click();
      }
    } finally {
      await supportContext.close();
      await context.close();
    }
  });
}
