import { expect, test, type Page } from "@playwright/test";
import { login } from "./support/auth";
import { executeFixtureSql } from "./support/database";

const assignmentTicketId = "80000000-0000-0000-0000-000000000009";
const revisionId = "80000000-0000-0000-0000-000000000008";

async function claimApproval(page: Page) {
  const queue = await page.evaluate(async () => {
    return (await (
      await fetch("/api/approver/compensation-proposals", {
        credentials: "same-origin",
        cache: "no-store",
      })
    ).json()) as Array<{ proposalRevisionId: string }>;
  });
  const index = queue.findIndex((item) => item.proposalRevisionId === revisionId);
  expect(index).toBeGreaterThanOrEqual(0);
  const streamOpened = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/${revisionId}/approval-view/events`) && response.status() === 200,
  );
  await page
    .locator(".queue-list > li")
    .nth(index)
    .getByRole("button", { name: "领取审批" })
    .click();
  await expect(page.getByRole("heading", { name: "ORDER-DELAY-001" })).toBeVisible();
  await streamOpened;
}

function resetApprovalFixture() {
  executeFixtureSql(`
    DELETE FROM approval_release_request WHERE proposal_revision_id = '${revisionId}';
    DELETE FROM approval_claim_request WHERE proposal_revision_id = '${revisionId}';
    DELETE FROM approval_view_event WHERE proposal_revision_id = '${revisionId}';
    DELETE FROM audit_event
      WHERE subject_type = 'COMPENSATION_PROPOSAL_REVISION'
        AND subject_id = '${revisionId}'
        AND event_type LIKE 'APPROVAL_LEASE_%';
    DELETE FROM approval_lease WHERE proposal_revision_id = '${revisionId}';
    UPDATE compensation_proposal_revision
      SET status = 'PENDING_APPROVAL'
      WHERE id = '${revisionId}';
  `);
}

test("客服 assignment 撤销后 60 秒内断流、移除旧详情并重读权威资源", async ({ page }) => {
  await login(page, "internal", "support-demo");
  await expect(
    page.getByRole("button", { name: `领取工单 ${assignmentTicketId}` }).first(),
  ).toBeVisible();
  const streamOpened = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/tickets/${assignmentTicketId}/events`) && response.status() === 200,
  );
  await page
    .getByRole("button", { name: `领取工单 ${assignmentTicketId}` })
    .first()
    .click();
  await expect(page.getByRole("heading", { name: "当前工单详情" })).toBeVisible();
  await streamOpened;

  const revokedAt = Date.now();
  executeFixtureSql(`
    UPDATE support_assignment
      SET status = 'REVOKED', revoked_at = clock_timestamp()
      WHERE ticket_id = '${assignmentTicketId}' AND status = 'ACTIVE';
  `);

  await expect(page.getByRole("alert")).toContainText("客服分配已失效", { timeout: 60_000 });
  expect(Date.now() - revokedAt).toBeLessThan(60_000);
  await expect(page.getByRole("heading", { name: "当前工单详情" })).toHaveCount(0);
  const authorityStatus = await page.evaluate(async (ticketId) => {
    return (
      await fetch(`/api/support/workbench/tickets/${ticketId}`, {
        credentials: "same-origin",
        cache: "no-store",
      })
    ).status;
  }, assignmentTicketId);
  expect(authorityStatus).toBe(404);
});

test("审批 lease 撤销后 60 秒内断流并以权威队列恢复", async ({ page }) => {
  resetApprovalFixture();
  await login(page, "internal", "approver-demo");
  await claimApproval(page);

  const revokedAt = Date.now();
  executeFixtureSql(`
    UPDATE approval_lease SET status = 'REVOKED'
      WHERE proposal_revision_id = '${revisionId}' AND status = 'ACTIVE';
  `);

  await expect(page.getByRole("status")).toContainText("待审批队列已刷新", { timeout: 60_000 });
  expect(Date.now() - revokedAt).toBeLessThan(60_000);
  await expect(page.getByRole("heading", { name: "ORDER-DELAY-001" })).toHaveCount(0);
  const queueContainsReleasedRevision = await page.evaluate(async (releasedRevisionId) => {
    const queue = (await (
      await fetch("/api/approver/compensation-proposals", {
        credentials: "same-origin",
        cache: "no-store",
      })
    ).json()) as Array<{ proposalRevisionId: string }>;
    return queue.some((item) => item.proposalRevisionId === releasedRevisionId);
  }, revisionId);
  expect(queueContainsReleasedRevision).toBe(true);
});

test("提案版本失效后 60 秒内断流并拒绝旧租约权威视图", async ({ page }) => {
  resetApprovalFixture();
  await login(page, "internal", "approver-demo");
  await claimApproval(page);

  const supersededAt = Date.now();
  executeFixtureSql(`
    UPDATE compensation_proposal_revision SET status = 'SUPERSEDED'
      WHERE id = '${revisionId}';
  `);

  await expect(page.getByRole("status")).toContainText("待审批队列已刷新", { timeout: 60_000 });
  expect(Date.now() - supersededAt).toBeLessThan(60_000);
  await expect(page.getByRole("heading", { name: "ORDER-DELAY-001" })).toHaveCount(0);
  const queueContainsOldRevision = await page.evaluate(async (oldRevisionId) => {
    const queue = (await (
      await fetch("/api/approver/compensation-proposals", {
        credentials: "same-origin",
        cache: "no-store",
      })
    ).json()) as Array<{ proposalRevisionId: string }>;
    return queue.some((item) => item.proposalRevisionId === oldRevisionId);
  }, revisionId);
  expect(queueContainsOldRevision).toBe(false);
});
