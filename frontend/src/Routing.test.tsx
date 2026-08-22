import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RootApplication } from "./RootApplication";

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

  it("双角色内部默认页只展示两个 capability 入口且不预读业务数据", async () => {
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
