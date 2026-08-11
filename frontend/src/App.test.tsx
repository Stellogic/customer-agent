import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

describe("客户帮助中心", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it("提交后读取 CUSTOMER_PUBLIC 权威快照并显示受理结果", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ ticketId: "ticket-13", replayed: false }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        view: "CUSTOMER_PUBLIC",
        schema: "customer-public-v1",
        cursor: "customer-public-v1:2",
        ticket: { id: "ticket-13", lifecycleState: "INVESTIGATING", handlingMode: "AGENT", agentGeneration: 1, firstRespondedAt: "2026-08-09T00:00:00Z" },
        messages: [
          { author: "CUSTOMER", body: "物流已经延迟多日", sentAt: "2026-08-09T00:00:00Z" },
          { author: "SUPPORT", body: "您的问题已受理", sentAt: "2026-08-09T00:00:00Z" },
        ],
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(
        publicEvent("customer-public-v1:3", "PUBLIC_MESSAGE_APPENDED", { author: "SUPPORT", body: "正在核对物流轨迹", sentAt: "2026-08-09T00:01:00Z" }) +
        publicEvent("customer-public-v1:4", "CUSTOMER_CLARIFICATION_REQUESTED", { lifecycleState: "WAITING_FOR_CUSTOMER", clarification: { id: "clarification-16", promptCode: "ORDER_CONFIRMATION_CODE", question: "请回复订单确认码（A 或 B）。" } }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ));

    render(<App />);
    fireEvent.change(screen.getByLabelText("订单编号"), { target: { value: "ORDER-DELAY-001" } });
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: "物流已经延迟多日" } });
    fireEvent.click(screen.getByRole("button", { name: "提交物流延迟问题" }));

    expect(await screen.findByText("您的问题已受理")).toBeInTheDocument();
    expect(await screen.findByText("正在核对物流轨迹")).toBeInTheDocument();
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    expect(screen.getByLabelText("订单确认码")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[1][0]).toBe("/api/customer/tickets/ticket-13");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/customer/tickets/ticket-13/events");
  });

  it("澄清恢复响应丢失时按稳定 resumeRequestId 查询而不创建第二次恢复", async () => {
    const ticketId = "16000000-0000-0000-0000-000000000001";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    let snapshotReads = 0;
    let replyPosts = 0;
    let statusQueries = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`)) {
        snapshotReads += 1;
        const waiting = snapshotReads === 1;
        return new Response(JSON.stringify({
          view: "CUSTOMER_PUBLIC",
          schema: "customer-public-v1",
          cursor: waiting ? "customer-public-v1:4" : "customer-public-v1:6",
          ticket: {
            id: ticketId,
            lifecycleState: waiting ? "WAITING_FOR_CUSTOMER" : "INVESTIGATING",
            handlingMode: "AGENT",
            agentGeneration: 1,
            firstRespondedAt: "2026-08-09T00:00:00Z",
          },
          messages: [],
          clarification: waiting ? {
            id: "16000000-0000-0000-0000-000000000002",
            promptCode: "ORDER_CONFIRMATION_CODE",
            question: "为确认需要调查的订单，请回复订单确认码（A 或 B）。",
          } : null,
        }), { status: 200 });
      }
      if (url.includes("/clarifications/") && init?.method === "POST") {
        replyPosts += 1;
        throw new TypeError("response lost after commit");
      }
      if (url.includes("/clarification-resumes/")) {
        statusQueries += 1;
        return new Response(JSON.stringify({ status: "PENDING", replayed: true }), { status: 200 });
      }
      if (url.endsWith("/events")) {
        return new Response("", { status: 200, headers: { "Content-Type": "text/event-stream" } });
      }
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));

    expect(await screen.findByText("调查中")).toBeInTheDocument();
    expect(replyPosts).toBe(1);
    expect(statusQueries).toBe(1);
    expect(snapshotReads).toBe(2);
  });

  it("转人工响应丢失时按稳定请求身份对账并从权威快照恢复", async () => {
    const ticketId = "18000000-0000-0000-0000-000000000001";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    let snapshotReads = 0;
    let handoffPosts = 0;
    let statusQueries = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`)) {
        snapshotReads += 1;
        const handedOff = snapshotReads > 1;
        return new Response(JSON.stringify({
          view: "CUSTOMER_PUBLIC",
          schema: "customer-public-v1",
          cursor: handedOff ? "customer-public-v1:6" : "customer-public-v1:4",
          ticket: {
            id: ticketId,
            lifecycleState: "WAITING_FOR_CUSTOMER",
            handlingMode: handedOff ? "HUMAN" : "AGENT",
            agentGeneration: 1,
            firstRespondedAt: "2026-08-09T00:00:00Z",
          },
          messages: handedOff ? [{
            author: "SUPPORT",
            body: "已按您的要求转由客服继续处理。客服将在此工单中与您联系。",
            sentAt: "2026-08-09T00:01:00Z",
          }] : [],
          clarification: handedOff ? null : {
            id: "18000000-0000-0000-0000-000000000002",
            promptCode: "ORDER_CONFIRMATION_CODE",
            question: "请回复订单确认码（A 或 B）。",
          },
        }), { status: 200 });
      }
      if (url.endsWith("/human-handoff") && init?.method === "POST") {
        handoffPosts += 1;
        throw new TypeError("response lost after commit");
      }
      if (url.includes("/human-handoff-requests/")) {
        statusQueries += 1;
        return new Response(JSON.stringify({ handlingMode: "HUMAN", replayed: true }), { status: 200 });
      }
      if (url.endsWith("/events")) {
        return new Response("", { status: 200, headers: { "Content-Type": "text/event-stream" } });
      }
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByRole("button", { name: "转人工处理" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "转人工处理" }));
    fireEvent.click(screen.getByRole("button", { name: "正在提交…" }));

    expect(await screen.findByText("人工处理中")).toBeInTheDocument();
    expect(screen.getByText("已按您的要求转由客服继续处理。客服将在此工单中与您联系。")).toBeInTheDocument();
    expect(screen.queryByLabelText("订单确认码")).not.toBeInTheDocument();
    expect(handoffPosts).toBe(1);
    expect(statusQueries).toBe(1);
    expect(snapshotReads).toBe(2);
  });

  it("转人工后忽略旧代次迟到的 Agent 公开消息", async () => {
    const ticketId = "18000000-0000-0000-0000-000000000003";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({
      view: "CUSTOMER_PUBLIC",
      schema: "customer-public-v1",
      cursor: "customer-public-v1:6",
      ticket: {
        id: ticketId,
        lifecycleState: "INVESTIGATING",
        handlingMode: "HUMAN",
        agentGeneration: 1,
        firstRespondedAt: "2026-08-09T00:00:00Z",
      },
      messages: [{
        author: "SUPPORT",
        body: "已按您的要求转由客服继续处理。客服将在此工单中与您联系。",
        sentAt: "2026-08-09T00:01:00Z",
      }],
      clarification: null,
    }), { status: 200 })).mockResolvedValueOnce(new Response(
      publicEvent("customer-public-v1:7", "PUBLIC_MESSAGE_APPENDED", { author: "AGENT", body: "不应展示的旧代次结论", sentAt: "2026-08-09T00:02:00Z" }),
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    ));

    render(<App />);

    expect(await screen.findByText("人工处理中")).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("不应展示的旧代次结论")).not.toBeInTheDocument();
  });

  it("忽略重复和旧序号，只按严格下一序号应用增量", async () => {
    const ticketId = "25000000-0000-0000-0000-000000000001";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse(ticketId, "customer-public-v1:2", []))
      .mockResolvedValueOnce(eventResponse([
        publicEvent("customer-public-v1:2", "PUBLIC_MESSAGE_APPENDED", message("old")),
        publicEvent("customer-public-v1:3", "PUBLIC_MESSAGE_APPENDED", message("严格下一条")),
        publicEvent("customer-public-v1:3", "PUBLIC_MESSAGE_APPENDED", message("duplicate")),
      ]));

    render(<App />);

    expect(await screen.findByText("严格下一条")).toBeInTheDocument();
    expect(screen.queryByText("old")).not.toBeInTheDocument();
    expect(screen.queryByText("duplicate")).not.toBeInTheDocument();
  });

  it("序号缺口时关闭旧流并整体替换为新的权威快照", async () => {
    const ticketId = "25000000-0000-0000-0000-000000000002";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    let aborted = false;
    const firstStream = eventResponse([
      publicEvent("customer-public-v1:4", "PUBLIC_MESSAGE_APPENDED", message("不应拼接的缺口消息")),
    ]);
    let streamReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/events")) {
        init?.signal?.addEventListener("abort", () => { aborted = true; });
        streamReads += 1;
        return streamReads === 1 ? firstStream : openEventResponse();
      }
      const snapshotReads = vi.mocked(globalThis.fetch).mock.calls.filter(([value]) => !String(value).endsWith("/events")).length;
      return snapshotResponse(ticketId, snapshotReads === 1 ? "customer-public-v1:2" : "customer-public-v1:8",
        snapshotReads === 1 ? [message("旧快照")] : [message("恢复后权威快照")]);
    });

    render(<App />);

    expect(await screen.findByText("恢复后权威快照")).toBeInTheDocument();
    expect(screen.queryByText("旧快照")).not.toBeInTheDocument();
    expect(screen.queryByText("不应拼接的缺口消息")).not.toBeInTheDocument();
    expect(aborted).toBe(true);
    expect(screen.queryByText(/当前内容可能过期/)).not.toBeInTheDocument();
  });

  it("未知事件或含内部字段的 payload 不进入页面并触发快照恢复", async () => {
    const ticketId = "25000000-0000-0000-0000-000000000003";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse(ticketId, "customer-public-v1:2", [message("初始快照")]))
      .mockResolvedValueOnce(eventResponse([
        publicEvent("customer-public-v1:3", "MODEL_REASONING", { reasoning: "secret" }),
      ]))
      .mockResolvedValueOnce(snapshotResponse(ticketId, "customer-public-v1:4", [message("安全快照")]))
      .mockResolvedValueOnce(eventResponse([]));

    render(<App />);

    expect(await screen.findByText("安全快照")).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("在 AGENT 模式下也用公开 generation fence 忽略旧代次迟到事件", async () => {
    const ticketId = "25000000-0000-0000-0000-000000000004";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse(ticketId, "customer-public-v1:2", []))
      .mockResolvedValueOnce(eventResponse([
        publicEvent("customer-public-v1:3", "PUBLIC_MESSAGE_APPENDED", message("旧代次消息"), 0),
        publicEvent("customer-public-v1:4", "PUBLIC_MESSAGE_APPENDED", message("当前代次消息"), 1),
      ]));

    render(<App />);

    expect(await screen.findByText("当前代次消息")).toBeInTheDocument();
    expect(screen.queryByText("旧代次消息")).not.toBeInTheDocument();
  });

  it("窄屏下仍可读取会话状态并使用主要操作", async () => {
    const ticketId = "25000000-0000-0000-0000-000000000005";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    Object.defineProperty(globalThis, "innerWidth", { configurable: true, value: 375 });
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse(ticketId, "customer-public-v1:2", [message("窄屏公开会话")]))
      .mockResolvedValueOnce(eventResponse([]));

    render(<App />);

    expect(await screen.findByText("窄屏公开会话")).toBeInTheDocument();
    expect(screen.getByText("调查中")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "转人工处理" })).toBeInTheDocument();
  });
});

function message(body: string) {
  return { author: "SUPPORT", body, sentAt: "2026-08-09T00:01:00Z" };
}

function snapshotResponse(ticketId: string, cursor: string, messages: ReturnType<typeof message>[]) {
  return new Response(JSON.stringify({
    view: "CUSTOMER_PUBLIC",
    schema: "customer-public-v1",
    cursor,
    ticket: { id: ticketId, lifecycleState: "INVESTIGATING", handlingMode: "AGENT", agentGeneration: 1, firstRespondedAt: "2026-08-09T00:00:00Z" },
    messages,
    clarification: null,
  }), { status: 200 });
}

function publicEvent(id: string, type: string, payload: unknown, generation = 1) {
  return `id:${id}\nevent:${type}\ndata:${JSON.stringify({ view: "CUSTOMER_PUBLIC", schema: "customer-public-v1", generation, payload })}\n\n`;
}

function eventResponse(events: string[]) {
  return new Response(events.join(""), { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function openEventResponse() {
  return new Response(new ReadableStream({ start() {} }), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}
