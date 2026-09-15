import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql, queryFixtureSql } from "./support/database";
import { intakeReply } from "./support/issue173-intake";
import {
  coreCaseBudgetStopReason,
  type CoreCaseBudget,
} from "../src/test-support/issue230-case-budget";

declare const process: { env: Record<string, string | undefined> };
type Scenario = {
  id: string;
  title: string;
  delaySeconds: number;
  description: string;
  expected: string;
  expectedTickets: number;
  method?: string;
  amount?: number;
  refunded?: boolean;
  cancelled?: boolean;
  existingCompensation?: boolean;
  duplicate?: boolean;
};
const scenarios = JSON.parse(readFileSync("/evaluation/scenarios.json", "utf8")) as Scenario[];
test.describe.configure({ mode: "default", retries: 0 });
let stop: string | null = null;
test.beforeEach(() => {
  if (!stop) {
    const ledger = JSON.parse(
      readFileSync(process.env.ISSUE230_CORE_BUDGET_PATH!, "utf8"),
    ) as CoreCaseBudget;
    stop = coreCaseBudgetStopReason(ledger, Date.now());
  }
  test.skip(stop !== null, stop ?? "");
});

function snapshot(reference: string) {
  return JSON.parse(
    queryFixtureSql(`
    WITH tickets AS (SELECT * FROM support_ticket WHERE order_reference='${reference}'),
    gens AS (SELECT g.* FROM agent_processing_generation g JOIN tickets t ON t.id=g.ticket_id)
    SELECT json_build_object(
      'capturedAt',clock_timestamp(),
      'tickets',(SELECT json_agg(json_build_object('id',id,'issueKind',issue_kind,'handlingMode',handling_mode,'lifecycleState',lifecycle_state,'reason',human_handoff_reason_code)) FROM tickets),
      'generations',(SELECT json_agg(to_jsonb(g)) FROM gens g),
      'messages',(SELECT json_agg(json_build_object('ticketId',m.ticket_id,'sequence',m.message_sequence,'author',m.author,'body',m.body,'sentAt',m.sent_at) ORDER BY m.ticket_id,m.message_sequence) FROM public_message m JOIN tickets t ON t.id=m.ticket_id),
      'facts',(SELECT json_agg(to_jsonb(f)) FROM investigation_fact f JOIN gens g ON g.id=f.generation_id),
      'commands',(SELECT json_agg(json_build_object('generationId',c.generation_id,'operation',c.operation,'at',c.created_at,'response',c.response_payload) ORDER BY c.created_at) FROM agent_command_request c JOIN gens g ON g.id=c.generation_id),
      'audit',(SELECT json_agg(to_jsonb(a) ORDER BY a.occurred_at) FROM audit_event a JOIN tickets t ON t.id=a.ticket_id),
      'events',(SELECT json_agg(json_build_object('ticketId',e.ticket_id,'sequence',e.sequence,'type',e.event_type,'generation',e.agent_generation,'at',e.occurred_at,'payload',e.payload) ORDER BY e.ticket_id,e.sequence) FROM customer_public_event e JOIN tickets t ON t.id=e.ticket_id),
      'proposals',(SELECT json_agg(json_build_object('ticketId',p.ticket_id,'generationId',p.generation_id,'status',p.status,'method',p.compensation_method,'amount',p.amount,'delaySeconds',p.delay_seconds)) FROM compensation_proposal_revision p JOIN tickets t ON t.id=p.ticket_id),
      'executions',(SELECT count(*) FROM compensation_execution WHERE order_reference='${reference}'),
      'queue',(SELECT json_agg(to_jsonb(q)) FROM shared_support_queue_entry q JOIN tickets t ON t.id=q.ticket_id)
    );`),
  ) as BusinessSnapshot;
}

