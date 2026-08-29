import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OrderTicketGroups } from "./OrderTicketGroups";

const TICKET_ONE = "15700000-0000-0000-0000-000000000001";
const TICKET_TWO = "15700000-0000-0000-0000-000000000002";

describe("客户订单工单总览", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("按订单展示独立工单、受控进度和多个待客户事项", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      Response.json({
        view: "CUSTOMER_ORDER_TICKET_GROUPS",
        schema: "customer-order-ticket-groups-v1",
        groups: [
          {
            orderReference: "ORDER-157",
            tickets: [
              {
                ticketId: TICKET_ONE,
                issueKind: "PACKAGE_NOT_RECEIVED",
                lifecycleState: "WAITING_FOR_CUSTOMER",
                handlingMode: "AGENT",
                controlledProgress: "WAITING_FOR_CUSTOMER",
                pendingCustomerAction: true,
                compensationFlowExists: false,
              },
              {
                ticketId: TICKET_TWO,
                issueKind: "DUPLICATE_CHARGE",
                lifecycleState: "INVESTIGATING",
                handlingMode: "HUMAN",
                controlledProgress: "HUMAN_HANDLING",
                pendingCustomerAction: true,
                compensationFlowExists: true,
              },
            ],
            pendingCustomerItems: [
              {
                ticketId: TICKET_ONE,
                type: "CLARIFICATION",
                customerQuestion: "请确认是否本人签收",
              },
              {
                ticketId: TICKET_TWO,
                type: "CLARIFICATION",
                customerQuestion: "请确认重复扣款记录",
              },
            ],
          },
        ],
      }),
    );
    const openTicket = vi.fn();
    render(<OrderTicketGroups onOpenTicket={openTicket} />);

    fireEvent.click(screen.getByRole("button", { name: "查看订单工单总览" }));

    expect(await screen.findByRole("heading", { name: "订单 ORDER-157" })).toBeInTheDocument();
    expect(screen.getAllByRole("article", { name: /独立工单/ })).toHaveLength(2);
    expect(screen.getByText("等待你的回复")).toBeInTheDocument();
    expect(screen.getByText("已转人工处理")).toBeInTheDocument();
    expect(screen.getByText("Agent")).toBeInTheDocument();
    expect(screen.getByText("人工客服")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "ORDER-157 待客户事项" })).toHaveTextContent(
      "请确认是否本人签收",
    );
    expect(screen.getByRole("list", { name: "ORDER-157 待客户事项" })).toHaveTextContent(
      "请确认重复扣款记录",
    );
    fireEvent.click(screen.getByRole("button", { name: `打开工单 ${TICKET_TWO}` }));
    expect(openTicket).toHaveBeenCalledWith(TICKET_TWO);
  });

  it("覆盖 loading、empty 与 error 状态", async () => {
    let resolveRequest: (response: Response) => void = () => undefined;
    vi.spyOn(globalThis, "fetch").mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        resolveRequest = resolve;
      }),
    );
    const view = render(<OrderTicketGroups onOpenTicket={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "查看订单工单总览" }));
    expect(screen.getByRole("status")).toHaveTextContent("正在汇总");
    resolveRequest(
      Response.json({
        view: "CUSTOMER_ORDER_TICKET_GROUPS",
        schema: "customer-order-ticket-groups-v1",
        groups: [],
      }),
    );
    expect(await screen.findByText("当前还没有客服工单")).toBeInTheDocument();

    view.unmount();
    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response("failed", { status: 503 }));
    render(<OrderTicketGroups onOpenTicket={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "查看订单工单总览" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取订单工单总览");
  });

  it.each([
    ["LOGISTICS_DELAY", "物流延迟", "AGENT_PROCESSING", "Agent 独立处理中"],
    ["PACKAGE_NOT_RECEIVED", "包裹未收到", "WAITING_FOR_CUSTOMER", "等待你的回复"],
    ["DUPLICATE_CHARGE", "重复扣款", "HUMAN_HANDLING", "已转人工处理"],
    ["ORDER_OPERATION_OR_RULE", "地址或取消规则", "RESOLVED", "已给出结论"],
    ["OTHER", "其他问题", "WAITING_FOR_EXTERNAL", "等待外部信息"],
  ] as const)(
    "桌面与窄屏同步呈现 %# 问题类型与进度状态",
    async (issueKind, issueLabelText, progress, progressLabelText) => {
      const ticketId = "16100000-0000-0000-0000-000000000001";
      for (const width of [1440, 375]) {
        cleanup();
        Object.defineProperty(globalThis, "innerWidth", { configurable: true, value: width });
        vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
          Response.json({
            view: "CUSTOMER_ORDER_TICKET_GROUPS",
            schema: "customer-order-ticket-groups-v1",
            groups: [
              {
                orderReference: "ORDER-161",
                tickets: [
                  {
                    ticketId,
                    issueKind,
                    lifecycleState:
                      progress === "RESOLVED"
                        ? "RESOLVED"
                        : progress === "WAITING_FOR_CUSTOMER"
                          ? "WAITING_FOR_CUSTOMER"
                          : progress === "WAITING_FOR_EXTERNAL"
                            ? "WAITING_FOR_EXTERNAL"
                            : "INVESTIGATING",
                    handlingMode: progress === "HUMAN_HANDLING" ? "HUMAN" : "AGENT",
                    controlledProgress: progress,
                    pendingCustomerAction: progress === "WAITING_FOR_CUSTOMER",
                    compensationFlowExists: false,
                  },
                ],
                pendingCustomerItems:
                  progress === "WAITING_FOR_CUSTOMER"
                    ? [
                        {
                          ticketId,
                          type: "CLARIFICATION",
                          customerQuestion: "请补充该问题的关键信息",
                        },
                      ]
                    : [],
              },
            ],
          }),
        );
        render(<OrderTicketGroups onOpenTicket={vi.fn()} />);
        fireEvent.click(screen.getByRole("button", { name: "查看订单工单总览" }));
        expect(await screen.findByText(issueLabelText)).toBeInTheDocument();
        expect(screen.getAllByText(progressLabelText).length).toBeGreaterThan(0);
        if (progress === "WAITING_FOR_CUSTOMER") {
          expect(screen.getByRole("list", { name: "ORDER-161 待客户事项" })).toHaveTextContent(
            "请补充该问题的关键信息",
          );
        }
        vi.restoreAllMocks();
      }
    },
  );

  it("同批多工单确认后自动进入订单总览", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      Response.json({
        view: "CUSTOMER_ORDER_TICKET_GROUPS",
        schema: "customer-order-ticket-groups-v1",
        groups: [],
      }),
    );

    render(<OrderTicketGroups autoLoad onOpenTicket={vi.fn()} />);

    expect(screen.getByRole("status")).toHaveTextContent("正在汇总");
    expect(await screen.findByText("当前还没有客服工单")).toBeInTheDocument();
  });
});
