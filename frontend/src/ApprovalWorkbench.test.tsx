import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApprovalWorkbench } from "./ApprovalWorkbench";

vi.mock("./csrf", () => ({
  loadCsrfToken: async () => ({ token: "approval-csrf", headerName: "X-CSRF-TOKEN" }),
}));

const REVISION_ID = "27000000-0000-0000-0000-000000000001";
const LEASE_TOKEN = "27000000-0000-0000-0000-000000000002";

describe("审批视图授权撤销", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it("状态图形不混入审批队列的权威可见文案", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json([]));

    render(<ApprovalWorkbench />);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/^待审批队列已刷新$/));
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
            expiresAt: "2099-08-11T03:15:00Z",
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
      .mockResolvedValueOnce(new Response(null, { status: 403 }))
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
      );

    render(<ApprovalWorkbench />);

    fireEvent.click(await screen.findByRole("button", { name: "领取审批" }));
    expect(await screen.findByText("order:ORDER-DELAY-001")).toBeInTheDocument();
    const claimRequest = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(([input]) => String(input).endsWith("/claims"))?.[1];
    const claimHeaders = new Headers(claimRequest?.headers);
    expect(claimHeaders.get("X-CSRF-TOKEN")).toBe("approval-csrf");
    expect(claimHeaders.has("X-Synthetic-Approver-Id")).toBe(false);
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
    await waitFor(() =>
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.filter(([input]) => input === "/api/approver/compensation-proposals"),
      ).toHaveLength(2),
    );
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
            expiresAt: "2099-08-11T03:15:00Z",
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

    render(<ApprovalWorkbench />);

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

    render(<ApprovalWorkbench />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "待审批补偿" }),
    ).toBeInTheDocument();
    expect(globalThis.location.search).toBe("");
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);
  });

  it("领取前只读取队列，领取后才展示真实审批投影", async () => {
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
        Response.json({
          proposalRevisionId: REVISION_ID,
          leaseToken: LEASE_TOKEN,
          leaseVersion: 1,
          expiresAt: "2099-08-11T03:15:00Z",
          replayed: false,
        }),
      )
      .mockResolvedValueOnce(
        Response.json({ ...approvalSnapshot(), leaseExpiresAt: "2099-08-11T03:15:00Z" }),
      )
      .mockResolvedValueOnce(openStream());

    render(<ApprovalWorkbench />);

    expect(await screen.findByText("27000000…0001")).toBeInTheDocument();
    expect(screen.queryByText("ORDER-DELAY-001")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "批准补偿" })).not.toBeInTheDocument();
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "领取审批" }));

    expect(await screen.findByText("资格校验")).toBeInTheDocument();
    expect(screen.getByText("权威金额")).toBeInTheDocument();
    expect(screen.getByText("政策信息")).toBeInTheDocument();
    expect(screen.getByText("责任链")).toBeInTheDocument();
    expect(screen.getByText("order:ORDER-DELAY-001")).toBeInTheDocument();
    expect(screen.queryByText(/AI 建议批准|风险评级|PRP-/)).not.toBeInTheDocument();
    expect(screen.queryByText(/内容摘要|审批租约|租约 v/)).not.toBeInTheDocument();
  });

  it("队列直接复制完整 UUID 并提供完整表格语义", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      Response.json([
        {
          proposalRevisionId: REVISION_ID,
          compensationMethod: "COUPON",
          amount: 20,
          submittedAt: "2026-08-11T03:00:00Z",
          expiresAt: "2026-08-12T03:00:00Z",
        },
      ]),
    );

    render(<ApprovalWorkbench />);

    expect(await screen.findByRole("columnheader", { name: "提案 UUID" })).toBeInTheDocument();
    expect(screen.getAllByRole("cell")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "复制完整提案 UUID" }));
    expect(writeText).toHaveBeenCalledWith(REVISION_ID);
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);
  });

  it("领取请求进行中禁止并发领取", async () => {
    let finishClaim: ((response: Response) => void) | undefined;
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
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (finishClaim = resolve)))
      .mockResolvedValueOnce(Response.json(approvalSnapshot()))
      .mockResolvedValueOnce(openStream());

    render(<ApprovalWorkbench />);

    const claim = await screen.findByRole("button", { name: "领取审批" });
    fireEvent.click(claim);
    fireEvent.click(claim);

    expect(screen.getByRole("button", { name: "正在领取" })).toBeDisabled();
    await waitFor(() =>
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.filter(([input]) => String(input).endsWith("/claims")),
      ).toHaveLength(1),
    );

    finishClaim?.(
      Response.json({
        proposalRevisionId: REVISION_ID,
        leaseToken: LEASE_TOKEN,
        leaseVersion: 1,
        expiresAt: "2099-08-11T03:15:00Z",
      }),
    );
    expect(await screen.findByText("order:ORDER-DELAY-001")).toBeInTheDocument();
  });

  it("批准经过明确确认并携带版本、摘要、租约和幂等键", async () => {
    mockClaimFlow(async (path) => {
      if (path.endsWith("/approve")) {
        return Response.json({ proposalRevisionId: REVISION_ID, decision: "APPROVED" });
      }
      return undefined;
    });

    render(<ApprovalWorkbench />);
    fireEvent.click(await screen.findByRole("button", { name: "领取审批" }));
    fireEvent.click(await screen.findByRole("button", { name: "批准补偿" }));

    expect(screen.getByRole("dialog", { name: "确认批准补偿" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认批准" }));

    await waitFor(() =>
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.some(([input]) => String(input).endsWith("/approve")),
      ).toBe(true),
    );
    const request = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(([input]) => String(input).endsWith("/approve"))?.[1];
    const headers = new Headers(request?.headers);
    expect(headers.get("X-Approval-Lease-Token")).toBe(LEASE_TOKEN);
    expect(headers.get("X-Approval-Lease-Version")).toBe("1");
    expect(headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/i);
    expect(JSON.parse(String(request?.body))).toMatchObject({
      proposalRevision: 1,
      contentDigest: "0".repeat(64),
    });
  });

  it("确认对话框接管焦点、约束键盘遍历并在取消后恢复触发点", async () => {
    mockClaimFlow(async () => undefined);

    render(<ApprovalWorkbench />);
    fireEvent.click(await screen.findByRole("button", { name: "领取审批" }));
    const trigger = await screen.findByRole("button", { name: "批准补偿" });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "确认批准补偿" });
    const cancel = screen.getByRole("button", { name: "取消" });
    const confirm = screen.getByRole("button", { name: "确认批准" });
    const note = screen.getByLabelText("审批备注（可选）");
    await waitFor(() => expect(cancel).toHaveFocus());

    confirm.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(note).toHaveFocus();

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "确认批准补偿" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("驳回确认要求真实内部理由", async () => {
    mockClaimFlow(async (path) => {
      if (path.endsWith("/reject")) {
        return Response.json({ proposalRevisionId: REVISION_ID, decision: "REJECTED" });
      }
      return undefined;
    });

    render(<ApprovalWorkbench />);
    fireEvent.click(await screen.findByRole("button", { name: "领取审批" }));
    fireEvent.click(await screen.findByRole("button", { name: "驳回并转人工" }));

    const confirm = screen.getByRole("button", { name: "确认驳回并转人工" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("内部驳回理由"), {
      target: { value: "现有证据不足以支持该补偿金额" },
    });
    fireEvent.click(confirm);

    await waitFor(() =>
      expect(
        vi.mocked(globalThis.fetch).mock.calls.some(([input]) => String(input).endsWith("/reject")),
      ).toBe(true),
    );
    const request = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(([input]) => String(input).endsWith("/reject"))?.[1];
    expect(JSON.parse(String(request?.body))).toMatchObject({
      internalReason: "现有证据不足以支持该补偿金额",
    });
  });

  it("决定响应不确定时不普通重试写操作而恢复权威审批视图", async () => {
    let approvalViewReads = 0;
    let approveWrites = 0;
    mockClaimFlow(async (path) => {
      if (path.endsWith("/approve")) {
        approveWrites += 1;
        throw new TypeError("response lost");
      }
      if (path.endsWith("/approval-view")) {
        approvalViewReads += 1;
        return Response.json({
          ...approvalSnapshot(),
          cursor: `approval-view-v1:${approvalViewReads + 1}`,
          leaseExpiresAt: "2099-08-11T03:15:00Z",
        });
      }
      return undefined;
    });

    render(<ApprovalWorkbench />);
    fireEvent.click(await screen.findByRole("button", { name: "领取审批" }));
    fireEvent.click(await screen.findByRole("button", { name: "批准补偿" }));
    fireEvent.click(screen.getByRole("button", { name: "确认批准" }));

    expect(await screen.findByRole("heading", { name: "ORDER-DELAY-001" })).toBeInTheDocument();
    expect(approveWrites).toBe(1);
    expect(approvalViewReads).toBe(2);
  });

  it("释放审批使用当前 Session 的 CSRF 和租约围栏且不发送合成审批人", async () => {
    let queueReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/approver/compensation-proposals") {
        queueReads += 1;
        return Response.json(
          queueReads === 1
            ? [
                {
                  proposalRevisionId: REVISION_ID,
                  compensationMethod: "COUPON",
                  amount: 20,
                  submittedAt: "2026-08-11T03:00:00Z",
                  expiresAt: "2026-08-12T03:00:00Z",
                },
              ]
            : [],
        );
      }
      if (path.endsWith("/claims")) {
        return Response.json(
          {
            proposalRevisionId: REVISION_ID,
            leaseToken: LEASE_TOKEN,
            leaseVersion: 1,
            expiresAt: "2099-08-11T03:15:00Z",
            replayed: false,
          },
          { status: 201 },
        );
      }
      if (path.endsWith("/approval-view")) return Response.json(approvalSnapshot());
      if (path.endsWith("/approval-view/events")) return openStream();
      if (path.endsWith("/release")) {
        return Response.json({ proposalRevisionId: REVISION_ID, released: true, replayed: false });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ApprovalWorkbench />);
    fireEvent.click(await screen.findByRole("button", { name: "领取审批" }));
    fireEvent.click(await screen.findByRole("button", { name: "释放审批" }));
    fireEvent.click(screen.getByRole("button", { name: "确认释放审批责任" }));

    expect(await screen.findByText("审批责任已释放，已返回队列。")).toBeInTheDocument();
    const releaseRequest = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(([input]) => String(input).endsWith("/release"))?.[1];
    const releaseHeaders = new Headers(releaseRequest?.headers);
    expect(releaseHeaders.get("X-CSRF-TOKEN")).toBe("approval-csrf");
    expect(releaseHeaders.get("X-Approval-Lease-Token")).toBe(LEASE_TOKEN);
    expect(releaseHeaders.get("X-Approval-Lease-Version")).toBe("1");
    expect(releaseHeaders.has("X-Synthetic-Approver-Id")).toBe(false);
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
            expiresAt: "2099-08-11T03:15:00Z",
            replayed: false,
          },
          { status: 201 },
        ),
      )
      .mockResolvedValueOnce(Response.json(approvalSnapshot()))
      .mockResolvedValueOnce(sseResponse(stale + gap))
      .mockResolvedValueOnce(Response.json({ ...approvalSnapshot(), cursor: "approval-view-v1:4" }))
      .mockResolvedValueOnce(openStream());

    render(<ApprovalWorkbench />);
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

function mockClaimFlow(extra: (path: string, init?: RequestInit) => Promise<Response | undefined>) {
  let queueReads = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path === "/api/approver/compensation-proposals") {
      queueReads += 1;
      return Response.json(
        queueReads === 1
          ? [
              {
                proposalRevisionId: REVISION_ID,
                compensationMethod: "COUPON",
                amount: 20,
                submittedAt: "2026-08-11T03:00:00Z",
                expiresAt: "2026-08-12T03:00:00Z",
              },
            ]
          : [],
      );
    }
    if (path.endsWith("/claims")) {
      return Response.json({
        proposalRevisionId: REVISION_ID,
        leaseToken: LEASE_TOKEN,
        leaseVersion: 1,
        expiresAt: "2099-08-11T03:15:00Z",
        replayed: false,
      });
    }
    const response = await extra(path, init);
    if (response) return response;
    if (path.endsWith("/approval-view")) {
      return Response.json({ ...approvalSnapshot(), leaseExpiresAt: "2099-08-11T03:15:00Z" });
    }
    if (path.endsWith("/approval-view/events")) return openStream();
    throw new Error(`unexpected request: ${path}`);
  });
}
