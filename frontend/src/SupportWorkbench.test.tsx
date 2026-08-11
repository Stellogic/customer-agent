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
    globalThis.history.replaceState(null, "", "/support");
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(Response.json({ id: "support-demo", role: "SUPPORT" }))
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:7", [handoffItem(), breachedItem()], [breachedItem()]))
      .mockResolvedValueOnce(openStream());

    render(<RootApplication />);

    expect(await screen.findByRole("heading", { name: "客服共享队列" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "待接手工单" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "SLA 违约升级" })).toBeInTheDocument();
    expect(await screen.findAllByText(HANDOFF_TICKET)).toHaveLength(1);
    expect(await screen.findAllByText(BREACHED_TICKET)).toHaveLength(2);
    expect(screen.queryByRole("combobox", { name: /角色/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/CUSTOMER_REQUESTED|AGENT_HUMAN_HANDOFF|调查摘要/)).not.toBeInTheDocument();
    expect(vi.mocked(globalThis.fetch).mock.calls[0]?.[0]).toBe("/api/demo/session");
    expect(vi.mocked(globalThis.fetch).mock.calls[1]?.[0]).toBe("/api/support/workbench/snapshot");
  });

  it("客户或审批人直接访问客服 URL 不会被自动提升为客服", async () => {
    globalThis.history.replaceState(null, "", "/support");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(null, { status: 401 }));

    render(<RootApplication />);

    expect(await screen.findByRole("heading", { name: "无权访问客服工作台" })).toBeInTheDocument();
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(globalThis.fetch)).not.toHaveBeenCalledWith("/api/support/workbench/snapshot", expect.anything());
  });

  it("序号缺口停止旧流并整体替换为新快照", async () => {
    let resolveRecovery: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:2", [handoffItem()], []))
      .mockResolvedValueOnce(sseResponse(eventBlock("support-workbench-v1:4", "QUEUE_TICKET_REMOVED", {
        ticketId: HANDOFF_TICKET,
      })))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveRecovery = resolve; }))
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench supportId="support-demo" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("当前队列可能过期");
    resolveRecovery?.(snapshotResponse("support-workbench-v1:8", [breachedItem()], [breachedItem()]));
    expect(await screen.findAllByText(BREACHED_TICKET)).toHaveLength(2);
    expect(screen.queryByText(HANDOFF_TICKET)).not.toBeInTheDocument();
    expect(vi.mocked(globalThis.fetch).mock.calls.filter(([input]) => input === "/api/support/workbench/snapshot"))
      .toHaveLength(2);
  });

  it("非法 payload 与 reset_required 都不会继续应用旧状态", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:2", [handoffItem()], []))
      .mockResolvedValueOnce(sseResponse(eventBlock("support-workbench-v1:3", "QUEUE_TICKET_UPSERTED", {
        ticketId: BREACHED_TICKET,
        lifecycleState: "INVESTIGATING",
        handlingMode: "AGENT",
        sharedEnteredAt: "2026-08-11T01:05:00Z",
        escalationEnteredAt: null,
        investigationSummary: "不得进入浏览器事件",
      })))
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:9", [], []))
      .mockResolvedValueOnce(new Response(JSON.stringify({ code: "SNAPSHOT_REQUIRED" }), { status: 409 }))
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:10", [breachedItem()], [breachedItem()]))
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench supportId="support-demo" />);

    expect(await screen.findAllByText(BREACHED_TICKET)).toHaveLength(2);
    expect(screen.queryByText("不得进入浏览器事件")).not.toBeInTheDocument();
    expect(vi.mocked(globalThis.fetch).mock.calls.filter(([input]) => input === "/api/support/workbench/snapshot"))
      .toHaveLength(3);
  });

  it("断线明确标记可能过期并提供保持焦点可操作的手动同步", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:2", [handoffItem()], []))
      .mockRejectedValueOnce(new TypeError("disconnected"))
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:3", [breachedItem()], [breachedItem()]))
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench supportId="support-demo" />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("可能过期");
    const refresh = screen.getByRole("button", { name: "重新同步队列" });
    refresh.focus();
    fireEvent.click(refresh);

    expect(await screen.findAllByText(BREACHED_TICKET)).toHaveLength(2);
    await waitFor(() => expect(refresh).not.toBeDisabled());
    expect(document.activeElement).toBe(refresh);
  });

  it("窄屏仍保留地标、标题层级和可读的队列列表", async () => {
    Object.defineProperty(globalThis, "innerWidth", { configurable: true, value: 360 });
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse("support-workbench-v1:1", [handoffItem()], []))
      .mockResolvedValueOnce(openStream());

    render(<SupportWorkbench supportId="support-demo" />);

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
  return new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(value));
      controller.close();
    },
  }), { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function openStream() {
  return new Response(new ReadableStream(), { status: 200, headers: { "Content-Type": "text/event-stream" } });
}
