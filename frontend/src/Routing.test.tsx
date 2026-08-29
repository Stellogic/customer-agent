import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RootApplication } from "./RootApplication";
import { LEGACY_ROUTE_REDIRECTS } from "./workspaceRegistry";
import {
  announceHumanSessionChange,
  resetHumanSessionLifecycleForTests,
} from "./humanSessionLifecycle";

type Session = {
  id: string;
  displayName: string;
  subjectType: "CUSTOMER" | "INTERNAL";
  roles: Array<"CUSTOMER" | "SUPPORT" | "APPROVER">;
  capabilities: Array<
    | "CUSTOMER_HELP_ACCESS"
    | "SUPPORT_WORKBENCH_ACCESS"
    | "APPROVAL_WORKBENCH_ACCESS"
    | "KNOWLEDGE_READ_ACCESS"
  >;
};
const supportWithKnowledge: Session = {
  id: "support-knowledge",
  displayName: "演示知识客服",
  subjectType: "INTERNAL",
  roles: ["SUPPORT"],
  capabilities: ["SUPPORT_WORKBENCH_ACCESS", "KNOWLEDGE_READ_ACCESS"],
};

const customer: Session = {
  id: "customer-demo",
  displayName: "演示客户",
  subjectType: "CUSTOMER",
  roles: ["CUSTOMER"],
  capabilities: ["CUSTOMER_HELP_ACCESS"],
};
const support: Session = {
  id: "support-demo",
  displayName: "演示客服",
  subjectType: "INTERNAL",
  roles: ["SUPPORT"],
  capabilities: ["SUPPORT_WORKBENCH_ACCESS"],
};
const approver: Session = {
  id: "approver-demo",
  displayName: "演示审批人",
  subjectType: "INTERNAL",
  roles: ["APPROVER"],
  capabilities: ["APPROVAL_WORKBENCH_ACCESS"],
};
const dualRole: Session = {
  id: "internal-demo",
  displayName: "演示双角色工作人员",
  subjectType: "INTERNAL",
  roles: ["SUPPORT", "APPROVER"],
  capabilities: ["SUPPORT_WORKBENCH_ACCESS", "APPROVAL_WORKBENCH_ACCESS"],
};

