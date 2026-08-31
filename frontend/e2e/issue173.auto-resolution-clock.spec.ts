import { readFileSync, writeFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { queryFixtureSql } from "./support/database";
import { createSingleTicket, prepareOrder } from "./support/issue173-intake";

declare const process: { env: Record<string, string | undefined> };

// 仅外层脚本推进 Spring 时钟；浏览器不快进、不写生命周期、不预造 Agent 结果。
const phases = ["prepare", "before-due", "resolved", "resolved-restart", "before-close", "closed"];
const phase = process.env.ISSUE173_CLOCK_PHASE ?? "";
const start = "2026-08-09T14:00:00.000Z";
const due = "2026-08-09T14:05:00.000Z";
const closeDue = "2026-08-12T14:05:00.000Z";
const statePath = "/artifacts/issue173-clock.json";

type ClockTicket = { reference: string; ticketId: string; generation: number; dueAt: string };
type ClockState = { completedPhase: string; tickets: [ClockTicket, ClockTicket] };
type Snapshot = {
  ticket: { id: string; lifecycleState: string; agentGeneration: number };
  autoResolution: { status: string; dueAt: string | null } | null;
};
type StoredTicket = {
  lifecycle: string;
  candidate: string;
  createdAt: string;
  dueAt: string;
  resolvedAt: string | null;
  closeDueAt: string | null;
  closedAt: string | null;
  resolutions: number;
  autoResolutions: number;
  reopens: number;
  closures: number;
  cancellations: number;
};

function storedTicket(ticketId: string): StoredTicket {
  return JSON.parse(
    queryFixtureSql(`
    SELECT json_build_object(
      'lifecycle', t.lifecycle_state, 'candidate', a.status,
      'createdAt', a.created_at, 'dueAt', a.due_at,
      'resolvedAt', t.resolved_at, 'closeDueAt', t.close_due_at, 'closedAt', t.closed_at,
      'resolutions', (SELECT count(*) FROM customer_public_event WHERE ticket_id = t.id AND event_type = 'TICKET_RESOLVED'),
      'autoResolutions', (SELECT count(*) FROM audit_event WHERE ticket_id = t.id AND event_type = 'AUTO_RESOLUTION_RESOLVED'),
      'reopens', (SELECT count(*) FROM customer_public_event WHERE ticket_id = t.id AND event_type = 'TICKET_REOPENED'),
      'closures', (SELECT count(*) FROM customer_public_event WHERE ticket_id = t.id AND event_type = 'TICKET_CLOSED'),
      'cancellations', (SELECT count(*) FROM customer_public_event WHERE ticket_id = t.id
        AND event_type = 'AUTO_RESOLUTION_CHANGED' AND payload->'autoResolution'->>'status' = 'CANCELLED')
    ) FROM support_ticket t JOIN ticket_auto_resolution a ON a.ticket_id = t.id
    WHERE t.id = '${ticketId}';
  `),
  ) as StoredTicket;
}

async function openTicket(page: Page, ticketId: string): Promise<Snapshot> {
  const loaded = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      new URL(response.url()).pathname === `/api/customer/v2/tickets/${ticketId}`,
  );
  await page.goto(`/help?ticket=${ticketId}`);
  const response = await loaded;
  expect(response.status()).toBe(200);
  const snapshot = (await response.json()) as Snapshot;
  expect(snapshot.ticket.id).toBe(ticketId);
  await expect(
    page.getByRole("heading", {
      name: `${ticketId.slice(0, 8)}…${ticketId.slice(-4)}`,
      exact: true,
    }),
  ).toBeVisible();
  return snapshot;
}

