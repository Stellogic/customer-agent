import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApprovalWorkbench } from "./ApprovalWorkbench";

const REVISION_ID = "27000000-0000-0000-0000-000000000001";
const LEASE_TOKEN = "27000000-0000-0000-0000-000000000002";

describe("审批视图授权撤销", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it("连接期间租约被撤销后立即清除审批证据和操作并返回队列", async () => {
    let revoke: ((response: Response) => void) | undefined;
    globalThis.history.replaceState(null, "", `/approver?revision=${REVISION_ID}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(Response.json([{ proposalRevisionId: REVISION_ID, compensationMethod: "COUPON", amount: 20, submittedAt: "2026-08-11T03:00:00Z", expiresAt: "2026-08-12T03:00:00Z" }]))
      .mockResolvedValueOnce(Response.json({ proposalRevisionId: REVISION_ID, leaseToken: LEASE_TOKEN, leaseVersion: 1, expiresAt: "2026-08-11T03:15:00Z", replayed: false }, { status: 201 }))
      .mockResolvedValueOnce(Response.json(approvalSnapshot()))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { revoke = resolve; }));

    render(<ApprovalWorkbench approverId="approver-demo" />);

    fireEvent.click(await screen.findByRole("button", { name: "领取审批" }));
    expect(await screen.findByText("order:ORDER-DELAY-001")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "批准补偿" })).toBeInTheDocument();
    revoke?.(new Response(null, { status: 403 }));
    expect(await screen.findByRole("heading", { level: 1, name: "待审批补偿" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("order:ORDER-DELAY-001")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "批准补偿" })).not.toBeInTheDocument();
    expect(globalThis.location.search).toBe("");
  });

  it("旧序号、缺口和非法 payload 不能恢复或扩大审批访问", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(Response.json([]));

    render(<ApprovalWorkbench approverId="approver-demo" />);

    expect(await screen.findByRole("heading", { level: 1, name: "待审批补偿" })).toBeInTheDocument();
    expect(screen.queryByText(/执行|重试|对账|撤销补偿/)).not.toBeInTheDocument();
  });
});

function approvalSnapshot() {
  return {
    view: "APPROVAL_VIEW",
    schema: "approval-view-v1",
    cursor: "approval-view-v1:1",
    proposalRevisionId: REVISION_ID,
    proposalRevision: 1,
    contentDigest: "0".repeat(64),
    orderReference: "ORDER-DELAY-001",
    reasonCode: "LOGISTICS_DELAY",
    delayHours: 80,
    delaySeconds: 288000,
    compensationMethod: "COUPON",
    proposedAmount: 20,
    authoritativeAmount: 20,
    policyVersion: "delay-policy-v1",
    policyTier: "OVER_72_HOURS",
    eligibilityChecks: ["ORDER_PAID"],
    evidenceReferences: ["order:ORDER-DELAY-001"],
    evidenceSnapshot: { paidAmount: "268.00" },
    responsibilityChain: [],
    leaseToken: LEASE_TOKEN,
    leaseVersion: 1,
    leaseExpiresAt: "2026-08-11T03:15:00Z",
    submittedAt: "2026-08-11T03:00:00Z",
    proposalExpiresAt: "2026-08-12T03:00:00Z",
  };
}
