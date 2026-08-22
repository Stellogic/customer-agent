import { expect, test, type Page } from "@playwright/test";
import { login as loginForAudience } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";
const derivedRevisionId = "80000000-0000-0000-0000-000000000008";

async function login(page: Page, username: string) {
  await loginForAudience(page, "internal", username);
}

async function csrf(page: Page) {
  return page.evaluate(async () => {
    return (await (await fetch("/api/auth/csrf", { credentials: "same-origin" })).json()) as {
      token: string;
      headerName: string;
    };
  });
}

test("双角色不能审批本人参与的派生版本，独立审批人的旧租约被围栏", async ({ browser }) => {
  const dualContext = await newIssue80Context(browser);
  const dual = await dualContext.newPage();
  await login(dual, "internal-demo");
  await expect(dual.getByRole("link", { name: "客服工作区", exact: true })).toBeVisible();
  await expect(dual.getByRole("link", { name: "审批工作区", exact: true })).toBeVisible();

  const dualQueue = await dual.evaluate(async () => {
    const response = await fetch("/api/approver/compensation-proposals", {
      credentials: "same-origin",
      headers: { "X-Synthetic-Approver-Id": "approver-demo" },
    });
    return { status: response.status, body: await response.text() };
  });
  expect(dualQueue.status).toBe(200);
  expect(dualQueue.body).not.toContain(derivedRevisionId);

  const dualCsrf = await csrf(dual);
  const directStatuses = await dual.evaluate(
    async ({ csrfToken, revisionId }) => {
      const commonHeaders = {
        [csrfToken.headerName]: csrfToken.token,
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
        "X-Synthetic-Approver-Id": "approver-demo",
      };
      const claim = await fetch(`/api/approver/compensation-proposals/${revisionId}/claims`, {
        method: "POST",
        credentials: "same-origin",
        headers: commonHeaders,
        body: JSON.stringify({ requestedLeaseSeconds: 900 }),
      });
      const approve = await fetch(`/api/approver/compensation-proposals/${revisionId}/approve`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          ...commonHeaders,
          "X-Approval-Lease-Token": crypto.randomUUID(),
          "X-Approval-Lease-Version": "1",
        },
        body: JSON.stringify({
          proposalRevision: 2,
          contentDigest: "b".repeat(64),
          internalNote: "不应允许本人决定",
        }),
      });
      return [claim.status, approve.status];
    },
    { csrfToken: dualCsrf, revisionId: derivedRevisionId },
  );
  expect(directStatuses).toEqual([404, 404]);
  await dualContext.close();

  const approverContext = await newIssue80Context(browser);
  const approver = await approverContext.newPage();
  await login(approver, "approver-demo");
  await expect(approver).toHaveURL(/\/internal\/approvals$/);
  await expect(approver.getByRole("status")).toHaveText("待审批队列已刷新");

  const queue = await approver.evaluate(async () => {
    return (await (
      await fetch("/api/approver/compensation-proposals", {
        credentials: "same-origin",
        cache: "no-store",
      })
    ).json()) as Array<{ proposalRevisionId: string }>;
  });
  const derivedQueueIndex = queue.findIndex(
    (item) => item.proposalRevisionId === derivedRevisionId,
  );
  expect(derivedQueueIndex).toBeGreaterThanOrEqual(0);

  const claimResponse = approver.waitForResponse((response) =>
    response.url().endsWith(`/${derivedRevisionId}/claims`),
  );
  await approver
    .locator(".queue-list > li")
    .nth(derivedQueueIndex)
    .getByRole("button", { name: "领取审批" })
    .click();
  const actualClaimResponse = await claimResponse;
  const actualClaimBody = await actualClaimResponse.text();
  expect(actualClaimResponse.status(), actualClaimBody).toBe(201);
  const lease = JSON.parse(actualClaimBody) as {
    leaseToken: string;
    leaseVersion: number;
  };
  await expect(approver.getByRole("heading", { name: "ORDER-DELAY-001" })).toBeVisible();
  await expect(approver.getByText("order:ORDER-DELAY-001")).toBeVisible();
  await approver.getByRole("button", { name: "释放审批" }).click();
  await expect(approver.getByText("审批责任已释放，已返回队列。")).toBeVisible();

  const oldLeaseStatus = await approver.evaluate(
    async ({ leaseToken, leaseVersion, revisionId }) => {
      return (
        await fetch(`/api/approver/compensation-proposals/${revisionId}/approval-view`, {
          credentials: "same-origin",
          headers: {
            "X-Approval-Lease-Token": leaseToken,
            "X-Approval-Lease-Version": String(leaseVersion),
          },
        })
      ).status;
    },
    { ...lease, revisionId: derivedRevisionId },
  );
  expect(oldLeaseStatus).toBe(409);
  await approverContext.close();
});
