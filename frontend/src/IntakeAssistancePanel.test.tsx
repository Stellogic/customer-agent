import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IntakeAssistancePanel } from "./IntakeAssistancePanel";

const REQUEST_ID = "15600000-0000-0000-0000-000000000001";
const INTAKE_ID = "15600000-0000-0000-0000-000000000002";

describe("受理协助队列", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("领取前只显示裁剪摘要，领取后修正候选并等待客户确认", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/support/intake-assistance/snapshot") {
        return Response.json({
          view: "INTAKE_ASSISTANCE",
          schema: "intake-assistance-v1",
          cursor: "intake-assistance-v1:1",
          requests: [
            {
              requestId: REQUEST_ID,
              status: "QUEUED",
              reasonCode: "AGENT_UNAVAILABLE",
              requestedAt: "2026-08-28T04:00:00Z",
              claimExpiresAt: null,
              assignedToCurrentSupport: false,
            },
          ],
        });
      }
      if (path === "/api/support/intake-assistance/events") return openStream();
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "support-csrf", headerName: "X-CSRF-TOKEN" });
      }
      if (path === `/api/support/intake-assistance/requests/${REQUEST_ID}/claims`) {
        expect(init?.method).toBe("POST");
        return Response.json(
          {
            requestId: REQUEST_ID,
            status: "CLAIMED",
            claimExpiresAt: "2026-08-28T04:15:00Z",
            replayed: false,
          },
          { status: 201 },
        );
      }
      if (path === `/api/support/intake-assistance/requests/${REQUEST_ID}`) {
        return Response.json({
          requestId: REQUEST_ID,
          intakeId: INTAKE_ID,
          status: "CLAIMED",
          reasonCode: "AGENT_UNAVAILABLE",
          originalMessage: "订单一直没有更新，请找人工客服",
          orderCandidates: [
            { reference: "ORDER-DELAY-001", summary: "配送中的合成订单" },
            { reference: "ORDER-DELAY-002", summary: "配送中的合成订单" },
          ],
          selectedOrderReference: null,
          issues: [],
          intakeVersion: 1,
          claimExpiresAt: "2026-08-28T04:15:00Z",
        });
      }
      if (path === `/api/support/intake-assistance/requests/${REQUEST_ID}/events`) {
        return openStream();
      }
      if (path === `/api/support/intake-assistance/requests/${REQUEST_ID}/proposal`) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        expect(body).toMatchObject({
          schema: "intake-assistance-v1",
          expectedIntakeVersion: 1,
          orderReference: "ORDER-DELAY-002",
        });
        expect(init?.method).toBe("POST");
        return Response.json(
          {
            requestId: REQUEST_ID,
            status: "WAITING_FOR_CUSTOMER",
            intakeVersion: 2,
            claimExpiresAt: "2026-08-28T04:15:00Z",
            replayed: false,
          },
          { status: 201 },
        );
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<IntakeAssistancePanel />);

    expect(await screen.findByRole("heading", { name: "受理协助队列" })).toBeInTheDocument();
    expect(screen.getByText("Agent 暂不可用")).toBeInTheDocument();
    expect(screen.queryByText(/订单一直没有更新/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: `领取受理协助 ${REQUEST_ID}` }));

    expect(await screen.findByRole("heading", { name: "协助确认受理" })).toBeInTheDocument();
    expect(screen.getByText("订单一直没有更新，请找人工客服")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("订单候选"), {
      target: { value: "ORDER-DELAY-002" },
    });
    fireEvent.click(screen.getByLabelText("物流延迟"));
    fireEvent.change(screen.getByLabelText("物流延迟摘要"), {
      target: { value: "物流多日没有更新" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交给客户确认" }));

    expect(await screen.findByText("已提交给客户确认；尚未创建正式工单。")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/support/intake-assistance/requests/${REQUEST_ID}/proposal`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("覆盖 loading、empty、error 与权限撤销状态", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(
        Response.json({
          view: "INTAKE_ASSISTANCE",
          schema: "intake-assistance-v1",
          cursor: "intake-assistance-v1:2",
          requests: [],
        }),
      )
      .mockResolvedValueOnce(openStream());

    render(<IntakeAssistancePanel />);
    expect(screen.getByText("正在读取受理协助权威快照…")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("受理协助队列加载失败");
    fireEvent.click(screen.getByRole("button", { name: "重新同步受理协助" }));
    await waitFor(() => expect(screen.getByText("当前没有待处理的受理协助")).toBeInTheDocument());
  });

  it("客户确认完成后刷新队列快照仍保留权限撤销告警", async () => {
    const queueStream = openPushableStream();
    const authorityStream = openPushableStream();
    let detailsCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/support/intake-assistance/snapshot") {
        return Response.json({
          view: "INTAKE_ASSISTANCE",
          schema: "intake-assistance-v1",
          cursor: detailsCalls > 1 ? "intake-assistance-v1:3" : "intake-assistance-v1:1",
          requests:
            detailsCalls > 1
              ? []
              : [
                  {
                    requestId: REQUEST_ID,
                    status: "WAITING_FOR_CUSTOMER",
                    reasonCode: "AGENT_UNAVAILABLE",
                    requestedAt: "2026-08-28T04:00:00Z",
                    claimExpiresAt: "2026-08-28T04:15:00Z",
                    assignedToCurrentSupport: true,
                  },
                ],
        });
      }
      if (path === "/api/support/intake-assistance/events") return queueStream.response();
      if (path === `/api/support/intake-assistance/requests/${REQUEST_ID}`) {
        detailsCalls += 1;
        if (detailsCalls > 1) return new Response("gone", { status: 404 });
        return Response.json({
          requestId: REQUEST_ID,
          intakeId: INTAKE_ID,
          status: "WAITING_FOR_CUSTOMER",
          reasonCode: "AGENT_UNAVAILABLE",
          originalMessage: "订单一直没有更新，请找人工客服",
          orderCandidates: [{ reference: "ORDER-DELAY-001", summary: "配送中的合成订单" }],
          selectedOrderReference: "ORDER-DELAY-001",
          issues: [{ kind: "LOGISTICS_DELAY", summary: "物流多日没有更新" }],
          intakeVersion: 2,
          claimExpiresAt: "2026-08-28T04:15:00Z",
        });
      }
      if (path === `/api/support/intake-assistance/requests/${REQUEST_ID}/events`) {
        return authorityStream.response();
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<IntakeAssistancePanel />);
    fireEvent.click(await screen.findByRole("button", { name: `继续受理协助 ${REQUEST_ID}` }));
    expect(await screen.findByRole("heading", { name: "协助确认受理" })).toBeInTheDocument();

    authorityStream.close();
    expect(await screen.findByRole("alert")).toHaveTextContent("受理协助权限已撤销");

    queueStream.push(
      [
        "id: intake-assistance-v1:2",
        `data: ${JSON.stringify({
          view: "INTAKE_ASSISTANCE",
          schema: "intake-assistance-v1",
          payload: {},
        })}`,
        "",
        "",
      ].join("\n"),
    );
    await waitFor(() => expect(screen.getByText("当前没有待处理的受理协助")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("受理协助权限已撤销");
    expect(screen.queryByRole("heading", { name: "协助确认受理" })).not.toBeInTheDocument();
  });
});

function openStream() {
  return new Response(new ReadableStream(), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function openPushableStream() {
  let controller: ReadableStreamDefaultController<Uint8Array> | undefined;
  return {
    response() {
      return new Response(
        new ReadableStream({
          start(next) {
            controller = next;
          },
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      );
    },
    push(value: string) {
      controller?.enqueue(new TextEncoder().encode(value));
    },
    close() {
      controller?.close();
    },
  };
}