describe("Issue #73 静态路由与两个界面壳", () => {
  it("Issue #79 只在静态路由注册表保留两个弃用重定向", () => {
    expect(LEGACY_ROUTE_REDIRECTS).toEqual([
      { path: "/support", to: "/internal/support", deprecated: true },
      { path: "/approver", to: "/internal/approvals", deprecated: true },
    ]);
  });

  afterEach(() => {
    cleanup();
    resetHumanSessionLifecycleForTests();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it.each([
    [customer, "/help"],
    [support, "/internal/support"],
    [approver, "/internal/approvals"],
    [dualRole, "/internal"],
  ])(
    "根据当前身份接口为 %s 选择静态默认落点",
    async (session, expectedPath) => {
      mockSession(session);

      render(<RootApplication />);

      await waitFor(() => expect(globalThis.location.pathname).toBe(expectedPath));
    },
    60_000,
  );

  it("客户路由使用 CustomerShell，且不出现内部导航", async () => {
    globalThis.history.replaceState(null, "", "/help");
    mockSession(customer);

    render(<RootApplication />);

    expect(await screen.findByRole("banner", { name: "客户帮助中心" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Stellogic 客户帮助中心" })).toHaveAttribute(
      "href",
      "/help",
    );
    expect(screen.getByText("当前客户：演示客户")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "客户导航" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "内部工作区" })).not.toBeInTheDocument();
  });

  it("内部 Shell 明确当前工作人员且不混入客户导航", async () => {
    globalThis.history.replaceState(null, "", "/internal/support");
    mockSession(support);

    render(<RootApplication />);

    expect(await screen.findByRole("banner", { name: "内部工作台" })).toHaveTextContent(
      "当前工作人员：演示客服",
    );
    expect(screen.getByRole("link", { name: "Stellogic 内部工作台" })).toHaveAttribute(
      "href",
      "/internal",
    );
    expect(screen.queryByRole("navigation", { name: "客户导航" })).not.toBeInTheDocument();
  });

  it.each([
    [support, ["客服工作区"], ["审批工作区", "知识目录"]],
    [approver, ["审批工作区"], ["客服工作区", "知识目录"]],
    [dualRole, ["客服工作区", "审批工作区"], ["知识目录"]],
    [supportWithKnowledge, ["客服工作区", "知识目录"], ["审批工作区"]],
  ])("内部菜单只投影 %s 当前拥有的 capability", async (session, visibleLabels, hiddenLabels) => {
    mockSession(session);

    render(<RootApplication />);

    const navigation = await screen.findByRole("navigation", { name: "内部工作区" });
    for (const label of visibleLabels) {
      expect(within(navigation).getByRole("link", { name: label })).toBeInTheDocument();
    }
    for (const label of hiddenLabels) {
      expect(within(navigation).queryByRole("link", { name: label })).not.toBeInTheDocument();
    }
  });

  it("Issue #77 双角色内部默认页只展示两个 capability 入口且不预读业务数据", async () => {
    globalThis.history.replaceState(null, "", "/internal");
    const fetchMock = mockSession(dualRole);

    render(<RootApplication />);

    const heading = await screen.findByRole("heading", { name: "选择工作区" });
    const choice = heading.closest("main");
    expect(choice).not.toBeNull();
    expect(within(choice!).getByRole("link", { name: /客服工作区/ })).toHaveAttribute(
      "href",
      "/internal/support",
    );
    expect(within(choice!).getByRole("link", { name: /审批工作区/ })).toHaveAttribute(
      "href",
      "/internal/approvals",
    );
    expect(within(choice!).getByText("当前工作人员：演示双角色工作人员")).toBeInTheDocument();
    expect(
      within(choice!).getByText("进入共享队列，查看当前职责允许的客服工作入口。"),
    ).toBeInTheDocument();
    expect(
      within(choice!).getByText("进入待审批队列，查看当前职责允许的补偿审查入口。"),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/session", {
      credentials: "same-origin",
      cache: "no-store",
    });
  });

  it("已登录但缺少页面 capability 时明确显示 403", async () => {
    globalThis.history.replaceState(null, "", "/internal/approvals");
    mockSession(support);

    render(<RootApplication />);

    const heading = await screen.findByRole("heading", { name: "当前身份无权访问此页面" });
    const boundary = heading.closest("main");
    expect(boundary).not.toBeNull();
    expect(within(boundary!).getByText("403")).toBeInTheDocument();
    expect(within(boundary!).queryByText(/capability/i)).not.toBeInTheDocument();
    expect(within(boundary!).getByRole("link", { name: "返回可访问工作区" })).toHaveAttribute(
      "href",
      "/internal/support",
    );
    expect(globalThis.location.pathname).toBe("/internal/approvals");
  });

  it("缺少知识 capability 时直接访问知识路由显示 403", async () => {
    globalThis.history.replaceState(null, "", "/internal/knowledge");
    mockSession(support);

    render(<RootApplication />);

    const heading = await screen.findByRole("heading", { name: "当前身份无权访问此页面" });
    const boundary = heading.closest("main");
    expect(boundary).not.toBeNull();
    expect(within(boundary!).getByText("403")).toBeInTheDocument();
    expect(within(boundary!).queryByText(/capability|知识目录/i)).not.toBeInTheDocument();
    expect(within(boundary!).getByRole("link", { name: "返回可访问工作区" })).toHaveAttribute(
      "href",
      "/internal/support",
    );
  });

  it("未知路由只说明页面未找到且不增加业务资源线索", async () => {
    globalThis.history.replaceState(null, "", "/internal/unknown-record");

    render(<RootApplication />);

    const heading = await screen.findByRole("heading", { name: "没有找到这个页面" });
    const state = heading.closest("main");
    expect(state).not.toBeNull();
    expect(within(state!).getByText("404")).toBeInTheDocument();
    expect(within(state!).queryByText(/工单|审批|资源/)).not.toBeInTheDocument();
    expect(within(state!).getByRole("link", { name: "前往客户登录" })).toHaveAttribute(
      "href",
      "/help/login",
    );
    expect(within(state!).getByRole("link", { name: "前往内部登录" })).toHaveAttribute(
      "href",
      "/internal/login",
    );
  });

  it("恢复身份时以可访问的忙碌状态保留稳定页面骨架", () => {
    globalThis.history.replaceState(null, "", "/internal");
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => undefined));

    render(<RootApplication />);

    const status = screen.getByRole("status", { name: "正在确认当前身份" });
    const state = status.closest("main");
    expect(state).not.toBeNull();
    expect(state).toHaveAttribute("aria-busy", "true");
    expect(within(state!).getByText("正在安全地恢复你的工作区…")).toBeInTheDocument();
  });

  it("身份恢复失败时提供非技术化说明和当前地址重载入口", async () => {
    globalThis.history.replaceState(null, "", "/internal");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network unavailable"));

    render(<RootApplication />);

    const heading = await screen.findByRole("heading", { name: "暂时无法进入工作区" });
    const state = heading.closest("main");
    expect(state).not.toBeNull();
    expect(within(state!).getByRole("alert")).toHaveTextContent(
      "当前身份暂时无法确认。请重新加载页面后再试。",
    );
    expect(within(state!).getByRole("link", { name: "重新加载当前页面" })).toHaveAttribute(
      "href",
      "/internal",
    );
  });

  it("未登录内部路由只保留认可的站内 returnTo", async () => {
    globalThis.history.replaceState(null, "", "/internal/support?queue=mine");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 401 }));

    render(<RootApplication />);

    await waitFor(() => expect(globalThis.location.pathname).toBe("/internal/login"));
    expect(new URLSearchParams(globalThis.location.search).get("returnTo")).toBe(
      "/internal/support?queue=mine",
    );
  });

  it("登录入口拒绝外部 returnTo 并回到身份默认落点", async () => {
    globalThis.history.replaceState(
      null,
      "",
      "/help/login?returnTo=https%3A%2F%2Fevil.example%2Fsteal",
    );
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "current", headerName: "X-CSRF-TOKEN" });
      }
      if (path === "/api/auth/demo-accounts") return new Response(null, { status: 404 });
      if (path === "/api/auth/session") return Response.json(customer);
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RootApplication />);

    await waitFor(() => expect(globalThis.location.pathname).toBe("/help"));
    expect(globalThis.location.origin).not.toBe("https://evil.example");
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/session", {
      credentials: "same-origin",
      cache: "no-store",
    });
  });

  it("弃用入口重定向到正式静态路由", async () => {
    globalThis.history.replaceState(null, "", "/approver?revision=revision-1");
    mockSession(approver);

    render(<RootApplication />);

    await waitFor(() => expect(globalThis.location.pathname).toBe("/internal/approvals"));
  });

  it("其他标签退出后当前标签立即卸载主体工作区并回到对应登录入口", async () => {
    globalThis.history.replaceState(null, "", "/internal");
    let sessionReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/auth/session") {
        sessionReads += 1;
        return sessionReads === 1 ? Response.json(dualRole) : new Response(null, { status: 401 });
      }
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "anonymous-after-logout", headerName: "X-CSRF-TOKEN" });
      }
      if (path === "/api/auth/demo-accounts") return new Response(null, { status: 404 });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RootApplication />);
    await waitFor(() => expect(globalThis.location.pathname).toBe("/internal"));

    announceHumanSessionChange("logged-out");

    await waitFor(() => expect(globalThis.location.pathname).toBe("/internal/login"));
    expect(await screen.findByRole("heading", { name: "内部工作人员登录" })).toBeInTheDocument();
  }, 60_000);

  it("其他标签退出会立即中止当前标签 SSE 并移除客户缓存投影", async () => {
    const ticketId = "78000000-0000-0000-0000-000000000001";
    globalThis.history.replaceState(null, "", `/help?ticket=${ticketId}`);
    let sessionReads = 0;
    let streamAborted = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/auth/session") {
        sessionReads += 1;
        return sessionReads === 1 ? Response.json(customer) : new Response(null, { status: 401 });
      }
      if (path === `/api/customer/v2/tickets/${ticketId}`) {
        return Response.json({
          view: "PUBLIC_CONVERSATION",
          schema: "public-conversation-v2",
          cursor: "public-conversation-v2:1",
          ticket: {
            id: ticketId,
            lifecycleState: "INVESTIGATING",
            handlingMode: "AGENT",
            agentGeneration: 1,
          },
          messages: [
            { author: "SUPPORT", body: "仅属于旧客户主体的缓存", sentAt: "2026-08-22T00:00:00Z" },
          ],
          clarification: null,
        });
      }
      if (path === `/api/customer/v2/tickets/${ticketId}/events`) {
        init?.signal?.addEventListener("abort", () => {
          streamAborted = true;
        });
        return new Response(new ReadableStream({ start() {} }), {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "anonymous-after-logout", headerName: "X-CSRF-TOKEN" });
      }
      if (path === "/api/auth/demo-accounts") return new Response(null, { status: 404 });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RootApplication />);
    expect(await screen.findByText("仅属于旧客户主体的缓存")).toBeInTheDocument();

    announceHumanSessionChange("logged-out");

    await waitFor(() => expect(streamAborted).toBe(true));
    expect(screen.queryByText("仅属于旧客户主体的缓存")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "客户登录" })).toBeInTheDocument();
  }, 60_000);

  it("跨标签通知丢失时由 SSE 403 重校验 Session 并卸载旧客户投影", async () => {
    const ticketId = "78000000-0000-0000-0000-000000000002";
    globalThis.history.replaceState(null, "", `/help?ticket=${ticketId}`);
    let sessionReads = 0;
    let customerSnapshotReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/auth/session") {
        sessionReads += 1;
        return Response.json(sessionReads === 1 ? customer : support);
      }
      if (path === `/api/customer/v2/tickets/${ticketId}`) {
        customerSnapshotReads += 1;
        return Response.json({
          view: "PUBLIC_CONVERSATION",
          schema: "public-conversation-v2",
          cursor: "public-conversation-v2:1",
          ticket: {
            id: ticketId,
            lifecycleState: "INVESTIGATING",
            handlingMode: "AGENT",
            agentGeneration: 1,
          },
          messages: [
            {
              author: "SUPPORT",
              body: "通知丢失前的旧客户投影",
              sentAt: "2026-08-22T00:00:00Z",
            },
          ],
          clarification: null,
        });
      }
      if (path === `/api/customer/v2/tickets/${ticketId}/events`) {
        return new Response(null, { status: 403 });
      }
      if (path === "/api/auth/csrf") {
        return Response.json({ token: "support-session", headerName: "X-CSRF-TOKEN" });
      }
      if (path === "/api/auth/demo-accounts") return new Response(null, { status: 404 });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RootApplication />);

    await waitFor(() => expect(sessionReads).toBeGreaterThanOrEqual(2));
    expect(customerSnapshotReads).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("通知丢失前的旧客户投影")).not.toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "当前身份无权访问此页面" }),
    ).toBeInTheDocument();
  }, 60_000);
});

function mockSession(session: Session) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path === "/api/auth/session") {
      return new Response(JSON.stringify(session), { status: 200 });
    }
    if (path === "/api/approver/compensation-proposals") {
      return new Response(JSON.stringify([]), { status: 200 });
    }
    return new Response(null, { status: 503 });
  });
}
