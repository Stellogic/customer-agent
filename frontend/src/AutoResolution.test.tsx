import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { AutoResolutionNotice } from "./AutoResolutionNotice";

vi.mock("./csrf", () => ({
  loadCsrfToken: async () => ({ token: "customer-csrf", headerName: "X-CSRF-TOKEN" }),
}));

const ticketId = "16200000-0000-0000-0000-000000000001";
const dueAt = "2026-08-30T10:05:00Z";

function snapshot(status: string, cursor = 2) {
  return {
    view: "PUBLIC_CONVERSATION",
    schema: "public-conversation-v2",
    cursor: `public-conversation-v2:${cursor}`,
    ticket: {
      id: ticketId,
      lifecycleState: "INVESTIGATING",
      handlingMode: "AGENT",
      agentGeneration: 1,
    },
    messages: [],
    clarification: null,
    autoResolution: { status, dueAt: status === "PENDING" ? dueAt : null },
  };
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status });
}

function openStream() {
  return new Response(new ReadableStream({ start() {} }));
}

describe("Issue #162 客户自动解决", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it("根据服务端截止时间恢复倒计时，归零只等待核验", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-30T10:03:00Z"));
    const props = {
      resolution: { status: "PENDING" as const, dueAt },
      cancelling: false,
      onCancel: vi.fn(),
    };
    const first = render(<AutoResolutionNotice {...props} />);
    expect(screen.getByRole("timer")).toHaveTextContent("2 分 0 秒");
    first.unmount();
    vi.setSystemTime(new Date("2026-08-30T10:04:00Z"));
    render(<AutoResolutionNotice {...props} />);
    expect(screen.getByRole("timer")).toHaveTextContent("1 分 0 秒");
    await act(() => vi.advanceTimersByTime(60_000));
    expect(screen.getByRole("status")).toHaveTextContent("正在重新核验");
    expect(screen.queryByText("工单已自动解决")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "仍需帮助，取消自动解决" })).toBeEnabled();
    expect(props.onCancel).not.toHaveBeenCalled();
  });

  it.each([200, 409])("取消带候选期限及 CSRF，响应 %s 后重新读取权威状态", async (status) => {
    globalThis.history.replaceState(null, "", `?ticket=${ticketId}`);
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(snapshot("PENDING")))
      .mockResolvedValueOnce(openStream())
      .mockResolvedValueOnce(json({}, status))
      .mockResolvedValueOnce(json(snapshot("CANCELLED", 3)))
      .mockResolvedValueOnce(openStream());
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "仍需帮助，取消自动解决" }));
    expect(await screen.findByText("已取消自动解决")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "仍需帮助，取消自动解决" }),
    ).not.toBeInTheDocument();
    const request = fetchMock.mock.calls[2];
    expect(request[0]).toBe(`/api/customer/v2/tickets/${ticketId}/auto-resolution/cancel`);
    expect(request[1]?.method).toBe("POST");
    expect(new Headers(request[1]?.headers).get("X-CSRF-TOKEN")).toBe("customer-csrf");
    expect(JSON.parse(String(request[1]?.body))).toEqual({
      candidateDueAt: dueAt,
      candidateGeneration: 1,
    });
    expect(fetchMock.mock.calls[3][0]).toBe(`/api/customer/v2/tickets/${ticketId}`);
  });

  it("取消请求失败不伪造成功，保留重试入口", async () => {
    globalThis.history.replaceState(null, "", `?ticket=${ticketId}`);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(snapshot("PENDING")))
      .mockResolvedValueOnce(openStream())
      .mockRejectedValueOnce(new Error("network unavailable"));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "仍需帮助，取消自动解决" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("取消结果尚未确认");
    expect(screen.queryByText("已取消自动解决")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "仍需帮助，取消自动解决" })).toBeEnabled();
  });

  it("SSE 按序显示取消、重新评估及权威解决，不需重载", async () => {
    globalThis.history.replaceState(null, "", `?ticket=${ticketId}`);
    let stream: ReadableStreamDefaultController<Uint8Array>;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(snapshot("PENDING")))
      .mockResolvedValueOnce(
        new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              stream = controller;
            },
          }),
        ),
      );
    render(<App />);
    await screen.findByRole("button", { name: "仍需帮助，取消自动解决" });
    for (const [index, status, label] of [
      [3, "CANCELLED", "已取消自动解决"],
      [4, "REEVALUATING", "正在重新评估"],
      [5, "RESOLVED", "工单已自动解决"],
    ] as const) {
      const data = JSON.stringify({
        view: "PUBLIC_CONVERSATION",
        schema: "public-conversation-v2",
        generation: 1,
        payload: { autoResolution: { status, dueAt: null } },
      });
      await act(async () => {
        stream.enqueue(
          new TextEncoder().encode(
            `id:public-conversation-v2:${index}\nevent:AUTO_RESOLUTION_CHANGED\ndata:${data}\n\n`,
          ),
        );
      });
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });
});
