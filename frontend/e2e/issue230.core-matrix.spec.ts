import { expect, test, type Page } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql, queryFixtureSql } from "./support/database";
import { createSingleTicket, intakeReply } from "./support/issue173-intake";

declare const process: { env: Record<string, string | undefined> };

const cases = [
  "no_compensation",
  "pending_approval",
  "payment_handoff",
  "split_recovery",
  "generation_fence",
] as const;
type CoreCase = (typeof cases)[number];
const selectedCase = process.env.ISSUE230_CORE_CASE;
const selectedSample = process.env.ISSUE230_CORE_SAMPLE;
if (selectedCase && !cases.includes(selectedCase as CoreCase)) throw new Error("未知核心场景");
if (selectedSample && !["1", "2"].includes(selectedSample)) throw new Error("核心样本只能为1或2");
test.describe.configure({ mode: "serial", retries: 0 });

function prepare(caseName: CoreCase, sample: number) {
  const reference = `ORDER-CORE-${caseName.toUpperCase().replaceAll("_", "-")}-${sample}-${crypto.randomUUID()}`;
  const delay = caseName === "no_compensation" ? [6, 12][sample - 1] : [48, 80][sample - 1];
  const refunded = sample === 2 && caseName === "payment_handoff";
  executeFixtureSql(`
    INSERT INTO synthetic_order (order_reference, customer_id, paid_amount, currency,
      delay_hours, delay_seconds, paid, cancelled, fully_refunded, existing_compensation,
      policy_version, available_compensation_amount, duplicate_charge_suspected)
    VALUES ('${reference}', 'customer-demo', 99.00, 'CNY', ${delay}, ${delay * 3600},
      true, false, ${refunded}, false, 'delay-policy-v1', 20.00, true);
  `);
  return { reference, refunded };
}

async function createPaymentIntake(page: Page, reference: string, split: boolean) {
  await page
    .getByLabel("问题描述")
    .fill(`${reference} ${split ? "物流延迟，而且" : ""}疑似重复扣款，请核查`);
  await page.getByRole("button", { name: "开始智能受理" }).click();
  await expect(page.getByRole("heading", { name: "再帮我确认一点" })).toBeVisible();
  await page.getByLabel("补充受理信息").fill("我看到扣了两次，请继续核查");
  const clarification = intakeReply(page);
  await page.getByRole("button", { name: "发送给智能受理" }).click();
  const candidate = (await (await clarification).json()) as {
    status: string;
    issues: { kind: string }[];
  };
  expect(candidate.status).toBe("READY_TO_CONFIRM");
  expect(candidate.issues.map(({ kind }) => kind).sort()).toEqual(
    split ? ["DUPLICATE_CHARGE", "LOGISTICS_DELAY"] : ["DUPLICATE_CHARGE"],
  );
  const confirmation = intakeReply(page);
  await page
    .getByRole("button", { name: split ? "确认并原子创建 2 张工单" : "确认，就是这个问题" })
    .click();
  const response = await confirmation;
  expect(response.status()).toBe(201);
  const intake = (await response.json()) as {
    status: string;
    ticketIds: string[];
    sharedIntakeRecordId: string;
  };
  expect(intake.status).toBe("CONFIRMED");
  expect(intake.ticketIds).toHaveLength(split ? 2 : 1);
  expect(new Set(intake.ticketIds).size).toBe(intake.ticketIds.length);
  return intake;
}

async function complete(ticketId: string, generation = 1) {
  await expect
    .poll(
      () =>
        queryFixtureSql(`SELECT status FROM agent_processing_generation
    WHERE ticket_id = '${ticketId}' AND generation_number = ${generation};`),
      { timeout: 120_000 },
    )
    .toBe("COMPLETED");
}

async function verifyLogistics(page: Page, ticketId: string, pending: boolean) {
  const response = await page.request.get(`/api/customer/v2/tickets/${ticketId}`);
  expect(response.ok()).toBe(true);
  const snapshot = (await response.json()) as {
    pendingCompensation: { status: string } | null;
    messages: { author: string; body: string }[];
  };
  if (pending) expect(snapshot.pendingCompensation?.status).toBe("PENDING_REVIEW");
  else expect(snapshot.pendingCompensation).toBeNull();
  expect(snapshot.messages.some(({ author, body }) => author === "AGENT" && body.length > 0)).toBe(
    true,
  );
  expect(
    queryFixtureSql(
      `SELECT count(*) FROM compensation_proposal_revision WHERE ticket_id = '${ticketId}';`,
    ),
  ).toBe(pending ? "1" : "0");
  await page.goto(`/help?ticket=${ticketId}`);
  if (pending)
    await expect(
      page
        .locator(".pending-compensation-card")
        .getByRole("heading", { name: "待审批", exact: true }),
    ).toBeVisible();
  await expect(page.getByRole("log")).toBeVisible();
}

