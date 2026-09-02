import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { isRecord } from "../../streamProtocol";
import { SupportAssistance } from "./SupportAssistance";

const ticketId = "26000000-0000-0000-0000-000000000001";
const assignmentId = "27000000-0000-0000-0000-000000000001";
const base = `/api/support/workbench/tickets/${ticketId}/assistance`;

describe("客服辅助真实宿主边界（合成HTTP响应）", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("只发送当前assignment和查询，结果必须人工插入和审阅后移交", async () => {
    const review = vi.fn();
    const bodies: Record<string, unknown>[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/context"))
        return Response.json({ schema: "support-assistance-v1", ticketId, assignmentId });
      if (url === "/api/auth/csrf")
        return Response.json({ headerName: "X-CSRF-TOKEN", token: "fixture" });
      if (url === `${base}/requests`) {
        const body: unknown = JSON.parse(String(init?.body));
        if (!isRecord(body) || typeof body.requestId !== "string")
          throw new Error("invalid fixture request");
        bodies.push(body);
        return Response.json({
          ...body,
          ticketId,
          view: {
            status: "ready",
            kind: "draft",
            requestId: body.requestId,
            retrievalEmpty: false,
            text: "合成客服草稿",
            suggestions: [],
            citations: [],
          },
        });
      }
      throw new Error("unexpected request");
    });
    render(
      <SupportAssistance
        ticketId={ticketId}
        defaultQuery="合成查询"
        onReviewDraft={review}
        onClearDraft={() => undefined}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "回复草稿" }));
    await screen.findByText("合成客服草稿");
    expect(bodies).toHaveLength(1);
    expect(Object.keys(bodies[0]).sort()).toEqual([
      "assignmentId",
      "kind",
      "query",
      "requestId",
      "schema",
    ]);
    expect(review).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "插入回复草稿" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "交给人工发送区" }));
    expect(review).toHaveBeenCalledExactlyOnceWith("合成客服草稿");
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith("/messages"))).toBe(
      false,
    );
  });

  it("网络结果未知时仅GET原requestId，不重发生成；403清除人工草稿", async () => {
    let requestId = "";
    const clearDraft = vi.fn();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/context"))
        return Response.json({ schema: "support-assistance-v1", ticketId, assignmentId });
      if (url === "/api/auth/csrf")
        return Response.json({ headerName: "X-CSRF-TOKEN", token: "fixture" });
      if (url === `${base}/requests`) {
        const body: unknown = JSON.parse(String(init?.body));
        if (!isRecord(body) || typeof body.requestId !== "string")
          throw new Error("invalid fixture request");
        requestId = body.requestId;
        throw new TypeError("offline fixture");
      }
      if (url === `${base}/requests/${requestId}`)
        return Response.json({ code: "KNOWLEDGE_ACCESS_DENIED" }, { status: 403 });
      throw new Error("unexpected request");
    });
    render(
      <SupportAssistance
        ticketId={ticketId}
        defaultQuery="合成查询"
        onReviewDraft={null}
        onClearDraft={clearDraft}
      />,
    );
    const editor = await screen.findByRole("textbox", { name: "内部编辑区（尚未发送）" });
    fireEvent.change(editor, { target: { value: "人工内部草稿" } });
    fireEvent.click(screen.getByRole("button", { name: "回复草稿" }));
    fireEvent.click(await screen.findByRole("button", { name: "查询辅助结果" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("textbox", { name: "内部编辑区（尚未发送）" }),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    expect(
      fetchMock.mock.calls.some(([url]) => String(url) === `${base}/requests/${requestId}`),
    ).toBe(true);
    expect(clearDraft).toHaveBeenCalled();
  });
});
