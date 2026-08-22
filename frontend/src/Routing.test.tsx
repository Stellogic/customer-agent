import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RootApplication } from "./RootApplication";
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
    "CUSTOMER_HELP_ACCESS" | "SUPPORT_WORKBENCH_ACCESS" | "APPROVAL_WORKBENCH_ACCESS"
  >;
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
    expect(screen.queryByRole("navigation", { name: "内部工作区" })).not.toBeInTheDocument();
  });

  it.each([
    [support, ["客服工作区"], ["审批工作区"]],
    [approver, ["审批工作区"], ["客服工作区"]],
    [dualRole, ["客服工作区", "审批工作区"], []],
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

    expect(await screen.findByRole("heading", { name: "403" })).toBeInTheDocument();
    expect(globalThis.location.pathname).toBe("/internal/approvals");
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
      if (path === `/api/customer/tickets/${ticketId}`) {
        return Response.json({
          view: "CUSTOMER_PUBLIC",
          schema: "customer-public-v1",
          cursor: "customer-public-v1:1",
          ticket: {
            id: ticketId,
            lifecycleState: "INVESTIGATING",
            handlingMode: "AGENT",
            agentGeneration: 1,
            firstRespondedAt: "2026-08-22T00:00:00Z",
          },
          messages: [
            { author: "SUPPORT", body: "仅属于旧客户主体的缓存", sentAt: "2026-08-22T00:00:00Z" },
          ],
        });
      }
      if (path === `/api/customer/tickets/${ticketId}/events`) {
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
      if (path === `/api/customer/tickets/${ticketId}`) {
        customerSnapshotReads += 1;
        return Response.json({
          view: "CUSTOMER_PUBLIC",
          schema: "customer-public-v1",
          cursor: "customer-public-v1:1",
          ticket: {
            id: ticketId,
            lifecycleState: "INVESTIGATING",
            handlingMode: "AGENT",
            agentGeneration: 1,
            firstRespondedAt: "2026-08-22T00:00:00Z",
          },
          messages: [
            {
              author: "SUPPORT",
              body: "通知丢失前的旧客户投影",
              sentAt: "2026-08-22T00:00:00Z",
            },
          ],
        });
      }
      if (path === `/api/customer/tickets/${ticketId}/events`) {
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
    expect(await screen.findByRole("heading", { name: "403" })).toBeInTheDocument();
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
    if (path === "/api/demo/session") {
      if (session.capabilities.includes("SUPPORT_WORKBENCH_ACCESS")) {
        return Response.json({ id: "support-demo", role: "SUPPORT", label: "客服演示入口" });
      }
      return Response.json({
        id: "approver-demo",
        role: "APPROVER",
        label: "审批演示入口",
      });
    }
    return new Response(null, { status: 503 });
  });
}