async function verifyPayment(page: Page, ticketId: string, refunded: boolean) {
  const response = await page.request.get(`/api/customer/v2/tickets/${ticketId}`);
  expect(response.ok()).toBe(true);
  const snapshot = (await response.json()) as {
    ticket: { handlingMode: string };
    pendingCompensation: unknown;
    messages: { author: string; body: string }[];
  };
  expect(snapshot.ticket.handlingMode).toBe("HUMAN");
  expect(snapshot.pendingCompensation).toBeNull();
  const replies = snapshot.messages.filter(({ author }) => author === "AGENT");
  expect(replies).toHaveLength(1);
  expect(replies[0].body).toMatch(/支付|付款|已付/);
  expect(replies[0].body).toMatch(
    refunded
      ? /已(?:完成)?(?:全额|全部)退款|全额退款状态为已完成/
      : /未(?:完成)?(?:全额|全部)退款|全额退款状态为未完成/,
  );
  expect(replies[0].body).toMatch(/无法|不能|不足以确认|尚未确认|尚未.*核实|待.*核实/);
  expect(replies[0].body).toMatch(/人工|客服/);
  expect(replies[0].body).not.toMatch(/已查明.*原因|已确认.*重复扣款|已为您退款|已为你退款/);
  expect(
    queryFixtureSql(
      `SELECT human_handoff_reason_code FROM support_ticket WHERE id = '${ticketId}';`,
    ),
  ).toBe("DUPLICATE_CHARGE");
  expect(
    queryFixtureSql(
      `SELECT count(*) FROM compensation_proposal_revision WHERE ticket_id = '${ticketId}';`,
    ),
  ).toBe("0");
  expect(
    queryFixtureSql(`SELECT count(*) FROM investigation_fact f JOIN agent_processing_generation g ON g.id = f.generation_id
    WHERE g.ticket_id = '${ticketId}' AND fact_type IN ('LOGISTICS_DELAY_HOURS', 'LOGISTICS_DELAY_SECONDS', 'POLICY');`),
  ).toBe("0");
  await page.goto(`/help?ticket=${ticketId}`);
  await expect(page.getByText("人工客服处理中", { exact: true })).toBeVisible();
  await expect(page.getByRole("log").getByText(replies[0].body, { exact: true })).toBeVisible();
}

