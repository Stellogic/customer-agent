import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

vi.mock("./csrf", () => ({
  loadCsrfToken: async () => ({ token: "customer-csrf", headerName: "X-CSRF-TOKEN" }),
}));

describe("客户帮助中心", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it("提交后读取 CUSTOMER_PUBLIC 权威快照并显示受理结果", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ticketId: "ticket-13", replayed: false }), { status: 201 }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            view: "CUSTOMER_PUBLIC",
            schema: "customer-public-v1",
            cursor: "customer-public-v1:2",
            ticket: {
              id: "ticket-13",
              lifecycleState: "INVESTIGATING",
              handlingMode: "AGENT",
              agentGeneration: 1,
              firstRespondedAt: "2026-08-09T00:00:00Z",
            },
            messages: [
              { author: "CUSTOMER", body: "物流已经延迟多日", sentAt: "2026-08-09T00:00:00Z" },
              { author: "SUPPORT", body: "您的问题已受理", sentAt: "2026-08-09T00:00:00Z" },
            ],
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        streamResponse(
          publicEvent("customer-public-v1:3", "PUBLIC_MESSAGE_APPENDED", {
            author: "SUPPORT",
            body: "正在核对物流轨迹",
            sentAt: "2026-08-09T00:01:00Z",
          }) +
            publicEvent("customer-public-v1:4", "CUSTOMER_CLARIFICATION_REQUESTED", {
              lifecycleState: "WAITING_FOR_CUSTOMER",
              clarification: {
                id: "clarification-16",
                promptCode: "ORDER_CONFIRMATION_CODE",
                question: "请回复订单确认码（A 或 B）。",
              },
            }),
        ),
      );

    render(<App />);
    fireEvent.change(screen.getByLabelText("订单编号"), { target: { value: "ORDER-DELAY-001" } });
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: "物流已经延迟多日" } });
    fireEvent.click(screen.getByRole("button", { name: "提交物流延迟问题" }));

    expect(await screen.findByText("您的问题已受理")).toBeInTheDocument();
    expect(await screen.findByText("正在核对物流轨迹")).toBeInTheDocument();
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    expect(screen.getByLabelText("订单确认码")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const createHeaders = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(createHeaders.get("X-CSRF-TOKEN")).toBe("customer-csrf");
    expect(createHeaders.get("X-Synthetic-Customer-Id")).toBeNull();
    expect(fetchMock.mock.calls[1][0]).toBe("/api/customer/tickets/ticket-13");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/customer/tickets/ticket-13/events");
  });

  it("澄清恢复响应丢失时按稳定 resumeRequestId 查询而不创建第二次恢复", async () => {
    const ticketId = "16000000-0000-0000-0000-000000000001";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    let snapshotReads = 0;
    let replyPosts = 0;
    let statusQueries = 0;
    let submittedResumeId = "";
    let queriedResumeId = "";
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`)) {
        snapshotReads += 1;
        const waiting = snapshotReads === 1;
        return new Response(
          JSON.stringify({
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
            clarification: waiting
              ? {
                  id: "16000000-0000-0000-0000-000000000002",
                  promptCode: "ORDER_CONFIRMATION_CODE",
                  question: "为确认需要调查的订单，请回复订单确认码（A 或 B）。",
                }
              : null,
          }),
          { status: 200 },
        );
      }
      if (url.includes("/clarifications/") && init?.method === "POST") {
        replyPosts += 1;
        submittedResumeId = new Headers(init.headers).get("X-Resume-Request-Id") ?? "";
        throw new TypeError("response lost after commit");
      }
      if (url.includes("/clarification-resumes/")) {
        statusQueries += 1;
        queriedResumeId = url.split("/").at(-1) ?? "";
        return new Response(JSON.stringify({ status: "PENDING", replayed: true }), { status: 200 });
      }
      if (url.endsWith("/events")) {
        return openEventResponse();
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
    expect(queriedResumeId).toBe(submittedResumeId);
  });

  it("澄清恢复记录已找到但快照连接中断时保留稳定身份并提示手动刷新", async () => {
    const ticketId = "60000000-0000-0000-0000-000000000007";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    let snapshotReads = 0;
    let submittedResumeId = "";
    let queriedResumeId = "";
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`)) {
        snapshotReads += 1;
        if (snapshotReads === 1) return clarificationSnapshotResponse(ticketId);
        throw new TypeError("snapshot connection interrupted");
      }
      if (url.includes("/clarifications/") && init?.method === "POST") {
        submittedResumeId = new Headers(init.headers).get("X-Resume-Request-Id") ?? "";
        throw new TypeError("reply response lost");
      }
      if (url.includes("/clarification-resumes/")) {
        queriedResumeId = url.split("/").at(-1) ?? "";
        return new Response(JSON.stringify({ status: "PENDING", replayed: true }), { status: 200 });
      }
      if (url.endsWith("/events")) return openEventResponse();
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));

    expect(
      await screen.findByText("已找到原回复的恢复记录，但最新工单状态刷新失败，请手动刷新。"),
    ).toBeInTheDocument();
    expect(queriedResumeId).toBe(submittedResumeId);
  });

  it("澄清回复网络中断且恢复结果未知时重试复用两种稳定身份", async () => {
    const ticketId = "60000000-0000-0000-0000-000000000010";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    const submittedHeaders: Headers[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`))
        return clarificationSnapshotResponse(ticketId);
      if (url.includes("/clarifications/") && init?.method === "POST") {
        submittedHeaders.push(new Headers(init.headers));
        throw new TypeError("connection interrupted after sending request");
      }
      if (url.includes("/clarification-resumes/")) return new Response(null, { status: 404 });
      if (url.endsWith("/events")) return openEventResponse();
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));
    expect(
      await screen.findByText("回复状态暂时未知；请保留本页重试，稳定恢复身份不会启动第二次调查。"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));
    await waitFor(() => expect(submittedHeaders).toHaveLength(2));

    expectClarificationRequestIdsToMatch(submittedHeaders[0], submittedHeaders[1]);
  });

  it("澄清回复 422 显示输入校验错误且不用恢复端点，修正后使用新的幂等身份", async () => {
    const ticketId = "60000000-0000-0000-0000-000000000001";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    const replyHeaders: HeadersInit[] = [];
    let replyPosts = 0;
    let statusQueries = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`)) {
        return clarificationSnapshotResponse(ticketId);
      }
      if (url.includes("/clarifications/") && init?.method === "POST") {
        replyPosts += 1;
        replyHeaders.push(init.headers ?? {});
        return replyPosts === 1
          ? new Response(JSON.stringify({ detail: "answer is invalid" }), { status: 422 })
          : new Response(null, { status: 202 });
      }
      if (url.includes("/clarification-resumes/")) {
        statusQueries += 1;
        return new Response(null, { status: 404 });
      }
      if (url.endsWith("/events")) return openEventResponse();
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "无效输入" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));

    expect(await screen.findByText("回复内容未通过校验，请检查后重新提交。")).toBeInTheDocument();
    expect(statusQueries).toBe(0);

    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));
    await waitFor(() => expect(replyPosts).toBe(2));
    expect(new Headers(replyHeaders[1]).get("Idempotency-Key")).not.toBe(
      new Headers(replyHeaders[0]).get("Idempotency-Key"),
    );
    expect(new Headers(replyHeaders[1]).get("X-Resume-Request-Id")).not.toBe(
      new Headers(replyHeaders[0]).get("X-Resume-Request-Id"),
    );
  });

  it("澄清回复 409 刷新 Spring 权威快照并说明原澄清已失效", async () => {
    const ticketId = "60000000-0000-0000-0000-000000000003";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    let snapshotReads = 0;
    let statusQueries = 0;
    const submittedHeaders: Headers[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`)) {
        snapshotReads += 1;
        return snapshotReads === 1
          ? clarificationSnapshotResponse(ticketId)
          : clarificationSnapshotResponse(ticketId, "60000000-0000-0000-0000-000000000003", [
              message("工单状态已更新"),
            ]);
      }
      if (url.includes("/clarifications/") && init?.method === "POST") {
        submittedHeaders.push(new Headers(init.headers));
        return new Response(null, { status: submittedHeaders.length === 1 ? 409 : 202 });
      }
      if (url.includes("/clarification-resumes/")) {
        statusQueries += 1;
        return new Response(null, { status: 404 });
      }
      if (url.endsWith("/events")) return openEventResponse();
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));

    expect(
      await screen.findByText("该澄清已失效或工单状态已变化，已刷新最新状态。"),
    ).toBeInTheDocument();
    expect(await screen.findByText("工单状态已更新")).toBeInTheDocument();
    expect(snapshotReads).toBe(2);
    expect(statusQueries).toBe(0);
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "B" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));
    await waitFor(() => expect(submittedHeaders).toHaveLength(2));
    expectClarificationRequestIdsToDiffer(submittedHeaders[0], submittedHeaders[1]);
  });

  it("澄清回复 409 即使快照刷新失败也不把确定性拒绝送入恢复对账", async () => {
    const ticketId = "60000000-0000-0000-0000-000000000004";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    let snapshotReads = 0;
    let statusQueries = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`)) {
        snapshotReads += 1;
        if (snapshotReads === 1) return clarificationSnapshotResponse(ticketId);
        throw new TypeError("snapshot connection interrupted");
      }
      if (url.includes("/clarifications/") && init?.method === "POST") {
        return new Response(null, { status: 409 });
      }
      if (url.includes("/clarification-resumes/")) {
        statusQueries += 1;
        return new Response(null, { status: 404 });
      }
      if (url.endsWith("/events")) return openEventResponse();
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));

    expect(
      await screen.findByText("该澄清已失效或工单状态已变化；最新状态刷新失败，请手动刷新。"),
    ).toBeInTheDocument();
    expect(statusQueries).toBe(0);
  });

  it.each([
    [401, "60000000-0000-0000-0000-000000000041", "登录状态已失效，请重新登录后再试。"],
    [403, "60000000-0000-0000-0000-000000000043", "你当前无权回复这张工单。"],
    [404, "60000000-0000-0000-0000-000000000044", "未找到该工单或澄清请求，请返回工单列表确认。"],
  ])("澄清回复 %s 按授权或资源状态处理且不进入恢复对账", async (httpStatus, ticketId, text) => {
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    let statusQueries = 0;
    const submittedHeaders: Headers[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`))
        return clarificationSnapshotResponse(ticketId);
      if (url.includes("/clarifications/") && init?.method === "POST") {
        submittedHeaders.push(new Headers(init.headers));
        return new Response(null, { status: submittedHeaders.length === 1 ? httpStatus : 202 });
      }
      if (url.includes("/clarification-resumes/")) {
        statusQueries += 1;
        return new Response(null, { status: 404 });
      }
      if (url.endsWith("/events")) return openEventResponse();
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));

    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(statusQueries).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));
    await waitFor(() => expect(submittedHeaders).toHaveLength(2));
    expectClarificationRequestIdsToDiffer(submittedHeaders[0], submittedHeaders[1]);
  });

  it("澄清回复 5xx 使用提交时的稳定 resumeRequestId 对账", async () => {
    const ticketId = "60000000-0000-0000-0000-000000000005";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    let submittedResumeId = "";
    let queriedResumeId = "";
    const submittedHeaders: Headers[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`))
        return clarificationSnapshotResponse(ticketId);
      if (url.includes("/clarifications/") && init?.method === "POST") {
        const headers = new Headers(init.headers);
        submittedHeaders.push(headers);
        submittedResumeId = headers.get("X-Resume-Request-Id") ?? "";
        return new Response(null, { status: 503 });
      }
      if (url.includes("/clarification-resumes/")) {
        queriedResumeId = url.split("/").at(-1) ?? "";
        return new Response(null, { status: 404 });
      }
      if (url.endsWith("/events")) return openEventResponse();
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));

    expect(
      await screen.findByText("回复状态暂时未知；请保留本页重试，稳定恢复身份不会启动第二次调查。"),
    ).toBeInTheDocument();
    expect(queriedResumeId).toBe(submittedResumeId);
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));
    await waitFor(() => expect(submittedHeaders).toHaveLength(2));
    expectClarificationRequestIdsToMatch(submittedHeaders[0], submittedHeaders[1]);
  });

  it("澄清回复成功后清理本次幂等身份", async () => {
    const ticketId = "60000000-0000-0000-0000-000000000006";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    const submittedHeaders: Headers[] = [];
    let snapshotReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`)) {
        snapshotReads += 1;
        return clarificationSnapshotResponse(
          ticketId,
          snapshotReads === 1
            ? "60000000-0000-0000-0000-000000000002"
            : "60000000-0000-0000-0000-000000000008",
        );
      }
      if (url.includes("/clarifications/") && init?.method === "POST") {
        submittedHeaders.push(new Headers(init.headers));
        return new Response(null, { status: 202 });
      }
      if (url.endsWith("/events")) return openEventResponse();
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));
    await waitFor(() => expect(snapshotReads).toBe(2));
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "B" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));
    await waitFor(() => expect(submittedHeaders).toHaveLength(2));

    expect(submittedHeaders[1].get("Idempotency-Key")).not.toBe(
      submittedHeaders[0].get("Idempotency-Key"),
    );
    expect(submittedHeaders[1].get("X-Resume-Request-Id")).not.toBe(
      submittedHeaders[0].get("X-Resume-Request-Id"),
    );
  });

  it("澄清回复已成功但快照刷新失败时不进入 resume 对账", async () => {
    const ticketId = "60000000-0000-0000-0000-000000000009";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    let snapshotReads = 0;
    let statusQueries = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${ticketId}`)) {
        snapshotReads += 1;
        if (snapshotReads === 1) return clarificationSnapshotResponse(ticketId);
        throw new TypeError("snapshot connection interrupted");
      }
      if (url.includes("/clarifications/") && init?.method === "POST") {
        return new Response(null, { status: 202 });
      }
      if (url.includes("/clarification-resumes/")) {
        statusQueries += 1;
        return new Response(null, { status: 404 });
      }
      if (url.endsWith("/events")) return openEventResponse();
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("订单确认码"), { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "回复并继续调查" }));

    expect(
      await screen.findByText("回复已提交，但最新工单状态刷新失败，请手动刷新。"),
    ).toBeInTheDocument();
    expect(statusQueries).toBe(0);
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
        return new Response(
          JSON.stringify({
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
            messages: handedOff
              ? [
                  {
                    author: "SUPPORT",
                    body: "已按您的要求转由客服继续处理。客服将在此工单中与您联系。",
                    sentAt: "2026-08-09T00:01:00Z",
                  },
                ]
              : [],
            clarification: handedOff
              ? null
              : {
                  id: "18000000-0000-0000-0000-000000000002",
                  promptCode: "ORDER_CONFIRMATION_CODE",
                  question: "请回复订单确认码（A 或 B）。",
                },
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/human-handoff") && init?.method === "POST") {
        handoffPosts += 1;
        throw new TypeError("response lost after commit");
      }
      if (url.includes("/human-handoff-requests/")) {
        statusQueries += 1;
        return new Response(JSON.stringify({ handlingMode: "HUMAN", replayed: true }), {
          status: 200,
        });
      }
      if (url.endsWith("/events")) {
        return openEventResponse();
      }
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByRole("button", { name: "转人工处理" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "转人工处理" }));
    fireEvent.click(screen.getByRole("button", { name: "正在提交…" }));

    expect(await screen.findByText("人工处理中")).toBeInTheDocument();
    expect(
      screen.getByText("已按您的要求转由客服继续处理。客服将在此工单中与您联系。"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("订单确认码")).not.toBeInTheDocument();
    expect(handoffPosts).toBe(1);
    expect(statusQueries).toBe(1);
    expect(snapshotReads).toBe(2);
  });

  it("转人工后忽略旧代次迟到的 Agent 公开消息", async () => {
    const ticketId = "18000000-0000-0000-0000-000000000003";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
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
            messages: [
              {
                author: "SUPPORT",
                body: "已按您的要求转由客服继续处理。客服将在此工单中与您联系。",
                sentAt: "2026-08-09T00:01:00Z",
              },
            ],
            clarification: null,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        streamResponse(
          publicEvent("customer-public-v1:7", "PUBLIC_MESSAGE_APPENDED", {
            author: "AGENT",
            body: "不应展示的旧代次结论",
            sentAt: "2026-08-09T00:02:00Z",
          }),
        ),
      );

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
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent("customer-public-v1:2", "PUBLIC_MESSAGE_APPENDED", message("old")),
          publicEvent("customer-public-v1:3", "PUBLIC_MESSAGE_APPENDED", message("严格下一条")),
          publicEvent("customer-public-v1:3", "PUBLIC_MESSAGE_APPENDED", message("duplicate")),
        ]),
      );

    render(<App />);

    expect(await screen.findByText("严格下一条")).toBeInTheDocument();
    expect(screen.queryByText("old")).not.toBeInTheDocument();
    expect(screen.queryByText("duplicate")).not.toBeInTheDocument();
  });

  it("按关闭等待期事件更新为最终关闭", async () => {
    const ticketId = "28000000-0000-0000-0000-000000000001";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            view: "CUSTOMER_PUBLIC",
            schema: "customer-public-v1",
            cursor: "customer-public-v1:4",
            ticket: {
              id: ticketId,
              lifecycleState: "RESOLVED",
              handlingMode: "HUMAN",
              agentGeneration: 1,
              firstRespondedAt: "2026-08-09T00:00:00Z",
            },
            messages: [],
            clarification: null,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent("customer-public-v1:5", "TICKET_CLOSED", { lifecycleState: "CLOSED" }),
        ]),
      );

    render(<App />);

    expect(await screen.findByText("已关闭")).toBeInTheDocument();
  });

  it("按等待期内同一问题回复事件更新为调查中", async () => {
    const ticketId = "28000000-0000-0000-0000-000000000002";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            view: "CUSTOMER_PUBLIC",
            schema: "customer-public-v1",
            cursor: "customer-public-v1:4",
            ticket: {
              id: ticketId,
              lifecycleState: "RESOLVED",
              handlingMode: "AGENT",
              agentGeneration: 1,
              firstRespondedAt: "2026-08-09T00:00:00Z",
            },
            messages: [],
            clarification: null,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent("customer-public-v1:5", "TICKET_REOPENED", {
            lifecycleState: "INVESTIGATING",
          }),
        ]),
      );

    render(<App />);

    expect(await screen.findByText("调查中")).toBeInTheDocument();
  });

  it("已解决工单可从客户界面重开或进入关联新工单", async () => {
    const originalId = "28000000-0000-0000-0000-000000000003";
    const linkedId = "28000000-0000-0000-0000-000000000004";
    globalThis.history.replaceState(null, "", `/?ticket=${originalId}`);
    let submittedBody = "";
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(`/api/customer/tickets/${originalId}`)) {
        return new Response(
          JSON.stringify({
            view: "CUSTOMER_PUBLIC",
            schema: "customer-public-v1",
            cursor: "customer-public-v1:4",
            ticket: {
              id: originalId,
              lifecycleState: "RESOLVED",
              handlingMode: "AGENT",
              agentGeneration: 1,
              firstRespondedAt: "2026-08-09T00:00:00Z",
            },
            messages: [],
            clarification: null,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith(`/api/customer/tickets/${originalId}/replies`) && init?.method === "POST") {
        submittedBody = String(init.body);
        return new Response(
          JSON.stringify({ ticketId: linkedId, outcome: "LINKED_TICKET_CREATED" }),
          { status: 201 },
        );
      }
      if (url.endsWith(`/api/customer/tickets/${linkedId}`)) {
        return new Response(
          JSON.stringify({
            view: "CUSTOMER_PUBLIC",
            schema: "customer-public-v1",
            cursor: "customer-public-v1:2",
            ticket: {
              id: linkedId,
              lifecycleState: "INVESTIGATING",
              handlingMode: "HUMAN",
              agentGeneration: 0,
              firstRespondedAt: "2026-08-09T00:01:00Z",
            },
            messages: [],
            clarification: null,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/events")) {
        return openEventResponse();
      }
      throw new Error(`unexpected request: ${url}`);
    });

    render(<App />);
    expect(await screen.findByRole("button", { name: "发送回复" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("回复订单编号"), {
      target: { value: "ORDER-INTAKE-ONLY" },
    });
    fireEvent.change(screen.getByLabelText("回复问题类型"), { target: { value: "OTHER" } });
    fireEvent.change(screen.getByLabelText("工单回复"), {
      target: { value: "同一订单的另一个问题" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送回复" }));

    expect(await screen.findByText(linkedId)).toBeInTheDocument();
    expect(JSON.parse(submittedBody)).toEqual({
      orderReference: "ORDER-INTAKE-ONLY",
      issueKind: "OTHER",
      message: "同一订单的另一个问题",
    });
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
        init?.signal?.addEventListener("abort", () => {
          aborted = true;
        });
        streamReads += 1;
        return streamReads === 1 ? firstStream : openEventResponse();
      }
      const snapshotReads = vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([value]) => !String(value).endsWith("/events")).length;
      return snapshotResponse(
        ticketId,
        snapshotReads === 1 ? "customer-public-v1:2" : "customer-public-v1:8",
        snapshotReads === 1 ? [message("旧快照")] : [message("恢复后权威快照")],
      );
    });

    render(<App />);

    expect(await screen.findByText("恢复后权威快照")).toBeInTheDocument();
    expect(screen.queryByText("旧快照")).not.toBeInTheDocument();
    expect(screen.queryByText("不应拼接的缺口消息")).not.toBeInTheDocument();
    expect(aborted).toBe(true);
    expect(screen.queryByText(/当前内容可能过期/)).not.toBeInTheDocument();
  });

  it("未知事件不进入页面并触发快照恢复", async () => {
    const ticketId = "25000000-0000-0000-0000-000000000003";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        snapshotResponse(ticketId, "customer-public-v1:2", [message("初始快照")]),
      )
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent("customer-public-v1:3", "UNKNOWN_AGENT_EVENT", { value: "ignored" }),
        ]),
      )
      .mockResolvedValueOnce(
        snapshotResponse(ticketId, "customer-public-v1:4", [message("安全快照")]),
      )
      .mockResolvedValueOnce(eventResponse([]));

    render(<App />);

    expect(await screen.findByText("安全快照")).toBeInTheDocument();
    expect(screen.queryByText("ignored")).not.toBeInTheDocument();
  });

  it("已知事件含内部字段时也拒绝 payload 并从快照恢复", async () => {
    const ticketId = "25000000-0000-0000-0000-000000000006";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        snapshotResponse(ticketId, "customer-public-v1:2", [message("初始快照")]),
      )
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent("customer-public-v1:3", "PUBLIC_MESSAGE_APPENDED", {
            ...message("不应展示的消息"),
            reasoning: "secret",
          }),
        ]),
      )
      .mockResolvedValueOnce(
        snapshotResponse(ticketId, "customer-public-v1:4", [message("非法字段后安全快照")]),
      )
      .mockResolvedValueOnce(openEventResponse());

    render(<App />);

    expect(await screen.findByText("非法字段后安全快照")).toBeInTheDocument();
    expect(screen.queryByText("不应展示的消息")).not.toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("在 AGENT 模式下也用公开 generation fence 忽略旧代次迟到事件", async () => {
    const ticketId = "25000000-0000-0000-0000-000000000004";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse(ticketId, "customer-public-v1:2", []))
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent("customer-public-v1:3", "PUBLIC_MESSAGE_APPENDED", message("旧代次消息"), 0),
          publicEvent(
            "customer-public-v1:4",
            "PUBLIC_MESSAGE_APPENDED",
            message("当前代次消息"),
            1,
          ),
        ]),
      );

    render(<App />);

    expect(await screen.findByText("当前代次消息")).toBeInTheDocument();
    expect(screen.queryByText("旧代次消息")).not.toBeInTheDocument();
  });

  it("窄屏下仍可读取会话状态并使用主要操作", async () => {
    const ticketId = "25000000-0000-0000-0000-000000000005";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    Object.defineProperty(globalThis, "innerWidth", { configurable: true, value: 375 });
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        snapshotResponse(ticketId, "customer-public-v1:2", [message("窄屏公开会话")]),
      )
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

function snapshotResponse(
  ticketId: string,
  cursor: string,
  messages: ReturnType<typeof message>[],
) {
  return new Response(
    JSON.stringify({
      view: "CUSTOMER_PUBLIC",
      schema: "customer-public-v1",
      cursor,
      ticket: {
        id: ticketId,
        lifecycleState: "INVESTIGATING",
        handlingMode: "AGENT",
        agentGeneration: 1,
        firstRespondedAt: "2026-08-09T00:00:00Z",
      },
      messages,
      clarification: null,
    }),
    { status: 200 },
  );
}

function clarificationSnapshotResponse(
  ticketId: string,
  clarificationId = "60000000-0000-0000-0000-000000000002",
  messages: ReturnType<typeof message>[] = [],
) {
  return new Response(
    JSON.stringify({
      view: "CUSTOMER_PUBLIC",
      schema: "customer-public-v1",
      cursor: "customer-public-v1:4",
      ticket: {
        id: ticketId,
        lifecycleState: "WAITING_FOR_CUSTOMER",
        handlingMode: "AGENT",
        agentGeneration: 1,
        firstRespondedAt: "2026-08-09T00:00:00Z",
      },
      messages,
      clarification: {
        id: clarificationId,
        promptCode: "ORDER_CONFIRMATION_CODE",
        question: "为确认需要调查的订单，请回复订单确认码（A 或 B）。",
      },
    }),
    { status: 200 },
  );
}

function expectClarificationRequestIdsToDiffer(first: Headers, second: Headers) {
  expect(second.get("Idempotency-Key")).not.toBe(first.get("Idempotency-Key"));
  expect(second.get("X-Resume-Request-Id")).not.toBe(first.get("X-Resume-Request-Id"));
}

function expectClarificationRequestIdsToMatch(first: Headers, second: Headers) {
  expect(second.get("Idempotency-Key")).toBe(first.get("Idempotency-Key"));
  expect(second.get("X-Resume-Request-Id")).toBe(first.get("X-Resume-Request-Id"));
}

function publicEvent(id: string, type: string, payload: unknown, generation = 1) {
  return `id:${id}\nevent:${type}\ndata:${JSON.stringify({ view: "CUSTOMER_PUBLIC", schema: "customer-public-v1", generation, payload })}\n\n`;
}

function eventResponse(events: string[]) {
  return streamResponse(events.join(""));
}

function streamResponse(value: string) {
  return new Response(
    new ReadableStream({
      start(controller) {
        if (value) controller.enqueue(new TextEncoder().encode(value));
      },
    }),
    {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    },
  );
}

function openEventResponse() {
  return new Response(new ReadableStream({ start() {} }), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}
