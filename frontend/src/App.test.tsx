import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

describe("客户帮助中心", () => {
  afterEach(() => vi.restoreAllMocks());

  it("提交后读取 CUSTOMER_PUBLIC 权威快照并显示受理结果", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ ticketId: "ticket-13", replayed: false }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        view: "CUSTOMER_PUBLIC",
        cursor: "customer-public-v1:2",
        ticket: { id: "ticket-13", lifecycleState: "INVESTIGATING", handlingMode: "AGENT", firstRespondedAt: "2026-08-09T00:00:00Z" },
        messages: [
          { author: "CUSTOMER", body: "物流已经延迟多日", sentAt: "2026-08-09T00:00:00Z" },
          { author: "SUPPORT", body: "您的问题已受理", sentAt: "2026-08-09T00:00:00Z" },
        ],
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(
        'id:customer-public-v1:3\nevent:PUBLIC_MESSAGE_APPENDED\ndata:{"author":"SUPPORT","body":"正在核对物流轨迹","sentAt":"2026-08-09T00:01:00Z"}\n\n',
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ));

    render(<App />);
    fireEvent.change(screen.getByLabelText("订单编号"), { target: { value: "ORDER-DELAY-001" } });
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: "物流已经延迟多日" } });
    fireEvent.click(screen.getByRole("button", { name: "提交物流延迟问题" }));

    expect(await screen.findByText("您的问题已受理")).toBeInTheDocument();
    expect(await screen.findByText("正在核对物流轨迹")).toBeInTheDocument();
    expect(screen.getByText("调查中")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[1][0]).toBe("/api/customer/tickets/ticket-13");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/customer/tickets/ticket-13/events");
  });
});
