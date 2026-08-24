import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql } from "./support/database";

const revisionId = "80000000-0000-0000-0000-000000000008";

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
    UPDATE compensation_proposal_revision SET status = 'PENDING_APPROVAL' WHERE id = '${revisionId}';
  `);
}

test("Issue #100 真实登录、租约内审批视图、决定确认与撤权清屏", async ({ browser }, testInfo) => {
  resetApprovalFixture();
  const context = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 960 } });
  const page = await context.newPage();
  let viewReads = 0;
  page.on("request", (request) => {
    if (request.method() === "GET" && new URL(request.url()).pathname.endsWith("/approval-view"))
      viewReads += 1;
  });

  await login(page, "internal", "approver-demo");
  await expect(page).toHaveURL(/\/internal\/approvals$/);
  const row = page.locator(".approval-table-row", { hasText: "80000000…0008" });
  await expect(row).toBeVisible();
  await expect(page.getByRole("heading", { name: "ORDER-DELAY-001" })).toHaveCount(0);
  expect(viewReads).toBe(0);
  await page.screenshot({
    path: testInfo.outputPath("approval-queue-before-claim.png"),
    fullPage: true,
  });

  await row.getByRole("button", { name: "领取审批" }).click();
  await expect(page.getByRole("heading", { name: "ORDER-DELAY-001" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "权威金额" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "政策信息" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "证据引用" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "责任链" })).toBeVisible();
  await expect(page.getByText(/AI 建议批准|风险评级|PRP-/)).toHaveCount(0);
  expect(viewReads).toBe(1);

  await page.getByRole("button", { name: "批准补偿" }).click();
  await expect(page.getByRole("dialog", { name: "确认批准补偿" })).toBeVisible();
  await page.getByRole("button", { name: "取消" }).click();
  await page.screenshot({
    path: testInfo.outputPath("approval-authorized-detail.png"),
    fullPage: true,
  });

  const revokedAt = Date.now();
  executeFixtureSql(
    `UPDATE approval_lease SET status = 'REVOKED' WHERE proposal_revision_id = '${revisionId}' AND status = 'ACTIVE';`,
  );
  await expect(page.getByRole("heading", { name: "ORDER-DELAY-001" })).toHaveCount(0, {
    timeout: 60_000,
  });
  expect(Date.now() - revokedAt).toBeLessThan(60_000);
  await expect(page.getByRole("button", { name: "批准补偿" })).toHaveCount(0);
  await expect(page.getByText("order:ORDER-DELAY-001", { exact: true })).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("approval-revoked-cleared.png"),
    fullPage: true,
  });
  await context.close();
});
