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
    globalThis.sessionStorage.clear();
    globalThis.history.replaceState(null, "", "/");
  });

  it("自然语言受理确认后读取 PUBLIC_CONVERSATION v2 权威快照", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            schema: "customer-intake-v1",
            intakeId: "intake-152",
            status: "READY_TO_CONFIRM",
            candidateOrder: { reference: "ORDER-DELAY-001", summary: "配送中的合成订单" },
            issue: { kind: "LOGISTICS_DELAY", summary: "物流已经延迟多日" },
            assistantMessage: "请确认我的理解。",
            ticketId: null,
            confirmed: false,
            replayed: false,
          }),
          { status: 201 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            schema: "customer-intake-v1",
            intakeId: "intake-152",
            status: "CONFIRMED",
            candidateOrder: { reference: "ORDER-DELAY-001", summary: "配送中的合成订单" },
            issue: { kind: "LOGISTICS_DELAY", summary: "物流已经延迟多日" },
            assistantMessage: "已确认，客服工单正在独立处理。",
            ticketId: "ticket-13",
            confirmed: true,
            replayed: false,
          }),
          { status: 201 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            view: "PUBLIC_CONVERSATION",
            schema: "public-conversation-v2",
            cursor: "public-conversation-v2:2",
            ticket: {
              id: "ticket-13",
              lifecycleState: "INVESTIGATING",
              handlingMode: "AGENT",
              agentGeneration: 1,
            },
            messages: [
              { author: "CUSTOMER", body: "物流已经延迟多日", sentAt: "2026-08-09T00:00:00Z" },
              { author: "SUPPORT", body: "您的问题已受理", sentAt: "2026-08-09T00:00:00Z" },
            ],
            clarification: null,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        streamResponse(
          publicEvent("public-conversation-v2:3", "PUBLIC_MESSAGE_APPENDED", {
            author: "SUPPORT",
            body: "正在核对物流轨迹",
            sentAt: "2026-08-09T00:01:00Z",
          }) +
            publicEvent("public-conversation-v2:4", "CUSTOMER_CLARIFICATION_REQUESTED", {
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

    expect(await screen.findByRole("heading", { name: "请确认我的理解" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("您的问题已受理")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认，就是这个问题" }));

    expect(await screen.findByText("您的问题已受理")).toBeInTheDocument();
    expect(await screen.findByText("正在核对物流轨迹")).toBeInTheDocument();
    expect(await screen.findByText("等待你的回复")).toBeInTheDocument();
    expect(screen.getByLabelText("订单确认码")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    const createHeaders = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(createHeaders.get("X-CSRF-TOKEN")).toBe("customer-csrf");
    expect(createHeaders.get("X-Synthetic-Customer-Id")).toBeNull();
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      schema: "customer-intake-v2",
      message: "订单 ORDER-DELAY-001 的物流延迟问题：物流已经延迟多日",
    });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/customer/v2/intakes/intake-152/messages");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/customer/v2/tickets/ticket-13");
    expect(fetchMock.mock.calls[3][0]).toBe("/api/customer/v2/tickets/ticket-13/events");
  });

  it("不选择订单或问题类型即可看到候选、问题理解与确认边界", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          schema: "customer-intake-v1",
          intakeId: "intake-natural-language",
          status: "READY_TO_CONFIRM",
          candidateOrder: { reference: "ORDER-DELAY-001", summary: "配送中的合成订单" },
          issue: { kind: "LOGISTICS_DELAY", summary: "包裹好几天没有动了" },
          assistantMessage: "我理解为这笔订单的物流延迟问题，请确认是否正确。",
          ticketId: null,
          confirmed: false,
          replayed: false,
        }),
        { status: 201 },
      ),
    );

    render(<App />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "包裹好几天没有动了" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交物流延迟问题" }));

    expect(await screen.findByRole("heading", { name: "请确认我的理解" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "订单候选" })).toHaveTextContent("ORDER-DELAY-001");
    expect(screen.getByRole("article", { name: "问题理解" })).toHaveTextContent(
      "确认前不会创建正式工单",
    );
    expect(screen.getByRole("button", { name: "确认，就是这个问题" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      schema: "customer-intake-v2",
      message: "包裹好几天没有动了",
    });
  });

  it("一次展示同订单的多个拟建问题与原子创建数量", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            schema: "customer-intake-v2",
            intakeId: "intake-multi-153",
            status: "READY_TO_CONFIRM",
            candidateOrder: { reference: "ORDER-MULTI-001", summary: "配送中的合成订单" },
            issue: null,
            issues: [
              { kind: "PACKAGE_NOT_RECEIVED", summary: "包裹未收到" },
              { kind: "DUPLICATE_CHARGE", summary: "疑似重复扣款" },
            ],
            assistantMessage: "请确认；确认后将创建 2 张工单。",
            ticketId: null,
            ticketIds: [],
            sharedIntakeRecordId: null,
            expectedTicketCount: 2,
            confirmed: false,
            replayed: false,
          }),
          { status: 201 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            schema: "customer-intake-v2",
            intakeId: "intake-multi-153",
            status: "CONFIRMED",
            candidateOrder: { reference: "ORDER-MULTI-001", summary: "配送中的合成订单" },
            issue: null,
            issues: [
              { kind: "PACKAGE_NOT_RECEIVED", summary: "包裹未收到" },
              { kind: "DUPLICATE_CHARGE", summary: "疑似重复扣款" },
            ],
            assistantMessage: "已确认，2 张客服工单已原子创建并开始独立处理。",
            ticketId: null,
            ticketIds: ["ticket-153-a", "ticket-153-b"],
            sharedIntakeRecordId: "shared-153",
            expectedTicketCount: 2,
            confirmed: true,
            replayed: false,
          }),
          { status: 201 },
        ),
      );

    render(<App />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "包裹未收到而且重复扣款" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交物流延迟问题" }));

    expect(await screen.findByRole("heading", { name: "请确认 2 个问题" })).toBeInTheDocument();
    expect(screen.getAllByRole("article", { name: /拟建工单/ })).toHaveLength(2);
    expect(screen.getByText("包裹未收到")).toBeInTheDocument();
    expect(screen.getByText("疑似重复扣款")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认并原子创建 2 张工单" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认并原子创建 2 张工单" }));
    expect(await screen.findByRole("heading", { name: "2 张工单已创建" })).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "已创建工单" }).querySelectorAll("button"),
    ).toHaveLength(2);
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
      if (url.endsWith(`/api/customer/v2/tickets/${ticketId}`)) {
        snapshotReads += 1;
        const waiting = snapshotReads === 1;
        return new Response(
          JSON.stringify({
            view: "PUBLIC_CONVERSATION",
            schema: "public-conversation-v2",
            cursor: waiting ? "public-conversation-v2:4" : "public-conversation-v2:6",
            ticket: {
              id: ticketId,
              lifecycleState: waiting ? "WAITING_FOR_CUSTOMER" : "INVESTIGATING",
              handlingMode: "AGENT",
              agentGeneration: 1,
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
      if (url.endsWith(`/api/customer/v2/tickets/${ticketId}`)) {
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
      if (url.endsWith(`/api/customer/v2/tickets/${ticketId}`))
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
      if (url.endsWith(`/api/customer/v2/tickets/${ticketId}`)) {
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
      if (url.endsWith(`/api/customer/v2/tickets/${ticketId}`)) {
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
      if (url.endsWith(`/api/customer/v2/tickets/${ticketId}`)) {
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
      if (url.endsWith(`/api/customer/v2/tickets/${ticketId}`))
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
      if (url.endsWith(`/api/customer/v2/tickets/${ticketId}`))
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
      if (url.endsWith(`/api/customer/v2/tickets/${ticketId}`)) {
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
      if (url.endsWith(`/api/customer/v2/tickets/${ticketId}`)) {
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
      if (url.endsWith(`/api/customer/v2/tickets/${ticketId}`)) {
        snapshotReads += 1;
        const handedOff = snapshotReads > 1;
        return new Response(
          JSON.stringify({
            view: "PUBLIC_CONVERSATION",
            schema: "public-conversation-v2",
            cursor: handedOff ? "public-conversation-v2:6" : "public-conversation-v2:4",
            ticket: {
              id: ticketId,
              lifecycleState: "WAITING_FOR_CUSTOMER",
              handlingMode: handedOff ? "HUMAN" : "AGENT",
              agentGeneration: 1,
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
    fireEvent.click(screen.getByRole("button", { name: "确认转人工" }));
    fireEvent.click(screen.getByRole("button", { name: "正在提交…" }));

    expect(await screen.findByText("人工客服处理中")).toBeInTheDocument();
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
            view: "PUBLIC_CONVERSATION",
            schema: "public-conversation-v2",
            cursor: "public-conversation-v2:6",
            ticket: {
              id: ticketId,
              lifecycleState: "INVESTIGATING",
              handlingMode: "HUMAN",
              agentGeneration: 1,
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
          publicEvent("public-conversation-v2:7", "PUBLIC_MESSAGE_APPENDED", {
            author: "AGENT",
            body: "不应展示的旧代次结论",
            sentAt: "2026-08-09T00:02:00Z",
          }),
        ),
      );

    render(<App />);

    expect(await screen.findByText("人工客服处理中")).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("不应展示的旧代次结论")).not.toBeInTheDocument();
  });

  it("忽略重复和旧序号，只按严格下一序号应用增量", async () => {
    const ticketId = "25000000-0000-0000-0000-000000000001";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(snapshotResponse(ticketId, "public-conversation-v2:2", []))
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent("public-conversation-v2:2", "PUBLIC_MESSAGE_APPENDED", message("old")),
          publicEvent("public-conversation-v2:3", "PUBLIC_MESSAGE_APPENDED", message("严格下一条")),
          publicEvent("public-conversation-v2:3", "PUBLIC_MESSAGE_APPENDED", message("duplicate")),
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
            view: "PUBLIC_CONVERSATION",
            schema: "public-conversation-v2",
            cursor: "public-conversation-v2:4",
            ticket: {
              id: ticketId,
              lifecycleState: "RESOLVED",
              handlingMode: "HUMAN",
              agentGeneration: 1,
            },
            messages: [],
            clarification: null,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent("public-conversation-v2:5", "TICKET_CLOSED", { lifecycleState: "CLOSED" }),
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
            view: "PUBLIC_CONVERSATION",
            schema: "public-conversation-v2",
            cursor: "public-conversation-v2:4",
            ticket: {
              id: ticketId,
              lifecycleState: "RESOLVED",
              handlingMode: "AGENT",
              agentGeneration: 1,
            },
            messages: [],
            clarification: null,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent("public-conversation-v2:5", "TICKET_REOPENED", {
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
      if (url.endsWith(`/api/customer/v2/tickets/${originalId}`)) {
        return new Response(
          JSON.stringify({
            view: "PUBLIC_CONVERSATION",
            schema: "public-conversation-v2",
            cursor: "public-conversation-v2:4",
            ticket: {
              id: originalId,
              lifecycleState: "RESOLVED",
              handlingMode: "AGENT",
              agentGeneration: 1,
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
      if (url.endsWith(`/api/customer/v2/tickets/${linkedId}`)) {
        return new Response(
          JSON.stringify({
            view: "PUBLIC_CONVERSATION",
            schema: "public-conversation-v2",
            cursor: "public-conversation-v2:2",
            ticket: {
              id: linkedId,
              lifecycleState: "INVESTIGATING",
              handlingMode: "HUMAN",
              agentGeneration: 0,
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
    expect(screen.queryByRole("button", { name: "转人工处理" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("回复订单编号"), {
      target: { value: "ORDER-INTAKE-ONLY" },
    });
    fireEvent.change(screen.getByLabelText("回复问题类型"), { target: { value: "OTHER" } });
    fireEvent.change(screen.getByLabelText("工单回复"), {
      target: { value: "同一订单的另一个问题" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送回复" }));

    expect(await screen.findByText("28000000…0004")).toBeInTheDocument();
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
      publicEvent(
        "public-conversation-v2:4",
        "PUBLIC_MESSAGE_APPENDED",
        message("不应拼接的缺口消息"),
      ),
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
        snapshotReads === 1 ? "public-conversation-v2:2" : "public-conversation-v2:8",
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
        snapshotResponse(ticketId, "public-conversation-v2:2", [message("初始快照")]),
      )
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent("public-conversation-v2:3", "UNKNOWN_AGENT_EVENT", { value: "ignored" }),
        ]),
      )
      .mockResolvedValueOnce(
        snapshotResponse(ticketId, "public-conversation-v2:4", [message("安全快照")]),
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
        snapshotResponse(ticketId, "public-conversation-v2:2", [message("初始快照")]),
      )
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent("public-conversation-v2:3", "PUBLIC_MESSAGE_APPENDED", {
            ...message("不应展示的消息"),
            reasoning: "secret",
          }),
        ]),
      )
      .mockResolvedValueOnce(
        snapshotResponse(ticketId, "public-conversation-v2:4", [message("非法字段后安全快照")]),
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
      .mockResolvedValueOnce(snapshotResponse(ticketId, "public-conversation-v2:2", []))
      .mockResolvedValueOnce(
        eventResponse([
          publicEvent(
            "public-conversation-v2:3",
            "PUBLIC_MESSAGE_APPENDED",
            message("旧代次消息"),
            0,
          ),
          publicEvent(
            "public-conversation-v2:4",
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
        snapshotResponse(ticketId, "public-conversation-v2:2", [message("窄屏公开会话")]),
      )
      .mockResolvedValueOnce(eventResponse([]));

    render(<App />);

    expect(await screen.findByText("窄屏公开会话")).toBeInTheDocument();
    expect(screen.getByText("调查中")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "转人工处理" })).toBeInTheDocument();
  });

  it.each([
    ["未知顶层字段", { internalTrace: "must-not-enter-product-contract" }],
    [
      "畸形澄清",
      {
        clarification: {
          id: "clarification-151",
          promptCode: "ORDER_CONFIRMATION_CODE",
          question: "请确认订单。",
          checkpoint: "must-not-enter-product-contract",
        },
      },
    ],
  ])("拒绝包含%s的 v2 权威快照", async (_scenario, override) => {
    const ticketId = "15100000-0000-0000-0000-000000000002";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          view: "PUBLIC_CONVERSATION",
          schema: "public-conversation-v2",
          cursor: "public-conversation-v2:2",
          ticket: {
            id: ticketId,
            lifecycleState: "INVESTIGATING",
            handlingMode: "AGENT",
            agentGeneration: 1,
          },
          messages: [],
          clarification: null,
          ...override,
        }),
        { status: 200 },
      ),
    );

    render(<App />);

    expect(
      await screen.findByText("暂时无法读取最新工单状态，我们会继续尝试从权威记录恢复。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("调查中")).not.toBeInTheDocument();
  });

  it.each([
    ["NEW", "AGENT", "已受理", "智能客服处理中"],
    ["INVESTIGATING", "AGENT", "调查中", "智能客服处理中"],
    ["WAITING_FOR_CUSTOMER", "AGENT", "等待你的回复", "智能客服处理中"],
    ["WAITING_FOR_EXTERNAL", "AGENT", "等待外部信息", "智能客服处理中"],
    ["RESOLVED", "HUMAN", "已解决", "人工客服处理中"],
    ["CLOSED", "HUMAN", "已关闭", "人工客服处理中"],
  ])("用客户可理解的文案同时呈现 %s 与 %s", async (lifecycle, mode, stateLabel, modeLabel) => {
    const ticketId = "98000000-0000-0000-0000-000000000001";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(ticketStateResponse(ticketId, lifecycle, mode))
      .mockResolvedValueOnce(openEventResponse());

    render(<App />);

    expect(await screen.findByText(stateLabel)).toBeInTheDocument();
    expect(screen.getByText(modeLabel)).toBeInTheDocument();
    expect(screen.queryByText(lifecycle)).not.toBeInTheDocument();
    expect(screen.queryByText(mode)).not.toBeInTheDocument();
  });

  it("稳定缩略展示工单 UUID，并通过明确操作复制完整值", async () => {
    const ticketId = "98000000-0000-0000-0000-000000000002";
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis.navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(ticketStateResponse(ticketId, "INVESTIGATING", "AGENT"))
      .mockResolvedValueOnce(openEventResponse());

    render(<App />);

    expect(await screen.findByText("98000000…0002")).toBeInTheDocument();
    expect(screen.queryByText(ticketId)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "复制完整工单编号" }));
    expect(writeText).toHaveBeenCalledWith(ticketId);
  });

  it("SSE 恢复失败时清除旧投影并保留权威重同步入口，不退回创建表单", async () => {
    const ticketId = "98000000-0000-0000-0000-000000000003";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        ticketStateResponse(ticketId, "INVESTIGATING", "AGENT", [message("即将过期的公开投影")]),
      )
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValueOnce(
        ticketStateResponse(ticketId, "INVESTIGATING", "AGENT", [message("恢复后的权威公开投影")]),
      )
      .mockResolvedValueOnce(openEventResponse());

    render(<App />);

    expect(await screen.findByText("正在重新同步工单")).toBeInTheDocument();
    expect(screen.queryByText("即将过期的公开投影")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交物流延迟问题" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "立即重试同步" }));
    expect(await screen.findByText("恢复后的权威公开投影")).toBeInTheDocument();
  });

  it("转人工结果未知时只提供权威结果查询，不提供普通重复提交路径", async () => {
    const ticketId = "98000000-0000-0000-0000-000000000004";
    globalThis.history.replaceState(null, "", `/?ticket=${ticketId}`);
    let handoffPosts = 0;
    let resultQueries = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === `/api/customer/v2/tickets/${ticketId}`) {
        return ticketStateResponse(ticketId, "INVESTIGATING", "AGENT");
      }
      if (path.endsWith("/events")) return openEventResponse();
      if (path.endsWith("/human-handoff") && init?.method === "POST") {
        handoffPosts += 1;
        throw new TypeError("response lost after commit");
      }
      if (path.includes("/human-handoff-requests/")) {
        resultQueries += 1;
        return new Response(null, { status: 404 });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    const firstRender = render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "转人工处理" }));
    expect(screen.getByRole("dialog", { name: "确认转人工处理" })).toBeInTheDocument();
    expect(handoffPosts).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "确认转人工" }));

    const queryButton = await screen.findByRole("button", { name: "查询转人工结果" });
    expect(screen.queryByRole("button", { name: "转人工处理" })).not.toBeInTheDocument();
    fireEvent.click(queryButton);
    await waitFor(() => expect(resultQueries).toBe(2));
    expect(handoffPosts).toBe(1);

    firstRender.unmount();
    render(<App />);
    expect(await screen.findByRole("button", { name: "查询转人工结果" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "转人工处理" })).not.toBeInTheDocument();
    expect(handoffPosts).toBe(1);
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
      view: "PUBLIC_CONVERSATION",
      schema: "public-conversation-v2",
      cursor,
      ticket: {
        id: ticketId,
        lifecycleState: "INVESTIGATING",
        handlingMode: "AGENT",
        agentGeneration: 1,
      },
      messages,
      clarification: null,
    }),
    { status: 200 },
  );
}

function ticketStateResponse(
  ticketId: string,
  lifecycleState: string,
  handlingMode: string,
  messages: ReturnType<typeof message>[] = [],
) {
  return new Response(
    JSON.stringify({
      view: "PUBLIC_CONVERSATION",
      schema: "public-conversation-v2",
      cursor: "public-conversation-v2:2",
      ticket: {
        id: ticketId,
        lifecycleState,
        handlingMode,
        agentGeneration: 1,
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
      view: "PUBLIC_CONVERSATION",
      schema: "public-conversation-v2",
      cursor: "public-conversation-v2:4",
      ticket: {
        id: ticketId,
        lifecycleState: "WAITING_FOR_CUSTOMER",
        handlingMode: "AGENT",
        agentGeneration: 1,
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
  return `id:${id}\nevent:${type}\ndata:${JSON.stringify({ view: "PUBLIC_CONVERSATION", schema: "public-conversation-v2", generation, payload })}\n\n`;
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