type Ticket = { id: string; issueKind: string; handlingMode: string; reason: string | null };
type Intake = { status: string; issues: { kind: string }[] };
type BusinessSnapshot = {
  tickets: Ticket[];
  executions: number;
  generations: { id: string; ticket_id: string }[];
  facts: { generation_id: string; fact_type: string; fact_value: string }[];
  audit: { ticket_id: string; event_type: string }[] | null;
  proposals:
    | { ticketId: string; status: string; method: string; amount: number; delaySeconds: number }[]
    | null;
  queue: { ticket_id: string }[] | null;
};
type CustomerSnapshot = {
  messages: { author: string; body: string }[];
  pendingCompensation: { status: string } | null;
  ticket: { handlingMode: string };
};

for (const scenario of scenarios) {
  test(`E2E 20260915 ${scenario.id}`, async ({ browser }, testInfo) => {
    test.setTimeout(240_000);
    const startedAt = Date.now();
    const reference = `ORDER-EVAL-0915-${scenario.id.toUpperCase().replaceAll("_", "-")}-${crypto.randomUUID()}`;
    const phases: { name: string; at: number; elapsedMs: number; detail?: unknown }[] = [];
    const mark = (name: string, detail?: unknown) =>
      phases.push({ name, at: Date.now(), elapsedMs: Date.now() - startedAt, detail });
    const evidence: Record<string, unknown> = {
      scenario,
      reference,
      startedAt,
      phases,
      http: [],
      browserErrors: [],
    };
    executeFixtureSql(`INSERT INTO synthetic_order (order_reference,customer_id,paid_amount,currency,delay_hours,delay_seconds,paid,cancelled,fully_refunded,existing_compensation,policy_version,available_compensation_amount,duplicate_charge_suspected)
      VALUES ('${reference}','customer-demo',99.00,'CNY',${Math.floor(scenario.delaySeconds / 3600)},${scenario.delaySeconds},true,${!!scenario.cancelled},${!!scenario.refunded},${!!scenario.existingCompensation},'delay-policy-v1',50.00,${!!scenario.duplicate});`);
    const context = await newAcceptanceContext(browser);
    const page = await context.newPage();
    page.on("pageerror", (err) => (evidence.browserErrors as string[]).push(err.message));
    page.on("response", (response) => {
      const path = new URL(response.url()).pathname;
      if (path.startsWith("/api/customer/v2/") && response.request().method() === "POST") {
        (evidence.http as unknown[]).push({
          at: Date.now(),
          path,
          method: "POST",
          status: response.status(),
        });
      }
    });
    await page.addInitScript(() => {
      const state = window as unknown as { evalFirstReply?: { at: number; text: string } };
      new MutationObserver(() => {
        const log = document.querySelector('[role="log"]');
        const source = log?.querySelector(".reply-sources");
        if (!state.evalFirstReply && source && source.getClientRects().length > 0) {
          state.evalFirstReply = { at: Date.now(), text: (log as HTMLElement).innerText };
        }
      }).observe(document, { childList: true, subtree: true, characterData: true });
    });
    try {
      await login(page, "customer", "customer-demo");
      mark("logged_in");
      await page.getByLabel("订单编号").fill(reference);
      await page.getByLabel("问题描述").fill(scenario.description);
      const first = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          new URL(r.url()).pathname === "/api/customer/v2/intakes",
      );
      mark("intake_clicked");
      await page.getByRole("button", { name: "开始智能受理" }).click();
      const firstResponse = await first;
      expect(firstResponse.status()).toBe(201);
      let intake = (await firstResponse.json()) as Intake;
      evidence.intakeSnapshots = [intake];
      mark("intake_response", { status: intake.status });
      if (intake.status === "NEEDS_CLARIFICATION") {
        const answer = scenario.duplicate
          ? "我看到两笔扣款，请核查重复扣款。" +
            (scenario.expected === "split" ? "物流也确实超过预计送达时间，两件事都请处理。" : "")
          : "确实超过预计时间仍未送达，请核查物流延迟。";
        await page.getByLabel("补充受理信息").fill(answer);
        const followup = intakeReply(page);
        mark("clarification_clicked", { answer });
        await page.getByRole("button", { name: "发送给智能受理", exact: true }).click();
        const followed = await followup;
        expect(followed.status()).toBe(201);
        intake = (await followed.json()) as Intake;
        (evidence.intakeSnapshots as unknown[]).push(intake);
        mark("clarification_response", { status: intake.status });
      }
      expect(intake.status).toBe("READY_TO_CONFIRM");
      expect(intake.issues.map((i: { kind: string }) => i.kind).sort()).toEqual(
        scenario.expected === "split"
          ? ["DUPLICATE_CHARGE", "LOGISTICS_DELAY"]
          : [scenario.expected === "payment" ? "DUPLICATE_CHARGE" : "LOGISTICS_DELAY"],
      );
      const confirmed = intakeReply(page);
      mark("confirmation_clicked");
      await page
        .getByRole("button", {
          name: scenario.expectedTickets === 2 ? "确认并原子创建 2 张工单" : "确认，就是这个问题",
          exact: true,
        })
        .click();
      const confirmedResponse = await confirmed;
      expect(confirmedResponse.status()).toBe(201);
      const created = (await confirmedResponse.json()) as { ticketIds: string[] };
      evidence.confirmation = created;
      expect(created.ticketIds).toHaveLength(scenario.expectedTickets);
      mark("tickets_created");
      const ids = created.ticketIds;
      let terminals: { ticketId: string; status: string }[] = [];
      await expect
        .poll(
          () => {
            terminals = JSON.parse(
              queryFixtureSql(
                `SELECT json_agg(json_build_object('ticketId',ticket_id,'status',status)) FROM agent_processing_generation WHERE ticket_id IN (${ids.map((id) => `'${id}'`).join(",")});`,
              ),
            ) as typeof terminals;
            return (
              terminals?.length === ids.length &&
              terminals.every((g) => ["COMPLETED", "HANDED_OFF", "SUPERSEDED"].includes(g.status))
            );
          },
          { timeout: 120_000, intervals: [150, 250, 500] },
        )
        .toBe(true);
      mark("all_terminal", terminals);
      evidence.firstReplyUi = await page.evaluate(
        () => (window as unknown as { evalFirstReply?: unknown }).evalFirstReply ?? null,
      );
      const state = snapshot(reference);
      evidence.business = state;
      const tickets = state.tickets;
      expect(tickets).toHaveLength(scenario.expectedTickets);
      expect(state.executions).toBe(0);
      for (const ticket of tickets) {
        const terminal = terminals.find((g) => g.ticketId === ticket.id)!;
        if (scenario.expected === "human_no_proposal") {
          expect(ticket.handlingMode).toBe("HUMAN");
          expect(state.proposals ?? []).toHaveLength(0);
          expect(["COMPLETED", "HANDED_OFF"]).toContain(terminal.status);
          expect(ticket.reason).not.toMatch(
            /FAILED|INVALID|TIMEOUT|BUDGET|UNKNOWN_ACTION|MODEL_CALL/,
          );
          expect(
            (state.queue ?? []).some((q: { ticket_id: string }) => q.ticket_id === ticket.id),
          ).toBe(true);
        } else {
          expect(terminal.status, JSON.stringify({ ticket, terminal })).toBe("COMPLETED");
          expect(
            (state.audit ?? []).filter(
              (a: { ticket_id: string; event_type: string }) =>
                a.ticket_id === ticket.id && a.event_type === "AGENT_CONCLUSION_ACCEPTED",
            ),
          ).toHaveLength(1);
          const proposals = (state.proposals ?? []).filter(
            (p: { ticketId: string }) => p.ticketId === ticket.id,
          );
          if (ticket.issueKind === "DUPLICATE_CHARGE") {
            expect(ticket.handlingMode).toBe("HUMAN");
            expect(ticket.reason).toBe("DUPLICATE_CHARGE");
            expect(proposals).toHaveLength(0);
            const generation = state.generations.find(
              (g: { ticket_id: string }) => g.ticket_id === ticket.id,
            )!;
            const facts = Object.fromEntries(
              state.facts
                .filter((f: { generation_id: string }) => f.generation_id === generation.id)
                .map((f: { fact_type: string; fact_value: string }) => [f.fact_type, f.fact_value]),
            );
            expect(facts.PAYMENT).toBe("PAID");
            expect(facts.REFUND_STATUS).toBe(
              scenario.refunded ? "FULLY_REFUNDED" : "NOT_FULLY_REFUNDED",
            );
            expect(facts.LOGISTICS_DELAY_SECONDS).toBeUndefined();
          } else if (scenario.expected === "no_compensation") {
            expect(proposals).toHaveLength(0);
          } else {
            expect(proposals).toEqual([
              expect.objectContaining({
                status: "PENDING_APPROVAL",
                method: scenario.method,
                amount: scenario.amount,
                delaySeconds: scenario.delaySeconds,
              }),
            ]);
          }
        }
        await page.goto(`/help?ticket=${ticket.id}`);
        const apiResponse = await page.request.get(`/api/customer/v2/tickets/${ticket.id}`);
        expect(apiResponse.ok()).toBe(true);
        const customer = (await apiResponse.json()) as CustomerSnapshot;
        const replies = customer.messages.filter((m) => m.author === "AGENT");
        if (scenario.expected !== "human_no_proposal") {
          expect(replies).toHaveLength(1);
          await expect(
            page.getByRole("log").getByText(replies[0].body, { exact: true }),
          ).toBeVisible();
        } else {
          await expect(page.getByText("人工客服处理中", { exact: true })).toBeVisible();
        }
        mark(`visible_${ticket.issueKind}`);
        await page.reload();
        await expect(page.getByRole("log")).toBeVisible();
        for (const reply of replies)
          await expect(page.getByRole("log").getByText(reply.body, { exact: true })).toBeVisible();
        const after = (await (
          await page.request.get(`/api/customer/v2/tickets/${ticket.id}`)
        ).json()) as CustomerSnapshot;
        expect(after.messages).toEqual(customer.messages);
        mark(`refreshed_${ticket.issueKind}`);
      }
      if (scenario.expected === "split") {
        await page.goto("/help");
        const overview = page.getByRole("region", { name: "订单工单总览" });
        for (const ticket of tickets)
          await expect(
            overview.getByRole("button", { name: `打开工单 ${ticket.id}`, exact: true }),
          ).toBeVisible();
        const supportContext = await newAcceptanceContext(browser);
        try {
          const support = await supportContext.newPage();
          await login(support, "internal", "support-demo");
          const payment = tickets.find((t) => t.issueKind === "DUPLICATE_CHARGE")!;
          await support
            .getByRole("table", { name: "待接手工单", exact: true })
            .getByRole("button", { name: `领取工单 ${payment.id}`, exact: true })
            .click();
          await support.getByRole("button", { name: "确认领取", exact: true }).click();
          const facts = support.getByRole("region", { name: "调查事实" });
          await expect(facts.getByText("PAYMENT", { exact: true })).toBeVisible();
          await expect(facts.getByText("NOT_FULLY_REFUNDED", { exact: true })).toBeVisible();
          await support.getByRole("button", { name: "释放领取", exact: true }).click();
          mark("support_claim_read_release");
        } finally {
          await supportContext.close();
        }
      }
      mark("checks_passed");
    } finally {
      evidence.business = snapshot(reference);
      evidence.endedAt = Date.now();
      await testInfo.attach("evaluation-case", {
        body: JSON.stringify(evidence),
        contentType: "application/json",
      });
      await page.screenshot({ path: `/artifacts/${scenario.id}.png`, fullPage: true });
      await context.close();
    }
  });
}