async function expectResolved(page: Page, ticket: ClockTicket) {
  await expect
    .poll(() => storedTicket(ticket.ticketId).lifecycle, { timeout: 30_000 })
    .toBe("RESOLVED");
  const snapshot = await openTicket(page, ticket.ticketId);
  expect(snapshot.ticket.lifecycleState).toBe("RESOLVED");
  expect(snapshot.autoResolution).toEqual({ status: "RESOLVED", dueAt: null });
  await expect(
    page.getByRole("region", { name: "自动解决状态" }).getByText("工单已自动解决", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "发送回复", exact: true })).toBeVisible();
  const stored = storedTicket(ticket.ticketId);
  expect(stored).toMatchObject({
    candidate: "RESOLVED",
    resolutions: 1,
    autoResolutions: 1,
    reopens: 0,
    closures: 0,
  });
  expect(Date.parse(stored.dueAt)).toBe(Date.parse(ticket.dueAt));
  expect(Date.parse(stored.resolvedAt!)).toBe(Date.parse(due));
  expect(Date.parse(stored.closeDueAt!)).toBe(Date.parse(closeDue));
}

async function replyThroughUi(
  page: Page,
  ticket: ClockTicket,
  message: string,
  expectedStatus: number,
) {
  await page.getByLabel("回复订单编号").fill(ticket.reference);
  await page.getByLabel("回复问题类型").selectOption("LOGISTICS_DELAY");
  await page.getByLabel("工单回复", { exact: true }).fill(message);
  const replied = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/customer/tickets/${ticket.ticketId}/replies`,
  );
  await page.getByRole("button", { name: "发送回复", exact: true }).click();
  const response = await replied;
  expect(response.status()).toBe(expectedStatus);
  return (await response.json()) as { ticketId: string; outcome: string; replayed: boolean };
}

test(`Issue #173 F：真实自动解决与72小时回复边界 / ${phase}`, async ({ browser }) => {
  test.setTimeout(180_000);
  // 缺少编排或未知阶段直接失败，不用 skip/条件假通过掩盖未执行的链路。
  expect(phases).toContain(phase);
  const context = await newAcceptanceContext(browser);
  try {
    const page = await context.newPage();
    // 每阶段都是后端重建后的新 Session，不重用已失效的 storageState。
    await login(page, "customer", "customer-demo");
    let state: ClockState;
    if (phase === "prepare") {
      const tickets: ClockTicket[] = [];
      for (let sample = 0; sample < 2; sample += 1) {
        const reference = prepareOrder({ delayHours: 23 });
        await page.goto("/help");
        const ticketId = await createSingleTicket(page, reference, "请解释物流状态");
        await expect(page.getByRole("button", { name: "仍需帮助，取消自动解决" })).toBeVisible({
          timeout: 60_000,
        });
        const snapshot = await openTicket(page, ticketId);
        expect(snapshot.ticket.lifecycleState).toBe("INVESTIGATING");
        expect(snapshot.autoResolution?.status).toBe("PENDING");
        const dueAt = snapshot.autoResolution!.dueAt!;
        expect(Date.parse(dueAt)).toBe(Date.parse(due));
        const stored = storedTicket(ticketId);
        expect(Date.parse(stored.createdAt)).toBe(Date.parse(start));
        expect(Date.parse(stored.dueAt) - Date.parse(stored.createdAt)).toBe(300_000);
        expect(stored).toMatchObject({ resolutions: 0, autoResolutions: 0, closures: 0 });
        tickets.push({ reference, ticketId, generation: snapshot.ticket.agentGeneration, dueAt });
      }
      expect(tickets[0].ticketId).not.toBe(tickets[1].ticketId);
      state = { completedPhase: phase, tickets: [tickets[0], tickets[1]] };
    } else {
      state = JSON.parse(readFileSync(statePath, "utf8")) as ClockState;
      expect(state.completedPhase).toBe(phases[phases.indexOf(phase) - 1]);
      if (phase === "before-due") {
        for (const ticket of state.tickets) {
          const snapshot = await openTicket(page, ticket.ticketId);
          expect(snapshot.ticket.lifecycleState).toBe("INVESTIGATING");
          expect(snapshot.autoResolution?.status).toBe("PENDING");
          expect(Date.parse(snapshot.autoResolution!.dueAt!)).toBe(Date.parse(ticket.dueAt));
          await expect(page.getByRole("button", { name: "仍需帮助，取消自动解决" })).toBeVisible();
          expect(storedTicket(ticket.ticketId)).toMatchObject({
            lifecycle: "INVESTIGATING",
            candidate: "PENDING",
            resolutions: 0,
            autoResolutions: 0,
          });
        }
      } else if (["resolved", "resolved-restart", "before-close"].includes(phase)) {
        for (const ticket of state.tickets) await expectResolved(page, ticket);
        if (phase === "before-close") {
          const ticket = state.tickets[0];
          await openTicket(page, ticket.ticketId);
          const message = `仍需帮助，请人工继续核实本物流问题。${ticket.reference}`;
          const result = await replyThroughUi(page, ticket, message, 200);
          expect(result).toMatchObject({
            ticketId: ticket.ticketId,
            outcome: "REOPENED",
            replayed: false,
          });
          await expect(page.getByText(message, { exact: true })).toBeVisible();
          await expect(page.getByRole("region", { name: "自动解决状态" })).toHaveCount(0);
          const reopened = await openTicket(page, ticket.ticketId);
          expect(reopened.ticket.lifecycleState).toBe("INVESTIGATING");
          expect(reopened.ticket.agentGeneration).toBeGreaterThan(ticket.generation);
          expect(reopened.autoResolution).toBeNull();
          await expect(page.getByText(message, { exact: true })).toBeVisible();
          await expect(page.getByRole("region", { name: "自动解决状态" })).toHaveCount(0);
          expect(storedTicket(ticket.ticketId)).toMatchObject({
            lifecycle: "INVESTIGATING",
            candidate: "RESOLVED",
            resolvedAt: null,
            closeDueAt: null,
            resolutions: 1,
            autoResolutions: 1,
            reopens: 1,
            closures: 0,
            cancellations: 0,
          });
        }
      } else if (phase === "closed") {
        const [reopened, closing] = state.tickets;
        await expect
          .poll(() => storedTicket(closing.ticketId).lifecycle, { timeout: 30_000 })
          .toBe("CLOSED");
        const snapshot = await openTicket(page, closing.ticketId);
        expect(snapshot.ticket.lifecycleState).toBe("CLOSED");
        const stored = storedTicket(closing.ticketId);
        expect(stored).toMatchObject({
          candidate: "RESOLVED",
          resolutions: 1,
          autoResolutions: 1,
          reopens: 0,
          closures: 1,
        });
        expect(Date.parse(stored.closedAt!)).toBe(Date.parse(closeDue));
        const result = await replyThroughUi(
          page,
          closing,
          "仍需帮助，请人工继续处理原物流问题。",
          201,
        );
        expect(result).toMatchObject({ outcome: "LINKED_TICKET_CREATED", replayed: false });
        expect(result.ticketId).toMatch(/^[0-9a-f-]{36}$/i);
        expect(result.ticketId).not.toBe(closing.ticketId);
        await expect(
          page.getByRole("heading", {
            name: `${result.ticketId.slice(0, 8)}…${result.ticketId.slice(-4)}`,
            exact: true,
          }),
        ).toBeVisible();
        expect(
          queryFixtureSql(`
          SELECT follow_up_of::text FROM support_ticket WHERE id = '${result.ticketId}';
        `),
        ).toBe(closing.ticketId);
        const original = await openTicket(page, reopened.ticketId);
        expect(original.ticket.lifecycleState).toBe("INVESTIGATING");
        expect(original.autoResolution).toBeNull();
        expect(storedTicket(reopened.ticketId)).toMatchObject({ reopens: 1, closures: 0 });
        expect(storedTicket(closing.ticketId)).toMatchObject({
          lifecycle: "CLOSED",
          closures: 1,
          reopens: 0,
        });
      }
      state.completedPhase = phase;
    }
    // 同一隔离 project 的现有 artifacts 卷交接；前一阶段断言全部成功后才推进标记。
    writeFileSync(statePath, JSON.stringify(state, null, 2));
    writeFileSync(
      `/artifacts/issue173-clock-${phase}.json`,
      JSON.stringify(
        {
          phase,
          tickets: state.tickets.map((ticket) => ({
            ...ticket,
            stored: storedTicket(ticket.ticketId),
          })),
        },
        null,
        2,
      ),
    );
    await page.screenshot({ path: `/artifacts/issue173-clock-${phase}.png`, fullPage: true });
  } finally {
    await context.close();
  }
});
