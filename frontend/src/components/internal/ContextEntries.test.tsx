import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApprovalContextEntries,
  ApprovalQueueEntries,
  SupportContextEntries,
  type ApprovalContextEntriesProps,
  type SupportContextEntriesProps,
} from "./ContextEntries";

const supportEntries: SupportContextEntriesProps["entries"] = {
  transfer: { kind: "developing" },
  more: { kind: "developing" },
  order: { kind: "unavailable", reason: "当前投影未提供订单详情。" },
  logistics: { kind: "unavailable", reason: "当前投影未提供物流详情。" },
  contact: { kind: "unavailable", reason: "当前不可发送公开回复。" },
  similarCases: { kind: "developing" },
  suggestedActions: { kind: "developing" },
};

const approvalEntries: ApprovalContextEntriesProps["entries"] = {
  policy: { kind: "unavailable", reason: "当前没有政策投影。" },
  proposalLog: { kind: "unavailable", reason: "当前没有日志投影。" },
  logistics: { kind: "unavailable", reason: "当前没有物流投影。" },
  eligibility: { kind: "unavailable", reason: "当前没有资格检查投影。" },
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Issue #193 独立详情入口的 props 边界", () => {
  it("已有能力交由当前宿主定位，不降级成开发中，也不主动请求数据", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const onOpen = vi.fn();
    render(
      <SupportContextEntries
        projectionKey="current-assignment"
        entries={{ ...supportEntries, contact: { kind: "available", onOpen } }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "联系客户" }));
    expect(onOpen).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("客服转派和更多操作只提供无副作用反馈，不实现补偿或 Agent 核心动作", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<SupportContextEntries projectionKey="current" entries={supportEntries} />);
    for (const label of ["转派", "更多操作", "相似案例", "建议动作"]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      const dialog = await screen.findByRole("dialog", { name: `${label} · 开发中` });
      expect(within(dialog).getByRole("status")).toHaveTextContent("未更改任何业务状态");
      fireEvent.click(within(dialog).getByRole("button", { name: "知道了" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    }
    expect(
      screen.queryByRole("button", { name: /补偿|发送公开回复|批准/ }),
    ).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("撤权卸载客服入口及已打开弹层，新的投影不继承旧弹层", async () => {
    const view = render(<SupportContextEntries projectionKey="old" entries={supportEntries} />);
    fireEvent.click(screen.getByRole("button", { name: "转派" }));
    await screen.findByRole("dialog");
    view.rerender(<SupportContextEntries projectionKey={null} entries={supportEntries} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("相关入口已移除");
    view.rerender(<SupportContextEntries projectionKey="new" entries={supportEntries} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("投影直接替换时清除旧弹层并使用新的查看回调", async () => {
    const oldOpen = vi.fn();
    const newOpen = vi.fn();
    const view = render(
      <SupportContextEntries
        projectionKey="old"
        entries={{ ...supportEntries, order: { kind: "available", onOpen: oldOpen } }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "转派" }));
    await screen.findByRole("dialog");
    view.rerender(
      <SupportContextEntries
        projectionKey="new"
        entries={{ ...supportEntries, order: { kind: "available", onOpen: newOpen } }}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看订单" }));
    expect(oldOpen).not.toHaveBeenCalled();
    expect(newOpen).toHaveBeenCalledOnce();
  });

  it("审批入口复用裁剪证据，不提供完整对话跳转或请求", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const onOpen = vi.fn();
    const entries: ApprovalContextEntriesProps["entries"] = {
      ...approvalEntries,
      policy: { kind: "available", onOpen },
      eligibility: { kind: "available", onOpen },
    };
    const view = render(<ApprovalContextEntries projectionKey="lease-current" entries={entries} />);
    fireEvent.click(screen.getByRole("button", { name: "政策详情" }));
    fireEvent.click(screen.getByRole("button", { name: "资格检查明细" }));
    expect(onOpen).toHaveBeenCalledTimes(2);
    const fullConversation = screen.getByRole("button", { name: "完整对话" });
    expect(fullConversation).toBeDisabled();
    fireEvent.click(fullConversation);
    expect(screen.getByText(/当前审批视图不授予完整客户对话访问权/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    view.rerender(<ApprovalContextEntries projectionKey={null} entries={entries} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("审批授权详情");
  });

  it.each(["更多筛选", "导出"])("审批队列 %s 不更改筛选或生成虚假导出", async (label) => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<ApprovalQueueEntries />);
    fireEvent.click(screen.getByRole("button", { name: label }));
    const dialog = await screen.findByRole("dialog", { name: `${label} · 开发中` });
    expect(within(dialog).getByRole("status")).toHaveTextContent("未提交业务请求");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
