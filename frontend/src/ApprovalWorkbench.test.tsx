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
    let closeStream: (() => void) | undefined;
    globalThis.history.replaceState(null, "", `/internal/approvals?revision=${REVISION_ID}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        Response.json([
          {
            proposalRevisionId: REVISION_ID,
            compensationMethod: "COUPON",
            amount: 20,
            submittedAt: "2026-08-11T03:00:00Z",
            expiresAt: "2026-08-12T03:00:00Z",
          },
        ]),
      )
      .mockResolvedValueOnce(
        Response.json(
          {
            proposalRevisionId: REVISION_ID,
            leaseToken: LEASE_TOKEN,
            leaseVersion: 1,
            expiresAt: "2026-08-11T03:15:00Z",
            replayed: false,
          },
          { status: 201 },
        ),
      )
      .mockResolvedValueOnce(Response.json(approvalSnapshot()))
      .mockImplementationOnce(
        async () =>
          new Response(
            new ReadableStream({
              start(controller) {
                closeStream = () => controller.close();
              },
            }),
            { status: 200, headers: { "Content-Type": "text/event-stream" } },
          ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 403 }));

    render(<ApprovalWorkbench approverId="approver-demo" />);

    fireEvent.click(await screen.findByRole("button", { name: "领取审批" }));
    expect(await screen.findByText("order:ORDER-DELAY-001")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "批准补偿" })).toBeInTheDocument();
    closeStream?.();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "批准补偿" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByText("order:ORDER-DELAY-001")).not.toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { level: 1, name: "待审批补偿" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("order:ORDER-DELAY-001")).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "批准补偿" })).not.toBeInTheDocument();
    expect(globalThis.location.search).toBe("");
  });

  it("瞬时断线使用同一租约和游标重新读取权威快照而不暴露额外能力", async () => {
    let closeStream: (() => void) | undefined;
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        Response.json([
          {
            proposalRevisionId: REVISION_ID,
            compensationMethod: "COUPON",
            amount: 20,
            submittedAt: "2026-08-11T03:00:00Z",
            expiresAt: "2026-08-12T03:00:00Z",
          },
        ]),
      )
      .mockResolvedValueOnce(
        Response.json(
          {
            proposalRevisionId: REVISION_ID,
            leaseToken: LEASE_TOKEN,
            leaseVersion: 1,
            expiresAt: "2026-08-11T03:15:00Z",
            replayed: false,
          },
          { status: 201 },
        ),
      )
      .mockResolvedValueOnce(Response.json(approvalSnapshot()))
      .mockImplementationOnce(
        async () =>
          new Response(
            new ReadableStream({
              start(controller) {
                closeStream = () => controller.close();
              },
            }),
            { status: 200, headers: { "Content-Type": "text/event-stream" } },
          ),
      )
      .mockResolvedValueOnce(Response.json({ ...approvalSnapshot(), cursor: "approval-view-v1:2" }))
      .mockResolvedValueOnce(openStream());

    render(<ApprovalWorkbench approverId="approver-demo" />);

    fireEvent.click(await screen.findByRole("button", { name: "领取审批" }));
    expect(await screen.findByText("order:ORDER-DELAY-001")).toBeInTheDocument();
    closeStream?.();
    expect(
      await screen.findByText("审批连接已断开；正在按当前租约重新校验权威快照…"),
    ).toBeInTheDocument();
    expect(screen.queryByText("order:ORDER-DELAY-001")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.filter(([input]) => String(input).endsWith("/approval-view")),
      ).toHaveLength(2),
    );
    expect(screen.getByText("order:ORDER-DELAY-001")).toBeInTheDocument();
    const reconnect = vi.mocked(globalThis.fetch).mock.calls.at(-1)?.[1];
    expect(new Headers(reconnect?.headers).get("Last-Event-ID")).toBe("approval-view-v1:2");
    expect(screen.queryByText(/执行|重试|对账|撤销补偿/)).not.toBeInTheDocument();
  });

  it("旧页面 URL 不会自动领取新租约", async () => {
    globalThis.history.replaceState(null, "", `/internal/approvals?revision=${REVISION_ID}`);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(Response.json([]));

    render(<ApprovalWorkbench approverId="approver-demo" />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "待审批补偿" }),
    ).toBeInTheDocument();
    expect(globalThis.location.search).toBe("");
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);
  });

  it("旧事件被忽略而序号缺口和非法 payload 触发完整快照重置", async () => {
    const stale = eventBlock("approval-view-v1:1", "APPROVAL_AUTHORITY_STARTED", {
      proposalRevisionId: REVISION_ID,
      leaseVersion: 1,
      authorityState: "ACTIVE",
      rawToolPayload: "forbidden",
    });
    const gap = eventBlock("approval-view-v1:3", "APPROVAL_AUTHORITY_STARTED", {
      proposalRevisionId: REVISION_ID,
      leaseVersion: 1,
      authorityState: "ACTIVE",
    });
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        Response.json([
          {
            proposalRevisionId: REVISION_ID,
            compensationMethod: "COUPON",
            amount: 20,
            submittedAt: "2026-08-11T03:00:00Z",
            expiresAt: "2026-08-12T03:00:00Z",
          },
        ]),
      )
      .mockResolvedValueOnce(
        Response.json(
          {
            proposalRevisionId: REVISION_ID,
            leaseToken: LEASE_TOKEN,
            leaseVersion: 1,
            expiresAt: "2026-08-11T03:15:00Z",
            replayed: false,
          },
          { status: 201 },
        ),
      )
      .mockResolvedValueOnce(Response.json(approvalSnapshot()))
      .mockResolvedValueOnce(sseResponse(stale + gap))
      .mockResolvedValueOnce(Response.json({ ...approvalSnapshot(), cursor: "approval-view-v1:4" }))
      .mockResolvedValueOnce(openStream());

    render(<ApprovalWorkbench approverId="approver-demo" />);
    fireEvent.click(await screen.findByRole("button", { name: "领取审批" }));

    await waitFor(() =>
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.filter(([input]) => String(input).endsWith("/approval-view")),
      ).toHaveLength(2),
    );
    expect(screen.queryByText("forbidden")).not.toBeInTheDocument();
    expect(screen.getByText("order:ORDER-DELAY-001")).toBeInTheDocument();
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

function eventBlock(id: string, type: string, payload: unknown) {
  return `id:${id}\nevent:${type}\ndata:${JSON.stringify({ view: "APPROVAL_VIEW", schema: "approval-view-v1", payload })}\n\n`;
}

function sseResponse(value: string) {
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(value));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

function openStream() {
  return new Response(new ReadableStream(), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}
