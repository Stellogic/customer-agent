import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RootApplication } from "./RootApplication";

describe("人工身份登录基线", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it("客户演示账号只填充表单并通过 CSRF 保护的密码登录恢复当前身份", async () => {
    globalThis.history.replaceState(null, "", "/help/login");
    let csrfReads = 0;
    let loginPosts = 0;
    let logoutPosts = 0;
    let sessionReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/auth/csrf") {
        csrfReads += 1;
        return new Response(
          JSON.stringify({
            token:
              csrfReads === 1 ? "before-login" : csrfReads === 2 ? "after-login" : "after-logout",
            headerName: "X-CSRF-TOKEN",
          }),
          { status: 200 },
        );
      }
      if (path === "/api/auth/demo-accounts") {
        return new Response(
          JSON.stringify([
            {
              username: "customer-demo",
              displayName: "演示客户",
              subjectType: "CUSTOMER",
              password: "local-demo-password",
            },
          ]),
          { status: 200 },
        );
      }
      if (path === "/api/auth/login") {
        loginPosts += 1;
        expect(init?.method).toBe("POST");
        expect(new Headers(init?.headers).get("X-CSRF-TOKEN")).toBe("before-login");
        expect(String(init?.body)).toBe("username=customer-demo&password=local-demo-password");
        return new Response(null, { status: 204 });
      }
      if (path === "/api/auth/session") {
        sessionReads += 1;
        if (sessionReads === 1) return new Response(null, { status: 401 });
        return new Response(
          JSON.stringify({
            id: "customer-demo",
            displayName: "演示客户",
            subjectType: "CUSTOMER",
            roles: ["CUSTOMER"],
            capabilities: ["CUSTOMER_HELP_ACCESS"],
          }),
          { status: 200 },
        );
      }
      if (path === "/api/auth/logout") {
        logoutPosts += 1;
        expect(init?.method).toBe("POST");
        expect(new Headers(init?.headers).get("X-CSRF-TOKEN")).toBe("after-login");
        return new Response(null, { status: 204 });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RootApplication />);

    expect(await screen.findByRole("heading", { name: "客户登录" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "使用演示客户填充" }));
    expect(screen.getByLabelText("用户名")).toHaveValue("customer-demo");
    expect(screen.getByLabelText("密码")).toHaveValue("local-demo-password");
    expect(loginPosts).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("当前身份：演示客户")).toBeInTheDocument();
    expect(loginPosts).toBe(1);
    await waitFor(() => expect(csrfReads).toBe(2));

    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));

    expect(await screen.findByRole("heading", { name: "客户登录" })).toBeInTheDocument();
    expect(logoutPosts).toBe(1);
    await waitFor(() => expect(csrfReads).toBe(3));
  });

  it("刷新内部登录入口时从服务端 Session 恢复唯一当前主体", async () => {
    globalThis.history.replaceState(null, "", "/internal/login");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/auth/csrf") {
        return new Response(JSON.stringify({ token: "current", headerName: "X-CSRF-TOKEN" }), {
          status: 200,
        });
      }
      if (path === "/api/auth/demo-accounts") return new Response(null, { status: 404 });
      if (path === "/api/auth/session") {
        return new Response(
          JSON.stringify({
            id: "internal-demo",
            displayName: "演示双角色工作人员",
            subjectType: "INTERNAL",
            roles: ["SUPPORT", "APPROVER"],
            capabilities: ["SUPPORT_WORKBENCH_ACCESS", "APPROVAL_WORKBENCH_ACCESS"],
          }),
          { status: 200 },
        );
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RootApplication />);

    expect(await screen.findByText("当前身份：演示双角色工作人员")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "内部工作人员登录" })).not.toBeInTheDocument();
  });

  it("内部入口只提供内部账号填表并完成真实登录", async () => {
    globalThis.history.replaceState(null, "", "/internal/login");
    let sessionReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/auth/csrf") {
        return new Response(
          JSON.stringify({ token: "internal-csrf", headerName: "X-CSRF-TOKEN" }),
          {
            status: 200,
          },
        );
      }
      if (path === "/api/auth/demo-accounts") {
        return new Response(
          JSON.stringify([
            {
              username: "customer-demo",
              displayName: "演示客户",
              subjectType: "CUSTOMER",
              password: "local-demo-password",
            },
            {
              username: "support-demo",
              displayName: "演示客服",
              subjectType: "INTERNAL",
              password: "local-demo-password",
            },
          ]),
          { status: 200 },
        );
      }
      if (path === "/api/auth/session") {
        sessionReads += 1;
        if (sessionReads === 1) return new Response(null, { status: 401 });
        return new Response(
          JSON.stringify({
            id: "support-demo",
            displayName: "演示客服",
            subjectType: "INTERNAL",
            roles: ["SUPPORT"],
            capabilities: ["SUPPORT_WORKBENCH_ACCESS"],
          }),
          { status: 200 },
        );
      }
      if (path === "/api/auth/login") {
        expect(new Headers(init?.headers).get("X-CSRF-TOKEN")).toBe("internal-csrf");
        expect(String(init?.body)).toBe("username=support-demo&password=local-demo-password");
        return new Response(null, { status: 204 });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RootApplication />);

    expect(await screen.findByRole("heading", { name: "内部工作人员登录" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "使用演示客户填充" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "使用演示客服填充" }));
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByText("当前身份：演示客服")).toBeInTheDocument();
  });

  it("拒绝服务端返回契约外的角色或页面能力", async () => {
    globalThis.history.replaceState(null, "", "/internal/login");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/auth/csrf") {
        return new Response(JSON.stringify({ token: "current", headerName: "X-CSRF-TOKEN" }), {
          status: 200,
        });
      }
      if (path === "/api/auth/demo-accounts") return new Response(null, { status: 404 });
      if (path === "/api/auth/session") {
        return new Response(
          JSON.stringify({
            id: "unexpected-demo",
            displayName: "契约外身份",
            subjectType: "INTERNAL",
            roles: ["ADMIN"],
            capabilities: ["SYSTEM_ADMIN_ACCESS"],
          }),
          { status: 200 },
        );
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RootApplication />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "无法初始化安全登录，请刷新后重试。",
    );
    expect(screen.queryByText("当前身份：契约外身份")).not.toBeInTheDocument();
  });
});
