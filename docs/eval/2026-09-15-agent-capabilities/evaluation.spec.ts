import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql, queryFixtureSql } from "./support/database";
import { intakeReply } from "./support/issue173-intake";
import {
  coreCaseBudgetStopReason,
  type CoreCaseBudget,
} from "../src/test-support/issue230-case-budget";

declare const process: { env: Record<string, string | undefined> };
type Order = {
  slot: string;
  delaySeconds: number;
  kinds: string[];
  outcome: string;
  amount?: number;
  method?: string;
  refunded?: boolean;
  duplicate?: boolean;
  logisticsStatus?: string;
};
type Scenario = {
  id: string;
  title: string;
  description: string;
  clarification: string;
  orders: Order[];
  initialClarificationRequired?: boolean;
  initialOrderUnknown?: boolean;
  initialKinds?: string[];
  followup?: string;
  humanPreference?: boolean;
  supplemental?: boolean;
  qualityFocus: string;
};
type Intake = {
  intakeId: string;
  status: string;
  candidateOrder: { reference: string } | null;
  issues: { kind: string }[];
  ticketIds: string[];
  remainingOrderCount: number;
  duplicateMatches: unknown[];
  sharedIntakeRecordId: string | null;
};
type Generation = { id: string; ticket_id: string; status: string; generation_number: number };
type Ticket = {
  id: string;
  orderReference: string;
  issueKind: string;
  handlingMode: string;
  reason: string | null;
  humanPreference: boolean;
};
type Message = {
  ticketId: string;
  sequence: number;
  author: string;
  body: string;
  knowledge: unknown;
};
type Proposal = {
  ticketId: string;
  generationId: string;
  method: string;
  amount: number;
  delaySeconds: number;
  status: string;
};
type Business = {
  tickets: Ticket[];
  generations: Generation[];
  messages: Message[];
  facts: { generation_id: string; fact_type: string; fact_value: string }[];
  commands: {
    generationId: string;
    operation: string;
    response: { accepted?: boolean; capability?: string };
  }[];
  proposals: Proposal[];
  executions: number;
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

function snapshot(references: string[], intakeId?: string) {
  return JSON.parse(
    queryFixtureSql(`
    WITH tickets AS (SELECT * FROM support_ticket WHERE order_reference IN (${references.map((r) => `'${r}'`).join(",")})),
    gens AS (SELECT g.* FROM agent_processing_generation g JOIN tickets t ON t.id=g.ticket_id)
    SELECT json_build_object(
      'capturedAt',clock_timestamp(),
      'tickets',coalesce((SELECT json_agg(json_build_object('id',id,'orderReference',order_reference,'issueKind',issue_kind,'handlingMode',handling_mode,'lifecycleState',lifecycle_state,'reason',human_handoff_reason_code,'humanPreference',customer_human_preference)) FROM tickets),'[]'),
      'generations',coalesce((SELECT json_agg(to_jsonb(g) ORDER BY ticket_id,generation_number) FROM gens g),'[]'),
      'messages',coalesce((SELECT json_agg(json_build_object('ticketId',m.ticket_id,'sequence',m.message_sequence,'author',m.author,'body',m.body,'knowledge',m.knowledge,'sentAt',m.sent_at) ORDER BY m.ticket_id,m.message_sequence) FROM public_message m JOIN tickets t ON t.id=m.ticket_id),'[]'),
      'facts',coalesce((SELECT json_agg(to_jsonb(f)) FROM investigation_fact f JOIN gens g ON g.id=f.generation_id),'[]'),
      'commands',coalesce((SELECT json_agg(json_build_object('generationId',c.generation_id,'operation',c.operation,'at',c.created_at,'response',c.response_payload) ORDER BY c.created_at) FROM agent_command_request c JOIN gens g ON g.id=c.generation_id),'[]'),
      'audit',coalesce((SELECT json_agg(to_jsonb(a) ORDER BY a.occurred_at) FROM audit_event a JOIN tickets t ON t.id=a.ticket_id),'[]'),
      'events',coalesce((SELECT json_agg(json_build_object('ticketId',e.ticket_id,'sequence',e.sequence,'type',e.event_type,'generation',e.agent_generation,'at',e.occurred_at,'payload',e.payload) ORDER BY e.ticket_id,e.sequence) FROM customer_public_event e JOIN tickets t ON t.id=e.ticket_id),'[]'),
      'proposals',coalesce((SELECT json_agg(json_build_object('ticketId',p.ticket_id,'generationId',p.generation_id,'status',p.status,'method',p.compensation_method,'amount',p.amount,'delaySeconds',p.delay_seconds)) FROM compensation_proposal_revision p JOIN tickets t ON t.id=p.ticket_id),'[]'),
      'executions',(SELECT count(*) FROM compensation_execution WHERE order_reference IN (${references.map((r) => `'${r}'`).join(",")})),
      'queue',coalesce((SELECT json_agg(to_jsonb(q)) FROM shared_support_queue_entry q JOIN tickets t ON t.id=q.ticket_id),'[]'),
      'intakeCalls',coalesce((SELECT json_agg(json_build_object('intakeId',intake_id,'invocationId',invocation_id,'phase',phase,'status',status,'failure',spring_failure_reason,'evidence',evidence) ORDER BY started_at) FROM intake_model_call WHERE intake_id=${intakeId ? `'${intakeId}'::uuid` : "NULL::uuid"}),'[]')
    );`),
  ) as Business;
}

async function terminalState(references: string[], ids: string[], generation = 1) {
  let state = snapshot(references);
  await expect
    .poll(
      () => {
        state = snapshot(references);
        return ids.every((id) =>
          state.generations.some(
            (g) =>
              g.ticket_id === id &&
              g.generation_number === generation &&
              ["COMPLETED", "HANDED_OFF", "SUPERSEDED"].includes(g.status),
          ),
        );
      },
      { timeout: 120_000, intervals: [150, 250, 500] },
    )
    .toBe(true);
  return state;
}

async function showReplies(page: Page, ticket: Ticket, evidence: Record<string, unknown>) {
  await page.goto(`/help?ticket=${ticket.id}`);
  const response = await page.request.get(`/api/customer/v2/tickets/${ticket.id}`);
  expect(response.ok()).toBe(true);
  const customer = (await response.json()) as { messages: { author: string; body: string }[] };
  (evidence.customerSnapshots as unknown[]).push({ ticketId: ticket.id, customer });
  await expect(page.getByRole("log")).toBeVisible();
  for (const reply of customer.messages.filter((m) => m.author === "AGENT")) {
    expect(reply.body.trim()).not.toBe("");
    await expect(
      page.getByRole("log").getByText(reply.body, { exact: true }).first(),
    ).toBeVisible();
  }
  await page.reload();
  const refreshed = await page.request.get(`/api/customer/v2/tickets/${ticket.id}`);
  expect(((await refreshed.json()) as typeof customer).messages).toEqual(customer.messages);
}

function verifyTicket(state: Business, ticket: Ticket, order: Order, generationNumber = 1) {
  const generation = state.generations.find(
    (g) => g.ticket_id === ticket.id && g.generation_number === generationNumber,
  )!;
  expect(generation?.status, JSON.stringify({ ticket, generation })).toBe("COMPLETED");
  expect(
    state.commands.filter(
      (c) =>
        c.generationId === generation.id &&
        c.operation === "SUBMIT_INVESTIGATION_CONCLUSION" &&
        c.response.accepted === true,
    ),
  ).toHaveLength(1);
  const facts = Object.fromEntries(
    state.facts
      .filter((f) => f.generation_id === generation.id)
      .map((f) => [f.fact_type, f.fact_value]),
  );
  expect(facts.ORDER).toBe(ticket.orderReference);
  const proposals = state.proposals.filter(
    (p) => p.ticketId === ticket.id && p.generationId === generation.id,
  );
  if (ticket.issueKind === "DUPLICATE_CHARGE") {
    expect(ticket.handlingMode).toBe("HUMAN");
    expect(ticket.reason).toBe("DUPLICATE_CHARGE");
    expect(facts.PAYMENT).toBe("PAID");
    expect(facts.REFUND_STATUS).toBe(order.refunded ? "FULLY_REFUNDED" : "NOT_FULLY_REFUNDED");
    expect(facts.LOGISTICS_DELAY_SECONDS).toBeUndefined();
    expect(proposals).toHaveLength(0);
  } else {
    expect(facts.LOGISTICS_DELAY_SECONDS).toBe(String(order.delaySeconds));
    expect(facts.LOGISTICS_DELAY_HOURS).toBe(String(Math.floor(order.delaySeconds / 3600)));
    if (order.outcome === "proposal") {
      expect(proposals).toEqual([
        expect.objectContaining({
          status: "PENDING_APPROVAL",
          method: order.method,
          amount: order.amount,
          delaySeconds: order.delaySeconds,
        }),
      ]);
    } else {
      expect(proposals).toHaveLength(0);
    }
    if (order.outcome === "signed_handoff") {
      expect(facts.LOGISTICS_STATUS).toBe("SIGNED");
      expect(ticket.handlingMode).toBe("HUMAN");
      expect(ticket.reason).toBe("PACKAGE_SIGNED_NOT_RECEIVED");
    }
  }
  expect(
    state.messages.filter((m) => m.ticketId === ticket.id && m.author === "AGENT").length,
  ).toBeGreaterThanOrEqual(generationNumber);
}

for (const scenario of scenarios) {
  test(`Agent capabilities 20260915 ${scenario.id}`, async ({ browser }, testInfo) => {
    test.setTimeout(300_000);
    const startedAt = Date.now();
    const references = scenario.orders.map(
      (order) =>
        `ORDER-CAP-0915-${scenario.id.toUpperCase().replaceAll("_", "-")}-${order.slot}-${crypto.randomUUID()}`,
    );
    const replace = (text: string) =>
      scenario.orders.reduce(
        (value, order, index) => value.replaceAll(`{${order.slot}}`, references[index]),
        text,
      );
    const phases: { name: string; at: number; elapsedMs: number; detail?: unknown }[] = [];
    const mark = (name: string, detail?: unknown) =>
      phases.push({ name, at: Date.now(), elapsedMs: Date.now() - startedAt, detail });
    const evidence: Record<string, unknown> = {
      scenario,
      references,
      startedAt,
      phases,
      intakeSnapshots: [],
      customerSnapshots: [],
      http: [],
      browserErrors: [],
    };
    for (const [index, order] of scenario.orders.entries()) {
      executeFixtureSql(`INSERT INTO synthetic_order (order_reference,customer_id,paid_amount,currency,delay_hours,delay_seconds,paid,cancelled,fully_refunded,existing_compensation,policy_version,available_compensation_amount,duplicate_charge_suspected,logistics_status)
        VALUES ('${references[index]}','customer-demo',99.00,'CNY',${Math.floor(order.delaySeconds / 3600)},${order.delaySeconds},true,false,${!!order.refunded},false,'delay-policy-v1',50.00,${!!order.duplicate},'${order.logisticsStatus ?? "IN_TRANSIT"}');`);
    }
    const context = await newAcceptanceContext(browser);
    const page = await context.newPage();
    let intakeId: string | undefined;
    page.on("pageerror", (error) => (evidence.browserErrors as string[]).push(error.message));
    page.on("response", (response) => {
      const path = new URL(response.url()).pathname;
      if (path.startsWith("/api/customer/v2/") && response.request().method() === "POST") {
        (evidence.http as unknown[]).push({ at: Date.now(), path, status: response.status() });
      }
    });
    await page.addInitScript(() => {
      const state = window as unknown as { evalFirstReply?: { at: number; text: string } };
      new MutationObserver(() => {
        const log = document.querySelector('[role="log"]');
        const source = log?.querySelector(".reply-sources");
        if (!state.evalFirstReply && source && source.getClientRects().length > 0)
          state.evalFirstReply = { at: Date.now(), text: (log as HTMLElement).innerText };
      }).observe(document, { childList: true, subtree: true, characterData: true });
    });
    try {
      await login(page, "customer", "customer-demo");
      await expect(page.getByLabel("订单编号")).toHaveValue("");
      await page.getByLabel("问题描述").fill(replace(scenario.description));
      const first = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          new URL(r.url()).pathname === "/api/customer/v2/intakes",
      );
      mark("intake_clicked");
      await page.getByRole("button", { name: "开始智能受理" }).click();
      const response = await first;
      expect(response.status()).toBe(201);
      let intake = (await response.json()) as Intake;
      intakeId = intake.intakeId;
      (evidence.intakeSnapshots as unknown[]).push(intake);
      mark("intake_response", { status: intake.status });
      expect(intake.ticketIds).toHaveLength(0);
      expect(snapshot(references).tickets).toHaveLength(0);
      if (scenario.initialClarificationRequired) expect(intake.status).toBe("NEEDS_CLARIFICATION");
      if (scenario.initialOrderUnknown) expect(intake.candidateOrder).toBeNull();
      if (scenario.initialKinds)
        expect(intake.issues.map((i) => i.kind).sort()).toEqual([...scenario.initialKinds].sort());
      if (scenario.orders.length > 1) expect(intake.remainingOrderCount).toBe(1);
      for (const [index, order] of scenario.orders.entries()) {
        if (intake.status === "NEEDS_CLARIFICATION") {
          await page.getByLabel("补充受理信息").fill(replace(scenario.clarification));
          const clarified = intakeReply(page);
          mark(`clarification_${index}_clicked`);
          await page.getByRole("button", { name: "发送给智能受理", exact: true }).click();
          const clarifiedResponse = await clarified;
          expect(clarifiedResponse.status()).toBe(201);
          intake = (await clarifiedResponse.json()) as Intake;
          (evidence.intakeSnapshots as unknown[]).push(intake);
        }
        expect(intake.status).toBe("READY_TO_CONFIRM");
        expect(intake.candidateOrder?.reference).toBe(references[index]);
        expect(intake.issues.map((i) => i.kind).sort()).toEqual([...order.kinds].sort());
        expect(intake.duplicateMatches).toHaveLength(0);
        const confirmed = intakeReply(page);
        mark(`confirmation_${index}_clicked`);
        await page
          .getByRole("button", {
            name: order.kinds.length === 2 ? "确认并原子创建 2 张工单" : "确认，就是这个问题",
            exact: true,
          })
          .click();
        const confirmedResponse = await confirmed;
        expect(confirmedResponse.status()).toBe(201);
        intake = (await confirmedResponse.json()) as Intake;
        (evidence.intakeSnapshots as unknown[]).push(intake);
        const confirmedCount = scenario.orders
          .slice(0, index + 1)
          .reduce((sum, item) => sum + item.kinds.length, 0);
        expect(intake.ticketIds).toHaveLength(confirmedCount);
        const current = snapshot(references);
        expect(current.tickets).toHaveLength(confirmedCount);
        expect(
          current.tickets.every((t) => references.slice(0, index + 1).includes(t.orderReference)),
        ).toBe(true);
        mark(`tickets_${index}_created`);
      }
      expect(intake.status).toBe("CONFIRMED");
      const ids = intake.ticketIds;
      evidence.ticketIds = ids;
      let state = await terminalState(references, ids);
      mark("all_terminal");
      evidence.firstReplyUi = await page.evaluate(
        () => (window as unknown as { evalFirstReply?: unknown }).evalFirstReply ?? null,
      );
      evidence.initialBusiness = state;
      expect(state.executions).toBe(0);
      for (const [index, order] of scenario.orders.entries()) {
        expect(
          state.tickets
            .filter((ticket) => ticket.orderReference === references[index])
            .map((ticket) => ticket.issueKind)
            .sort(),
        ).toEqual([...order.kinds].sort());
      }
      for (const ticket of state.tickets) {
        const order = scenario.orders[references.indexOf(ticket.orderReference)];
        expect(order.kinds).toContain(ticket.issueKind);
        verifyTicket(state, ticket, order);
        await showReplies(page, ticket, evidence);
      }
      if (scenario.followup) {
        const ticket = state.tickets[0];
        expect(ticket.handlingMode, "首轮必须保留Agent处理权才能测追加问题").toBe("AGENT");
        const beforeReplies = state.messages.filter((m) => m.author === "AGENT");
        await page.goto(`/help?ticket=${ticket.id}`);
        await page.getByPlaceholder("继续补充消息", { exact: true }).fill(scenario.followup);
        const appended = page.waitForResponse(
          (r) =>
            r.request().method() === "POST" &&
            new URL(r.url()).pathname === `/api/customer/v2/tickets/${ticket.id}/messages`,
        );
        mark("followup_clicked");
        await page.getByRole("button", { name: "发送新消息", exact: true }).click();
        expect((await appended).status()).toBe(202);
        state = await terminalState(references, ids, 2);
        mark("followup_terminal");
        expect(
          state.messages.filter((m) => m.author === "CUSTOMER" && m.body === scenario.followup),
        ).toHaveLength(1);
        if (scenario.humanPreference) {
          expect(state.tickets[0].handlingMode).toBe("HUMAN");
          expect(state.tickets[0].reason).toBe("CUSTOMER_REQUESTED_HUMAN");
          evidence.explicitUiHumanPreferenceObserved = state.tickets[0].humanPreference;
          expect(state.messages.filter((m) => m.author === "AGENT")).toEqual(beforeReplies);
          expect(state.proposals).toHaveLength(0);
        } else {
          verifyTicket(state, state.tickets[0], scenario.orders[0], 2);
        }
        await showReplies(page, state.tickets[0], evidence);
      }
      if (scenario.supplemental) {
        const optional = state.commands.filter(
          (c) => c.operation === "SEARCH_KNOWLEDGE" || c.response.capability === "READ_ORDER_RULES",
        );
        evidence.supplemental = {
          ruleRead: optional.some((c) => c.response.capability === "READ_ORDER_RULES"),
          knowledgeSearch: optional.some((c) => c.operation === "SEARCH_KNOWLEDGE"),
          publicKnowledge: state.messages
            .filter((m) => m.author === "AGENT")
            .map((m) => m.knowledge),
          commands: optional,
        };
        // 是否选中正确能力与是否回答充分分别记录，不把无意义多调工具当成功。
        expect(
          optional.length,
          "提出明确的补充规则/指南问题后至少应取得一种相关新依据",
        ).toBeGreaterThan(0);
      }
      expect(state.executions).toBe(0);
      mark("automatic_checks_passed");
    } finally {
      const captureErrors: string[] = [];
      try {
        try {
          evidence.business = snapshot(references, intakeId);
        } catch (error) {
          captureErrors.push(`business: ${String(error)}`);
        }
        try {
          await page.screenshot({
            path: `/artifacts/${scenario.id}.png`,
            fullPage: true,
            animations: "disabled",
          });
        } catch (error) {
          captureErrors.push(`screenshot: ${String(error)}`);
        }
        evidence.endedAt = Date.now();
        evidence.captureErrors = captureErrors;
        await testInfo.attach("evaluation-case", {
          body: JSON.stringify(evidence),
          contentType: "application/json",
        });
      } finally {
        await context.close();
      }
    }
  });
}
