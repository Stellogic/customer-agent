import { afterEach, describe, expect, it, vi } from "vitest";
import {
  announceHumanSessionChange,
  observeHumanSession,
  resetHumanSessionLifecycleForTests,
  subscribeToHumanSessionInvalidation,
} from "./humanSessionLifecycle";

describe("人工 Session 跨标签生命周期", () => {
  afterEach(() => {
    resetHumanSessionLifecycleForTests();
    vi.restoreAllMocks();
  });

  it("同源其他标签退出时立即通知当前标签清除旧主体", () => {
    const invalidated = vi.fn();
    const unsubscribe = subscribeToHumanSessionInvalidation(invalidated);

    announceHumanSessionChange("logged-out");

    expect(invalidated).toHaveBeenCalledExactlyOnceWith("logged-out");
    unsubscribe();
  });

  it("当前标签收到 API 401 时也收敛为未登录而不依赖跨标签通知", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 401 }));
    const invalidated = vi.fn();
    subscribeToHumanSessionInvalidation(invalidated);

    const { humanSessionFetch } = await import("./humanSessionLifecycle");
    const response = await humanSessionFetch("/api/customer/tickets");

    expect(response.status).toBe(401);
    expect(invalidated).toHaveBeenCalledExactlyOnceWith("server-rejected");
  });

  it.each([403, 404])("跨标签通知丢失时从 API %s 重新校验并收敛到替换后的主体", async (status) => {
    observeHumanSession({
      id: "customer-a",
      subjectType: "CUSTOMER",
      roles: ["CUSTOMER"],
      capabilities: ["CUSTOMER_HELP_ACCESS"],
    });
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status }))
      .mockResolvedValueOnce(
        Response.json({
          id: "support-demo",
          displayName: "演示客服",
          subjectType: "INTERNAL",
          roles: ["SUPPORT"],
          capabilities: ["SUPPORT_WORKBENCH_ACCESS"],
        }),
      );
    const invalidated = vi.fn();
    subscribeToHumanSessionInvalidation(invalidated);

    const { humanSessionFetch } = await import("./humanSessionLifecycle");
    const response = await humanSessionFetch("/api/customer/tickets/old-resource");

    expect(response.status).toBe(status);
    expect(globalThis.fetch).toHaveBeenNthCalledWith(2, "/api/auth/session", {
      credentials: "same-origin",
      cache: "no-store",
    });
    expect(invalidated).toHaveBeenCalledExactlyOnceWith("subject-replaced");
  });

  it("资源自身撤权的 403 在服务端主体未变化时不误清除 Session", async () => {
    const session = {
      id: "support-demo",
      displayName: "演示客服",
      subjectType: "INTERNAL" as const,
      roles: ["SUPPORT" as const],
      capabilities: ["SUPPORT_WORKBENCH_ACCESS" as const],
    };
    observeHumanSession(session);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 403 }))
      .mockResolvedValueOnce(Response.json(session));
    const invalidated = vi.fn();
    subscribeToHumanSessionInvalidation(invalidated);

    const { humanSessionFetch } = await import("./humanSessionLifecycle");
    await humanSessionFetch("/api/support/workbench/tickets/revoked");

    expect(invalidated).not.toHaveBeenCalled();
  });
});
