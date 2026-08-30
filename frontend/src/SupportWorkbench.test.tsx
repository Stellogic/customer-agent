import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { announceHumanSessionChange } from "./humanSessionLifecycle";
import { RootApplication } from "./RootApplication";
import { SupportWorkbench } from "./SupportWorkbench";

const HANDOFF_TICKET = "26000000-0000-0000-0000-000000000001";
const BREACHED_TICKET = "26000000-0000-0000-0000-000000000002";
const SECOND_HUMAN_TICKET = "26000000-0000-0000-0000-000000000003";
const SNAPSHOT_URL = "/api/support/workbench/snapshot?schema=support-workbench-v2";

describe("客服共享队列工作台", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    globalThis.sessionStorage.clear();
    globalThis.localStorage.clear();
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
          "support-workbench-v2:7",
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
    expect(screen.queryByText(/customer-demo|问题描述|调查摘要/)).not.toBeInTheDocument();
    expect(screen.getAllByText("ORDER-DELAY-001").length).toBeGreaterThan(0);
    expect(screen.getByText("包裹未收到")).toBeInTheDocument();
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
    expect(screen.queryByText(/快照游标/)).not.toBeInTheDocument();
    expect(vi.mocked(globalThis.fetch).mock.calls[0]?.[0]).toBe("/api/auth/session");
    expect(vi.mocked(globalThis.fetch).mock.calls[1]?.[0]).toBe(SNAPSHOT_URL);
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
    expect(vi.mocked(globalThis.fetch)).not.toHaveBeenCalledWith(SNAPSHOT_URL, expect.anything());
  });

  it("确认领取后才写入分配并分区呈现真实授权详情", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [handoffItem()], []);
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
      if (path.endsWith("/compensation-options")) return couponOptions();
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
    expect(screen.getAllByText("ORDER-DELAY-001").length).toBeGreaterThan(1);
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
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [handoffItem()], []);
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
      if (path.endsWith("/compensation-options")) return couponOptions();
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
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [handoffItem(), secondHumanItem()], []);
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
      if (path === `/api/support/workbench/tickets/${SECOND_HUMAN_TICKET}/claims`) {
        return Response.json({}, { status: 404 });
      }
      if (path.endsWith("/compensation-options")) return couponOptions();
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);
    await confirmClaim(HANDOFF_TICKET);
    expect((await screen.findAllByText("ORDER-DELAY-001")).length).toBeGreaterThan(0);

    await confirmClaim(SECOND_HUMAN_TICKET);
    expect(await screen.findByRole("alert")).toHaveTextContent("领取未完成");
    expect(screen.queryByText("customer-demo")).not.toBeInTheDocument();
  });

  it("序号缺口停止旧流并整体替换为新快照", async () => {
    let resolveRecovery: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v2:2", [handoffItem()], []))
      .mockResolvedValueOnce(
        sseResponse(
          eventBlock("support-workbench-v2:4", "QUEUE_TICKET_REMOVED", {
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
      snapshotResponse("support-workbench-v2:8", [breachedItem()], [breachedItem()]),
    );
    expect(await screen.findAllByText("26000000…0002")).toHaveLength(2);
    expect(screen.queryByText("26000000…0001")).not.toBeInTheDocument();
    expect(
      vi.mocked(globalThis.fetch).mock.calls.filter(([input]) => input === SNAPSHOT_URL),
    ).toHaveLength(2);
  });

  it("服务端结束单次 SSE 后自动重读快照并建立新的授权连接", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v2:1", [handoffItem()], []))
      .mockResolvedValueOnce(sseResponse(""))
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v2:2", [breachedItem()], []))
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    await waitFor(() =>
      expect(
        vi.mocked(globalThis.fetch).mock.calls.filter(([input]) => input === SNAPSHOT_URL),
      ).toHaveLength(2),
    );
    expect(await screen.findByText("26000000…0002")).toBeInTheDocument();
    expect(screen.queryByText("26000000…0001")).not.toBeInTheDocument();
  });

  it("非法 payload 与 reset_required 都不会继续应用旧状态", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v2:2", [handoffItem()], []))
      .mockResolvedValueOnce(
        sseResponse(
          eventBlock("support-workbench-v2:3", "QUEUE_TICKET_UPSERTED", {
            ticketId: BREACHED_TICKET,
            orderReference: "ORDER-DELAY-001",
            issueKind: "LOGISTICS_DELAY",
            lifecycleState: "INVESTIGATING",
            handlingMode: "AGENT",
            sharedEnteredAt: "2026-08-11T01:05:00Z",
            escalationEnteredAt: null,
            investigationSummary: "不得进入浏览器事件",
          }),
        ),
      )
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v2:9", [], []))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ code: "SNAPSHOT_REQUIRED" }), { status: 409 }),
      )
      .mockResolvedValueOnce(
        snapshotResponse("support-workbench-v2:10", [breachedItem()], [breachedItem()]),
      )
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    expect(await screen.findAllByText("26000000…0002")).toHaveLength(2);
    expect(screen.queryByText("不得进入浏览器事件")).not.toBeInTheDocument();
    expect(
      vi.mocked(globalThis.fetch).mock.calls.filter(([input]) => input === SNAPSHOT_URL),
    ).toHaveLength(3);
  });

  it("异常断线也自动清除旧投影并重新读取权威快照", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v2:2", [handoffItem()], []))
      .mockRejectedValueOnce(new TypeError("disconnected"))
      .mockResolvedValueOnce(
        snapshotResponse("support-workbench-v2:3", [breachedItem()], [breachedItem()]),
      )
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    expect(await screen.findAllByText("26000000…0002")).toHaveLength(2);
    expect(screen.queryByText("26000000…0001")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新同步队列" })).not.toBeDisabled();
  });

  it("保留地标、标题层级和语义化队列表格", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v2:1", [handoffItem()], []))
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    expect(await screen.findByRole("main", { name: "客服工作台" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "待接手工单" })).toBeInTheDocument();
    expect(screen.getByText("队列可发现不等于工单详情授权")).toBeInTheDocument();
  });

  it("订单分组保持队列最早进入顺序而不是按订单号重排", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        snapshotResponse(
          "support-workbench-v2:2",
          [
            { ...handoffItem(), orderReference: "ORDER-Z", enteredAt: "2026-08-11T01:00:00Z" },
            { ...breachedItem(), orderReference: "ORDER-A", enteredAt: "2026-08-11T01:05:00Z" },
          ],
          [],
        ),
      )
      .mockResolvedValueOnce(openStream());

    const { container } = render(<SupportWorkbench />);

    await screen.findByText("ORDER-Z");
    expect(
      [...container.querySelectorAll(".support-order-group > header strong")].map(
        (element) => element.textContent,
      ),
    ).toEqual(["ORDER-Z", "ORDER-A"]);
  });

  it("刷新后从权威快照恢复当前负责工单详情", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:4", [], [], [HANDOFF_TICKET]);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        return Response.json(humanDetails());
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path.endsWith("/compensation-options")) return couponOptions();
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);

    expect(await screen.findByRole("heading", { name: "授权工单详情" })).toBeInTheDocument();
    const summary = screen.getByLabelText("工单基本信息");
    expect(within(summary).getByText("customer-demo")).toBeInTheDocument();
    expect(within(summary).getByText("support-demo")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "人工公开回复" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: `领取工单 ${HANDOFF_TICKET}` }),
    ).not.toBeInTheDocument();
  });

  it("刷新后恢复同一客服全部 ACTIVE 领取并可切换详情", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse(
          "support-workbench-v2:5",
          [],
          [],
          [HANDOFF_TICKET, SECOND_HUMAN_TICKET],
        );
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        return Response.json(humanDetails());
      }
      if (path === `/api/support/workbench/tickets/${SECOND_HUMAN_TICKET}`) {
        return Response.json({
          ...humanDetails(),
          ticketId: SECOND_HUMAN_TICKET,
          description: "第二张已领取工单",
          assignedSupportId: "support-demo",
        });
      }
      if (
        path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events` ||
        path === `/api/support/workbench/tickets/${SECOND_HUMAN_TICKET}/events`
      ) {
        return openStream();
      }
      if (path.endsWith("/compensation-options")) return couponOptions();
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);

    expect(await screen.findByRole("heading", { name: "授权工单详情" })).toBeInTheDocument();
    expect(screen.getByText("物流延迟")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "已领取工单" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: `打开已领取工单 ${SECOND_HUMAN_TICKET}` }));
    expect(await screen.findByText("第二张已领取工单")).toBeInTheDocument();
    const description = screen.getByRole("heading", { name: "问题描述" }).parentElement;
    expect(description).not.toBeNull();
    expect(within(description!).queryByText("物流延迟")).not.toBeInTheDocument();
  });

  it("AGENT 处理模式的队列条目不能领取", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v2:1", [breachedItem()], []))
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    expect(await screen.findByText("Agent 处理中")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: `领取工单 ${BREACHED_TICKET}` }),
    ).not.toBeInTheDocument();
  });

  it("释放领取后清除详情并重新读取权威快照", async () => {
    let released = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse(
          released ? "support-workbench-v2:6" : "support-workbench-v2:5",
          released ? [handoffItem()] : [],
          [],
          released ? [] : [HANDOFF_TICKET],
        );
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "support-csrf", headerName: "X-CSRF-TOKEN" });
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        if (released) return Response.json({}, { status: 404 });
        return Response.json(humanDetails());
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/release`) {
        expect(init?.method).toBe("POST");
        released = true;
        return Response.json(
          { ticketId: HANDOFF_TICKET, supportId: "support-demo", replayed: false },
          { status: 201 },
        );
      }
      if (path.endsWith("/compensation-options")) return couponOptions();
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);
    expect(await screen.findByRole("heading", { name: "授权工单详情" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "释放领取" }));
    expect(await screen.findByRole("heading", { name: "领取后查看授权详情" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "授权工单详情" })).not.toBeInTheDocument();
  });

  it("HUMAN 模式下当前负责客服发送公开回复并使用稳定幂等键", async () => {
    const idempotencyKey = "16300000-0000-4000-8000-000000000001";
    const publicMessageId = "16300000-0000-4000-8000-000000000101";
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(idempotencyKey);
    let conversation = humanDetails().publicConversation;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [handoffItem()], []);
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
        return Response.json({ ...humanDetails(), publicConversation: conversation });
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/messages`) {
        expect(init?.method).toBe("POST");
        expect(new Headers(init?.headers).get("Idempotency-Key")).toBe(idempotencyKey);
        expect(new Headers(init?.headers).get("X-CSRF-TOKEN")).toBe("support-csrf");
        expect(JSON.parse(String(init?.body))).toEqual({
          schema: "support-workbench-v2",
          message: "包裹已在派送中，请再观察今天的物流更新。",
        });
        conversation = [
          ...conversation,
          {
            messageId: publicMessageId,
            author: "SUPPORT",
            body: "包裹已在派送中，请再观察今天的物流更新。",
            sentAt: "2026-08-11T01:20:00Z",
          },
        ];
        return Response.json(
          {
            schema: "support-workbench-v2",
            ticketId: HANDOFF_TICKET,
            messageId: idempotencyKey,
            publicMessageId,
            outcome: "ACCEPTED",
            accepted: true,
            replayed: false,
          },
          { status: 201 },
        );
      }
      if (path.endsWith("/compensation-options")) return couponOptions();
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);
    await confirmClaim(HANDOFF_TICKET);
    fireEvent.change(await screen.findByRole("textbox", { name: "公开回复" }), {
      target: { value: "包裹已在派送中，请再观察今天的物流更新。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送公开回复" }));

    expect(await screen.findByText("公开回复已由 Spring 保存并对客户可见。")).toBeInTheDocument();
    expect(screen.getByText("包裹已在派送中，请再观察今天的物流更新。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查询发送结果" })).not.toBeInTheDocument();
  });

  it("发送结果不明确时只允许查询权威结果而不是重新发送", async () => {
    const idempotencyKey = "16300000-0000-4000-8000-000000000002";
    const publicMessageId = "16300000-0000-4000-8000-000000000102";
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(idempotencyKey);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [handoffItem()], []);
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
        return Response.json(humanDetails());
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/messages`) {
        throw new TypeError("disconnected");
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/messages/${idempotencyKey}`) {
        expect(init?.method ?? "GET").toBe("GET");
        return Response.json({
          schema: "support-workbench-v2",
          ticketId: HANDOFF_TICKET,
          messageId: idempotencyKey,
          publicMessageId,
          outcome: "ACCEPTED",
          accepted: true,
          replayed: true,
        });
      }
      if (path.endsWith("/compensation-options")) return couponOptions();
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);
    await confirmClaim(HANDOFF_TICKET);
    fireEvent.change(await screen.findByRole("textbox", { name: "公开回复" }), {
      target: { value: "请先不要重复提交。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送公开回复" }));

    expect(await screen.findByRole("button", { name: "查询发送结果" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送公开回复" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "公开回复" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "查询发送结果" }));
    expect(await screen.findByText("已从 Spring 权威结果确认公开回复已保存。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查询发送结果" })).not.toBeInTheDocument();
  });

  it("AGENT 处理模式不展示人工公开回复 composer", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [], [], [BREACHED_TICKET]);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === `/api/support/workbench/tickets/${BREACHED_TICKET}`) {
        return Response.json({
          ...humanDetails(),
          ticketId: BREACHED_TICKET,
          handlingMode: "AGENT",
          lifecycleState: "INVESTIGATING",
        });
      }
      if (path === `/api/support/workbench/tickets/${BREACHED_TICKET}/events`) {
        return openStream();
      }
      if (path.endsWith("/compensation-options")) return couponOptions();
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);

    expect(await screen.findByRole("heading", { name: "授权工单详情" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "人工公开回复" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "公开回复" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "标准补偿" })).not.toBeInTheDocument();
  });

  it("读取标准补偿方案时展示 loading", async () => {
    let resolveOptions: ((value: Response) => void) | undefined;
    const pendingOptions = new Promise<Response>((resolve) => {
      resolveOptions = resolve;
    });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [handoffItem()], [], [HANDOFF_TICKET]);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        return Response.json(humanDetails());
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path.endsWith("/compensation-options")) return pendingOptions;
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);
    expect(await screen.findByText("正在读取当前允许的标准补偿方案…")).toBeInTheDocument();
    resolveOptions?.(couponOptions());
    expect(await screen.findAllByText("10.00 CNY")).toHaveLength(2);
  });

  it("重新登录后不会沿用上一主体未确认发送请求", async () => {
    globalThis.sessionStorage.setItem(
      `support-workbench:pending-reply:${HANDOFF_TICKET}`,
      JSON.stringify({
        idempotencyKey: "16300000-0000-4000-8000-000000000003",
        body: "上一主体未确认的回复",
      }),
    );
    globalThis.sessionStorage.setItem(
      `support-workbench:pending-compensation:${HANDOFF_TICKET}`,
      JSON.stringify({
        kind: "proposal",
        idempotencyKey: "16400000-0000-4000-8000-000000000003",
      }),
    );
    announceHumanSessionChange("logged-out");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:4", [], [], [HANDOFF_TICKET]);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        return Response.json(humanDetails());
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path.endsWith("/compensation-options")) return couponOptions();
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);

    expect(await screen.findByRole("heading", { name: "人工公开回复" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查询发送结果" })).not.toBeInTheDocument();
    expect(screen.queryByText("上一主体未确认的回复")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查询提交结果" })).not.toBeInTheDocument();
    expect(
      screen.queryByText("上次标准补偿提交结果尚未确认，请查询 Spring 权威结果。"),
    ).not.toBeInTheDocument();
  });

  it("HUMAN 模式展示 Spring 计算的标准补偿并提交审批", async () => {
    const idempotencyKey = "16400000-0000-4000-8000-000000000001";
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(idempotencyKey);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [handoffItem()], [], [HANDOFF_TICKET]);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "support-csrf", headerName: "X-CSRF-TOKEN" });
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        return Response.json(humanDetails());
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path.endsWith("/compensation-options")) return couponOptions();
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/compensation-proposals`) {
        expect(init?.method).toBe("POST");
        expect(new Headers(init?.headers).get("Idempotency-Key")).toBe(idempotencyKey);
        expect(JSON.parse(String(init?.body))).toEqual({
          schema: "support-workbench-v2",
          planCode: "COUPON",
          reasonCode: "LOGISTICS_DELAY",
        });
        return Response.json(
          {
            schema: "support-workbench-v2",
            ticketId: HANDOFF_TICKET,
            requestId: idempotencyKey,
            proposalRevisionId: "16400000-0000-0000-0000-000000000101",
            proposalRevision: 1,
            compensationMethod: "COUPON",
            amount: 10,
            currency: "CNY",
            status: "PENDING_APPROVAL",
            outcome: "ACCEPTED",
            replayed: false,
          },
          { status: 201 },
        );
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);

    const panel = await screen.findByRole("region", { name: "标准补偿" });
    expect(await within(panel).findAllByText("10.00 CNY")).toHaveLength(2);
    expect(within(panel).getByText("delay-policy-v1")).toBeInTheDocument();
    expect(
      within(panel).queryByRole("button", { name: "提交例外补偿申请" }),
    ).not.toBeInTheDocument();
    fireEvent.click(await within(panel).findByRole("button", { name: "提交审批" }));
    expect(
      await screen.findByText("标准补偿提案已提交审批。客户只会看到类型、金额和待审批。"),
    ).toBeInTheDocument();
  });

  it("标准补偿提交结果未知时查询 Spring 权威结果", async () => {
    const idempotencyKey = "16400000-0000-4000-8000-000000000002";
    let queryCount = 0;
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(idempotencyKey);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [handoffItem()], [], [HANDOFF_TICKET]);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "support-csrf", headerName: "X-CSRF-TOKEN" });
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        return Response.json(humanDetails());
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path.endsWith("/compensation-options")) return couponOptions();
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/compensation-proposals`) {
        expect(init?.method).toBe("POST");
        return Response.json(
          { schema: "support-workbench-v2", ticketId: HANDOFF_TICKET },
          { status: 201 },
        );
      }
      if (
        path ===
        `/api/support/workbench/tickets/${HANDOFF_TICKET}/compensation-proposals/${idempotencyKey}`
      ) {
        expect(init?.method ?? "GET").toBe("GET");
        queryCount += 1;
        if (queryCount === 1) {
          return new Response(null, { status: 404 });
        }
        if (queryCount === 2) {
          return Response.json({ schema: "support-workbench-v2", ticketId: HANDOFF_TICKET });
        }
        return Response.json({
          schema: "support-workbench-v2",
          ticketId: HANDOFF_TICKET,
          requestId: idempotencyKey,
          proposalRevisionId: "16400000-0000-0000-0000-000000000101",
          proposalRevision: 1,
          compensationMethod: "COUPON",
          amount: 10,
          currency: "CNY",
          status: "PENDING_APPROVAL",
          outcome: "ACCEPTED",
          replayed: true,
        });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);
    const panel = await screen.findByRole("region", { name: "标准补偿" });
    fireEvent.click(await within(panel).findByRole("button", { name: "提交审批" }));
    expect(await within(panel).findByRole("button", { name: "查询提交结果" })).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "查询提交结果" }));
    expect(
      await screen.findByText("Spring 尚未找到该提交请求，请稍后使用同一请求身份继续查询。"),
    ).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "查询提交结果" })).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "查询提交结果" }));
    expect(
      await screen.findByText("提交结果仍未确认；请继续查询 Spring 权威结果，不要重复提交。"),
    ).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "查询提交结果" })).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "查询提交结果" }));
    expect(
      await screen.findByText("已从 Spring 权威结果确认标准补偿提案已提交审批。"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查询提交结果" })).not.toBeInTheDocument();
  });

  it("查询 404 后可用同一请求身份重试提交", async () => {
    const idempotencyKey = "16400000-0000-4000-8000-000000000004";
    let postCount = 0;
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(idempotencyKey);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [handoffItem()], [], [HANDOFF_TICKET]);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "support-csrf", headerName: "X-CSRF-TOKEN" });
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        return Response.json(humanDetails());
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path.endsWith("/compensation-options")) return couponOptions();
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/compensation-proposals`) {
        expect(init?.method).toBe("POST");
        expect(new Headers(init?.headers).get("Idempotency-Key")).toBe(idempotencyKey);
        expect(JSON.parse(String(init?.body))).toEqual({
          schema: "support-workbench-v2",
          planCode: "COUPON",
          reasonCode: "LOGISTICS_DELAY",
        });
        postCount += 1;
        if (postCount === 1) {
          return Response.json(
            { schema: "support-workbench-v2", ticketId: HANDOFF_TICKET },
            { status: 201 },
          );
        }
        return Response.json(
          {
            schema: "support-workbench-v2",
            ticketId: HANDOFF_TICKET,
            requestId: idempotencyKey,
            proposalRevisionId: "16400000-0000-0000-0000-000000000104",
            proposalRevision: 1,
            compensationMethod: "COUPON",
            amount: 10,
            currency: "CNY",
            status: "PENDING_APPROVAL",
            outcome: "ACCEPTED",
            replayed: true,
          },
          { status: 200 },
        );
      }
      if (
        path ===
        `/api/support/workbench/tickets/${HANDOFF_TICKET}/compensation-proposals/${idempotencyKey}`
      ) {
        expect(init?.method ?? "GET").toBe("GET");
        return new Response(null, { status: 404 });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);
    const panel = await screen.findByRole("region", { name: "标准补偿" });
    fireEvent.click(await within(panel).findByRole("button", { name: "提交审批" }));
    fireEvent.click(await within(panel).findByRole("button", { name: "查询提交结果" }));
    expect(
      await screen.findByText("Spring 尚未找到该提交请求，请稍后使用同一请求身份继续查询。"),
    ).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "使用同一请求身份重试提交" }));
    expect(
      await screen.findByText("标准补偿提案已提交审批。客户只会看到类型、金额和待审批。"),
    ).toBeInTheDocument();
    expect(postCount).toBe(2);
    expect(screen.queryByRole("button", { name: "查询提交结果" })).not.toBeInTheDocument();
  });

  it("标准补偿方案读取失败时展示 error", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [handoffItem()], [], [HANDOFF_TICKET]);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        return Response.json(humanDetails());
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path.endsWith("/compensation-options")) return new Response(null, { status: 503 });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);
    expect(
      await screen.findByText("标准补偿方案暂时不可用，请重新同步后再试。"),
    ).toBeInTheDocument();
  });

  it("没有标准方案时展示 empty，并允许独立例外补偿申请", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === SNAPSHOT_URL) {
        return snapshotResponse("support-workbench-v2:1", [handoffItem()], [], [HANDOFF_TICKET]);
      }
      if (path === "/api/support/workbench/events") return openStream();
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "support-csrf", headerName: "X-CSRF-TOKEN" });
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}`) {
        return Response.json(humanDetails());
      }
      if (path === `/api/support/workbench/tickets/${HANDOFF_TICKET}/events`) {
        return openStream();
      }
      if (path.endsWith("/compensation-options")) {
        return Response.json({
          schema: "support-workbench-v2",
          policyVersion: "delay-policy-v1",
          plans: [],
        });
      }
      if (path.endsWith("/exceptional-compensation-requests")) {
        expect(init?.method).toBe("POST");
        const requestId = new Headers(init?.headers).get("Idempotency-Key");
        expect(requestId).toBeTruthy();
        expect(JSON.parse(String(init?.body))).toEqual({
          schema: "support-workbench-v2",
          reasonCode: "STANDARD_PLAN_INSUFFICIENT",
          justification: "标准优惠券无法覆盖客户损失",
        });
        return Response.json(
          {
            schema: "support-workbench-v2",
            ticketId: HANDOFF_TICKET,
            requestId,
            exceptionalRequestId: "16400000-0000-0000-0000-000000000201",
            reasonCode: "STANDARD_PLAN_INSUFFICIENT",
            status: "SUBMITTED",
            outcome: "ACCEPTED",
            replayed: false,
          },
          { status: 201 },
        );
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<SupportWorkbench />);
    expect(await screen.findByText("当前没有允许的标准补偿方案。")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "例外补偿说明" }), {
      target: { value: "标准优惠券无法覆盖客户损失" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交例外补偿申请" }));
    expect(
      await screen.findByText("例外补偿申请已提交，不会走普通提案审批捷径。"),
    ).toBeInTheDocument();
  });

  it("空队列展示 empty 状态且领取前详情区保持等待", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v2:1", [], []))
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench />);

    expect(await screen.findAllByText("当前没有队列条目")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "领取后查看授权详情" })).toBeInTheDocument();
  });
});

function handoffItem() {
  return {
    ticketId: HANDOFF_TICKET,
    orderReference: "ORDER-DELAY-001",
    issueKind: "PACKAGE_NOT_RECEIVED",
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
    orderReference: "ORDER-DELAY-001",
    issueKind: "LOGISTICS_DELAY",
    lifecycleState: "INVESTIGATING",
    handlingMode: "AGENT",
    enteredAt: "2026-08-11T01:05:00Z",
  };
}

function secondHumanItem() {
  return {
    ticketId: SECOND_HUMAN_TICKET,
    orderReference: "ORDER-DELAY-002",
    issueKind: "PACKAGE_NOT_RECEIVED",
    lifecycleState: "WAITING_FOR_CUSTOMER",
    handlingMode: "HUMAN",
    enteredAt: "2026-08-11T01:08:00Z",
  };
}

function humanDetails() {
  return {
    ticketId: HANDOFF_TICKET,
    customerId: "customer-demo",
    orderReference: "ORDER-DELAY-001",
    description: "物流延迟",
    lifecycleState: "WAITING_FOR_CUSTOMER",
    handlingMode: "HUMAN",
    assignedSupportId: "support-demo",
    publicConversation: [
      {
        messageId: "26000000-0000-0000-0000-000000000201",
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
  };
}

function couponOptions() {
  return Response.json({
    schema: "support-workbench-v2",
    policyVersion: "delay-policy-v1",
    plans: [
      {
        planCode: "COUPON",
        compensationMethod: "COUPON",
        amount: 10,
        capAmount: 10,
        currency: "CNY",
        reasonCodes: ["LOGISTICS_DELAY"],
      },
    ],
  });
}

function snapshotResponse(
  cursor: string,
  sharedQueue: unknown[],
  escalationQueue: unknown[],
  assignedTicketIds: string[] = [],
) {
  return Response.json({
    view: "SUPPORT_WORKBENCH",
    schema: "support-workbench-v2",
    cursor,
    sharedQueue,
    escalationQueue,
    assignedTicketIds,
  });
}

function eventBlock(id: string, type: string, payload: unknown) {
  return `id:${id}\nevent:${type}\ndata:${JSON.stringify({
    view: "SUPPORT_WORKBENCH",
    schema: "support-workbench-v2",
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
