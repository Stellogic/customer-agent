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
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis.navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
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
    expect(await screen.findAllByText("26000000…0001")).toHaveLength(1);
    expect(await screen.findAllByText("26000000…0002")).toHaveLength(2);
    expect(screen.queryByText(HANDOFF_TICKET)).not.toBeInTheDocument();
    expect(screen.queryByText(BREACHED_TICKET)).not.toBeInTheDocument();
    expect(screen.queryByText(/customer-demo|ORDER-DELAY|物流延迟/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /搜索|筛选|回复|订单查询/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /转派|解决|导出/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: `复制完整工单 UUID ${HANDOFF_TICKET}` }));
    expect(writeText).toHaveBeenCalledWith(HANDOFF_TICKET);
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

    expect(
      await screen.findByRole("heading", { name: "当前身份无权访问此页面" }),
    ).toBeInTheDocument();
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(globalThis.fetch)).not.toHaveBeenCalledWith(
      "/api/support/workbench/snapshot",
      expect.anything(),
    );
  });

  it("确认领取后才写入分配并分区呈现真实授权详情", async () => {
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
          publicConversation: [
            {
              author: "CUSTOMER",
              body: "物流一直没有更新",
              sentAt: "2026-08-11T01:10:00Z",
            },
          ],
          investigationFacts: [
            {
              factType: "DELIVERY_DELAY",
              factValue: "26 hours",
              evidenceReference: "shipment:ORDER-DELAY-001",
              recordedAt: "2026-08-11T01:12:00Z",
            },
          ],
          businessTimeline: [
            {
              eventType: "SUPPORT_ASSIGNMENT_CREATED",
              actorId: "support-demo",
              occurredAt: "2026-08-11T01:15:00Z",
            },
          ],
        });
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);

    fireEvent.click(await screen.findByRole("button", { name: `领取工单 ${HANDOFF_TICKET}` }));

    expect(await screen.findByRole("dialog", { name: "确认领取工单" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      `/api/support/workbench/tickets/${HANDOFF_TICKET}/claims`,
      expect.anything(),
    );
    fireEvent.click(screen.getByRole("button", { name: "确认领取" }));

    expect(await screen.findByRole("heading", { name: "授权工单详情" })).toBeInTheDocument();
    expect(screen.getByText("customer-demo")).toBeInTheDocument();
    expect(screen.getByText("ORDER-DELAY-001")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "公开沟通" })).toBeInTheDocument();
    expect(screen.getByText("物流一直没有更新")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "调查事实" })).toBeInTheDocument();
    expect(screen.getByText("26 hours")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "业务时间线" })).toBeInTheDocument();
    expect(screen.getByText("SUPPORT_ASSIGNMENT_CREATED")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/support/workbench/tickets/${HANDOFF_TICKET}`,
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("assignment 失效后移除旧详情并重读权威详情", async () => {
    let detailReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/support/workbench/snapshot") {
        return snapshotResponse("support-workbench-v1:1", [handoffItem()], []);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "support-csrf", headerName: "X-CSRF-TOKEN" });
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/claims`) {
        return Response.json(
          { ticketId: HANDOFF_TICKET, supportId: "support-demo", replayed: false },
          { status: 201 },
        );
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        detailReads += 1;
        if (detailReads > 1) return Response.json({}, { status: 404 });
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
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return sseResponse("");
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);
    await confirmClaim(HANDOFF_TICKET);

    expect(await screen.findByRole("alert")).toHaveTextContent("分配已失效");
    expect(screen.queryByRole("heading", { name: "授权工单详情" })).not.toBeInTheDocument();
    expect(detailReads).toBe(2);
  });

  it("从旧详情切换领取失败时立即移除不再监控的旧详情", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/support/workbench/snapshot") {
        return snapshotResponse("support-workbench-v1:1", [handoffItem(), breachedItem()], []);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "support-csrf", headerName: "X-CSRF-TOKEN" });
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/claims`) {
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
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path === `/api/support/workbench/tickets/${BREACHED_TICKET}/claims`) {
        return Response.json({}, { status: 404 });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);
    await confirmClaim(HANDOFF_TICKET);
    expect(await screen.findByText("ORDER-DELAY-001")).toBeInTheDocument();

    await confirmClaim(BREACHED_TICKET);
    expect(await screen.findByRole("alert")).toHaveTextContent("领取未完成");
    expect(screen.queryByText("ORDER-DELAY-001")).not.toBeInTheDocument();
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
    expect(await screen.findAllByText("26000000…0002")).toHaveLength(2);
    expect(screen.queryByText("26000000…0001")).not.toBeInTheDocument();
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
    expect(await screen.findByText("26000000…0002")).toBeInTheDocument();
    expect(screen.queryByText("26000000…0001")).not.toBeInTheDocument();
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

    expect(await screen.findAllByText("26000000…0002")).toHaveLength(2);
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

    expect(await screen.findAllByText("26000000…0002")).toHaveLength(2);
    expect(screen.queryByText("26000000…0001")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新同步队列" })).not.toBeDisabled();
  });

  it("保留地标、标题层级和语义化队列表格", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:1", [handoffItem()], []))
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    expect(await screen.findByRole("main", { name: "客服工作台" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "待接手工单" })).toBeInTheDocument();
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

async function confirmClaim(ticketId: string) {
  fireEvent.click(await screen.findByRole("button", { name: `领取工单 ${ticketId}` }));
  fireEvent.click(await screen.findByRole("button", { name: "确认领取" }));
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
