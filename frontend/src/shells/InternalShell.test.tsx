import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CurrentSession } from "../authContract";
import { CurrentSessionContext } from "../session";
import InternalShell from "./InternalShell";

const support: CurrentSession = {
  id: "support-shell-fixture",
  displayName: "客服壳层示例",
  subjectType: "INTERNAL",
  roles: ["SUPPORT"],
  capabilities: ["SUPPORT_WORKBENCH_ACCESS", "KNOWLEDGE_READ_ACCESS"],
};

const approver: CurrentSession = {
  id: "approver-shell-fixture",
  displayName: "审批壳层示例",
  subjectType: "INTERNAL",
  roles: ["APPROVER"],
  capabilities: ["APPROVAL_WORKBENCH_ACCESS"],
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function shell(session: CurrentSession, initialPath = "/internal") {
  return (
    <CurrentSessionContext.Provider value={session}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="internal" element={<InternalShell />}>
            <Route index element={<h1>工作区选择示例</h1>} />
            <Route path="support" element={<h1>授权客服页面示例</h1>} />
            <Route path="approvals" element={<h1>授权审批页面示例</h1>} />
            <Route path="knowledge" element={<h1>授权知识页面示例</h1>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </CurrentSessionContext.Provider>
  );
}

describe("Issue #193 内部壳独立入口", () => {
  it("客服快捷入口导航到既有工作区，不构造未实现路由或业务请求", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(shell(support));
    const shortcuts = within(screen.getByRole("navigation", { name: "快捷入口" }));
    fireEvent.click(shortcuts.getByRole("link", { name: /我的工单/ }));
    expect(screen.getByRole("heading", { name: "授权客服页面示例" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "客服工作区", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    fireEvent.click(shortcuts.getByRole("link", { name: /SLA 监控/ }));
    expect(screen.getByRole("heading", { name: "授权客服页面示例" })).toBeInTheDocument();
    fireEvent.click(shortcuts.getByRole("link", { name: "知识库" }));
    expect(screen.getByRole("heading", { name: "授权知识页面示例" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("审批身份不出现客服或无权知识入口，能力移除后入口随投影消失", () => {
    const view = render(shell(support));
    view.rerender(shell(approver));
    expect(screen.getByRole("link", { name: "审批工作区", exact: true })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /客服工作区|我的工单|SLA 监控|知识库|知识目录/ }))
      .not.toBeInTheDocument();
  });

  it("收起侧栏移除隐藏链接的焦点入口，并把焦点交还展开按钮", () => {
    render(shell(support));
    fireEvent.click(screen.getByRole("button", { name: "收起侧栏", exact: true }));
    const toggle = screen.getByRole("button", { name: "展开侧栏", exact: true });
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("navigation", { name: "内部工作区" })).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByRole("navigation", { name: "内部工作区" })).toBeVisible();
    expect(screen.getByRole("button", { name: "收起导航侧栏" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it.each(["模板中心", "通知中心"])("%s 反馈开发中，不发送请求或伪造结果", async (label) => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(shell(support));
    fireEvent.click(screen.getByRole("button", { name: label }));
    const dialog = await screen.findByRole("dialog", { name: `${label} · 开发中` });
    expect(within(dialog).getByRole("status")).toHaveTextContent("未提交业务请求");
    fireEvent.click(within(dialog).getByRole("button", { name: "知道了" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("重新同步保留当前受保护地址，用整页导航恢复身份且不声明成功", () => {
    render(shell(support, "/internal/support?view=current"));
    expect(screen.getByRole("link", { name: "重新同步", exact: true })).toHaveAttribute(
      "href",
      "/internal/support?view=current",
    );
    expect(screen.getByText(/重新同步会重载当前页并重新确认身份/)).toBeInTheDocument();
    expect(screen.queryByText("同步完成")).not.toBeInTheDocument();
  });
});