async function fenceDuringRealDelta(
  page: Page,
  ticketId: string,
  sample: number,
  evidence: Record<string, unknown>,
) {
  const message = [
    "补充：今天物流页面仍未更新，请结合这条消息继续核查。",
    "补充：刚刚再次查看物流仍没有进展，请在本工单继续说明。",
  ][sample - 1];
  await page.getByPlaceholder("继续补充消息", { exact: true }).fill(message);
  let observed = { status: "", deltaCount: 0, lastSequence: 0 };
  await expect
    .poll(
      () => {
        observed = JSON.parse(
          queryFixtureSql(`SELECT json_build_object('status', g.status,
      'deltaCount', (SELECT count(*) FROM customer_public_event e WHERE e.ticket_id = g.ticket_id
        AND e.agent_generation = 1 AND e.event_type = 'AGENT_REPLY_CONTENT_DELTA' AND length(e.payload->>'delta') > 0),
      'lastSequence', (SELECT coalesce(max(sequence), 0) FROM customer_public_event e WHERE e.ticket_id = g.ticket_id))
      FROM agent_processing_generation g WHERE ticket_id = '${ticketId}' AND generation_number = 1;`),
        ) as typeof observed;
        evidence.fence = { observed, message };
        // 错过真实流窗口即失败；不重新启动代次直到碰到成功。
        expect(observed.status, "真实首代次已结束，未取得追加消息窗口").toBe("ACTIVE");
        return observed.deltaCount;
      },
      { timeout: 120_000, intervals: [50] },
    )
    .toBeGreaterThan(0);
  const acceptance = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/customer/v2/tickets/${ticketId}/messages`,
  );
  await page.getByRole("button", { name: "发送新消息", exact: true }).click();
  const response = await acceptance;
  expect(response.status()).toBe(202);
  expect(await response.json()).toMatchObject({
    schema: "public-conversation-v2",
    ticketId,
    accepted: true,
    replayed: false,
  });
  expect(
    queryFixtureSql(
      `SELECT status FROM agent_processing_generation WHERE ticket_id = '${ticketId}' AND generation_number = 1;`,
    ),
  ).toBe("SUPERSEDED");
  await complete(ticketId, 2);
  expect(
    queryFixtureSql(
      `SELECT count(*) FROM agent_processing_generation WHERE ticket_id = '${ticketId}';`,
    ),
  ).toBe("2");
  expect(
    queryFixtureSql(
      `SELECT count(*) FROM customer_public_event WHERE ticket_id = '${ticketId}' AND agent_generation = 1 AND event_type = 'AGENT_PROCESSING_TERMINATED';`,
    ),
  ).toBe("1");
  expect(
    queryFixtureSql(`SELECT count(*) FROM customer_public_event WHERE ticket_id = '${ticketId}' AND agent_generation = 1
    AND event_type IN ('AGENT_REPLY_CONTENT_DELTA', 'PUBLIC_MESSAGE_APPENDED') AND sequence >
      (SELECT sequence FROM customer_public_event WHERE ticket_id = '${ticketId}' AND agent_generation = 1 AND event_type = 'AGENT_PROCESSING_TERMINATED');`),
  ).toBe("0");
  expect(
    queryFixtureSql(
      `SELECT count(*) FROM compensation_proposal_revision p JOIN agent_processing_generation g ON g.id = p.generation_id WHERE g.ticket_id = '${ticketId}' AND g.generation_number = 1;`,
    ),
  ).toBe("0");
  expect(
    queryFixtureSql(
      `SELECT count(*) FROM public_message WHERE ticket_id = '${ticketId}' AND author = 'CUSTOMER' AND body = '${message}';`,
    ),
  ).toBe("1");
  await page.reload();
  await expect(page.getByRole("log").getByText(message, { exact: true })).toBeVisible();
  return { observed, message, supersededGeneration: 1, completedGeneration: 2 };
}

for (const caseName of cases.filter((value) => !selectedCase || value === selectedCase)) {
  for (const sample of [1, 2].filter(
    (value) => !selectedSample || String(value) === selectedSample,
  )) {
    test(`Issue #230 core ${caseName} sample ${sample}`, async ({ browser }, testInfo) => {
      test.setTimeout(300_000);
      const { reference, refunded } = prepare(caseName, sample);
      const context = await newAcceptanceContext(browser);
      const evidence: Record<string, unknown> = { caseName, sample, reference };
      try {
        const page = await context.newPage();
        await login(page, "customer", "customer-demo");
        if (caseName === "payment_handoff" || caseName === "split_recovery") {
          const intake = await createPaymentIntake(page, reference, caseName === "split_recovery");
          Object.assign(evidence, intake);
          for (const id of intake.ticketIds) await complete(id);
          const tickets = JSON.parse(
            queryFixtureSql(
              `SELECT json_agg(json_build_object('id', id, 'kind', issue_kind)) FROM support_ticket WHERE id IN (${intake.ticketIds.map((id) => `'${id}'`).join(",")});`,
            ),
          ) as { id: string; kind: string }[];
          for (const ticket of tickets) {
            if (ticket.kind === "DUPLICATE_CHARGE") await verifyPayment(page, ticket.id, refunded);
            else await verifyLogistics(page, ticket.id, true);
          }
          if (caseName === "split_recovery") {
            expect(
              queryFixtureSql(
                `SELECT count(*) FROM shared_intake_issue WHERE shared_intake_record_id = '${intake.sharedIntakeRecordId}';`,
              ),
            ).toBe("2");
            await page.goto("/help");
            await page.reload();
            const overview = page.getByRole("region", { name: "订单工单总览" });
            await expect(
              overview.getByRole("heading", { name: `订单 ${reference}` }),
            ).toBeVisible();
            for (const ticket of tickets)
              await expect(
                overview.getByRole("button", { name: `打开工单 ${ticket.id}`, exact: true }),
              ).toBeVisible();
          }
        } else {
          const ticketId = await createSingleTicket(
            page,
            reference,
            "物流延迟，请核实订单后说明处理方案。",
          );
          evidence.ticketId = ticketId;
          if (caseName === "generation_fence")
            evidence.fence = await fenceDuringRealDelta(page, ticketId, sample, evidence);
          else await complete(ticketId);
          await verifyLogistics(page, ticketId, caseName !== "no_compensation");
        }
      } finally {
        await testInfo.attach("core-matrix-case", {
          body: JSON.stringify(evidence),
          contentType: "application/json",
        });
        await context.close();
      }
    });
  }
}
