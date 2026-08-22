import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RootApplication } from "./RootApplication";
import { SupportWorkbench } from "./SupportWorkbench";

const HANDOFF_TICKET = "26000000-0000-0000-0000-000000000001";
const BREACHED_TICKET = "26000000-0000-0000-0000-000000000002";

describe("客服共享队列工作台", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it("只在客服路由读取独立权威快照并呈现两种最小摘要", async () => {
    globalThis.history.replaceState(null, "", "/internal/support");
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        Response.json({
          id: "session-support-person",
          displayName: "演示客服",
          subjectType: "INTERNAL",
          roles: ["SUPPORT"],
          capabilities: ["SUPPORT_WORKBENCH_ACCESS"],
        }),
      )
      .mockResolvedValueOnce(
        snapshotResponse(
          "support-workbench-v1:7",
          [handoffItem(), breachedItem()],
          [breachedItem()],
        ),
      )
      .mockResolvedValueOnce(openStream());

    render(<RootApplication />);

    expect(await screen.findByRole("heading", { name: "客服共享队列" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "待接手工单" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "SLA 违约升级" })).toBeInTheDocument();
    expect(await screen.findAllByText(HANDOFF_TICKET)).toHaveLength(1);
    expect(await screen.findAllByText(BREACHED_TICKET)).toHaveLength(2);
    expect(screen.queryByRole("combobox", { name: /角色/ })).not.toBeInTheDocument();
    expect(
      screen.queryByText(/CUSTOMER_REQUESTED|AGENT_HUMAN_HANDOFF|调查摘要/),
    ).not.toBeInTheDocument();
    expect(vi.mocked(globalThis.fetch).mock.calls[0]?.[0]).toBe("/api/auth/session");
    expect(vi.mocked(globalThis.fetch).mock.calls[1]?.[0]).toBe("/api/support/workbench/snapshot");
    expect(
      new Headers(vi.mocked(globalThis.fetch).mock.calls[1]?.[1]?.headers).get(
        "X-Synthetic-Support-Id",
      ),
    ).toBeNull();
  });

  it("客户或审批人直接访问客服 URL 不会被自动提升为客服", async () => {
    globalThis.history.replaceState(null, "", "/internal/support");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      Response.json({
        id: "approver-demo",
        displayName: "演示审批人",
        subjectType: "INTERNAL",
        roles: ["APPROVER"],
        capabilities: ["APPROVAL_WORKBENCH_ACCESS"],
      }),
    );

    render(<RootApplication />);

    expect(await screen.findByRole("heading", { name: "403" })).toBeInTheDocument();
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(globalThis.fetch)).not.toHaveBeenCalledWith(
      "/api/support/workbench/snapshot",
      expect.anything(),
    );
  });

  it("领取写操作携带当前 CSRF 且成功后只读取已分配工单详情", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/support/workbench/snapshot") {
        return snapshotResponse("support-workbench-v1:1", [handoffItem()], []);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "support-csrf", headerName: "X-CSRF-TOKEN" });
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/claims`) {
        expect(init?.method).toBe("POST");
        expect(new Headers(init?.headers).get("X-CSRF-TOKEN")).toBe("support-csrf");
        expect(new Headers(init?.headers).get("X-Synthetic-Support-Id")).toBeNull();
        return Response.json(
          { ticketId: HANDOFF_TICKET, supportId: "support-demo", replayed: false },
          { status: 201 },
        );
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        return Response.json({
          ticketId: HANDOFF_TICKET,
          customerId: "customer-demo",
          orderReference: "ORDER-DELAY-001",
          description: "物流延迟",
          lifecycleState: "WAITING_FOR_CUSTOMER",
          handlingMode: "HUMAN",
          publicConversation: [],
          investigationFacts: [],
          businessTimeline: [],
        });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);

    fireEvent.click(await screen.findByRole("button", { name: `领取工单 ${HANDOFF_TICKET}` }));

    expect(await screen.findByRole("heading", { name: "当前工单详情" })).toBeInTheDocument();
    expect(screen.getByText("ORDER-DELAY-001")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/support/workbench/tickets/${HANDOFF_TICKET}`,
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("序号缺口停止旧流并整体替换为新快照", async () => {
    let resolveRecovery: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:2", [handoffItem()], []))
      .mockResolvedValueOnce(
        sseResponse(
          eventBlock("support-workbench-v1:4", "QUEUE_TICKET_REMOVED", {
            ticketId: HANDOFF_TICKET,
          }),
        ),
      )
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveRecovery = resolve;
          }),
      )
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    expect(await screen.findByRole("alert")).toHaveTextContent("当前队列可能过期");
    resolveRecovery?.(
      snapshotResponse("support-workbench-v1:8", [breachedItem()], [breachedItem()]),
    );
    expect(await screen.findAllByText(BREACHED_TICKET)).toHaveLength(2);
    expect(screen.queryByText(HANDOFF_TICKET)).not.toBeInTheDocument();
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) => input === "/api/support/workbench/snapshot"),
    ).toHaveLength(2);
  });

  it("服务端结束单次 SSE 后自动重读快照并建立新的授权连接", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:1", [handoffItem()], []))
      .mockResolvedValueOnce(sseResponse(""))
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:2", [breachedItem()], []))
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    await waitFor(() =>
      expect(
        vi
          .mocked(globalThis.fetch)
          .mock.calls.filter(([input]) => input === "/api/support/workbench/snapshot"),
      ).toHaveLength(2),
    );
    expect(await screen.findByText(BREACHED_TICKET)).toBeInTheDocument();
    expect(screen.queryByText(HANDOFF_TICKET)).not.toBeInTheDocument();
  });

  it("非法 payload 与 reset_required 都不会继续应用旧状态", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:2", [handoffItem()], []))
      .mockResolvedValueOnce(
        sseResponse(
          eventBlock("support-workbench-v1:3", "QUEUE_TICKET_UPSERTED", {
            ticketId: BREACHED_TICKET,
            lifecycleState: "INVESTIGATING",
            handlingMode: "AGENT",
            sharedEnteredAt: "2026-08-11T01:05:00Z",
            escalationEnteredAt: null,
            investigationSummary: "不得进入浏览器事件",
          }),
        ),
      )
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:9", [], []))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ code: "SNAPSHOT_REQUIRED" }), { status: 409 }),
      )
      .mockResolvedValueOnce(
        snapshotResponse("support-workbench-v1:10", [breachedItem()], [breachedItem()]),
      )
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    expect(await screen.findAllByText(BREACHED_TICKET)).toHaveLength(2);
    expect(screen.queryByText("不得进入浏览器事件")).not.toBeInTheDocument();
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) => input === "/api/support/workbench/snapshot"),
    ).toHaveLength(3);
  });

  it("异常断线也自动清除旧投影并重新读取权威快照", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:2", [handoffItem()], []))
      .mockRejectedValueOnce(new TypeError("disconnected"))
      .mockResolvedValueOnce(
        snapshotResponse("support-workbench-v1:3", [breachedItem()], [breachedItem()]),
      )
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    expect(await screen.findAllByText(BREACHED_TICKET)).toHaveLength(2);
    expect(screen.queryByText(HANDOFF_TICKET)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新同步队列" })).not.toBeDisabled();
  });

  it("窄屏仍保留地标、标题层级和可读的队列列表", async () => {
    Object.defineProperty(globalThis, "innerWidth", { configurable: true, value: 360 });
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:1", [handoffItem()], []))
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    expect(await screen.findByRole("main", { name: "客服工作台" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "待接手工单" })).toBeInTheDocument();
    expect(screen.getByText("队列可发现不等于工单详情授权")).toBeInTheDocument();
  });
});

function handoffItem() {
  return {
    ticketId: HANDOFF_TICKET,
    lifecycleState: "WAITING_FOR_CUSTOMER",
    handlingMode: "HUMAN",
    enteredAt: "2026-08-11T01:00:00Z",
  };
}

function breachedItem() {
  return {
    ticketId: BREACHED_TICKET,
    lifecycleState: "INVESTIGATING",
    handlingMode: "AGENT",
    enteredAt: "2026-08-11T01:05:00Z",
  };
}

function snapshotResponse(cursor: string, sharedQueue: unknown[], escalationQueue: unknown[]) {
  return Response.json({
    view: "SUPPORT_WORKBENCH",
    schema: "support-workbench-v1",
    cursor,
    sharedQueue,
    escalationQueue,
  });
}

function eventBlock(id: string, type: string, payload: unknown) {
  return `id:${id}\nevent:${type}\ndata:${JSON.stringify({
    view: "SUPPORT_WORKBENCH",
    schema: "support-workbench-v1",
    payload,
  })}\n\n`;
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
