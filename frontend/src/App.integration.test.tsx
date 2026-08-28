import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createCookieBrowserFetch } from "./liveBrowserTestClient";
import { RootApplication } from "./RootApplication";
import { SupportWorkbench } from "./SupportWorkbench";

const liveBaseUrl = import.meta.env.VITE_SMOKE_BASE_URL as string | undefined;

describe.skipIf(!liveBaseUrl)("客户帮助中心全栈验收", () => {
  const nativeFetch = globalThis.fetch;

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it("跨 React 表单、Spring API、迁移后的 PostgreSQL 与客户授权恢复公开受理结果", async () => {
    const browserFetch = createCookieBrowserFetch(nativeFetch, liveBaseUrl ?? "");
    vi.spyOn(globalThis, "fetch").mockImplementation(browserFetch);
    globalThis.history.replaceState(null, "", "/help/login");

    const firstRender = render(<RootApplication />);
    expect(await screen.findByRole("heading", { name: "客户登录" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "customer-demo" } });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "local-demo-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("banner", { name: "客户帮助中心" })).toBeInTheDocument();
    expect(globalThis.location.pathname).toBe("/help");
    expect(screen.queryByRole("navigation", { name: "内部工作区" })).not.toBeInTheDocument();

    const description = `React 全栈验收 ${globalThis.crypto.randomUUID()}`;
    fireEvent.change(screen.getByLabelText("订单编号"), { target: { value: "ORDER-DELAY-001" } });
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: description } });
    fireEvent.click(screen.getByRole("button", { name: "提交物流延迟问题" }));
    const intakeHeading = await screen.findByRole("heading", {
      name: /请确认我的理解|请确认是否继续既有工单/,
    });
    if (intakeHeading.textContent === "请确认是否继续既有工单") {
      fireEvent.click(screen.getByRole("button", { name: "这是新问题，继续创建" }));
    }
    expect(await screen.findByRole("heading", { name: "请确认我的理解" })).toBeInTheDocument();
    expect(screen.queryByText("调查中")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认，就是这个问题" }));

    expect(await screen.findByText("调查中")).toBeInTheDocument();
    expect(screen.getByText(description)).toBeInTheDocument();
    const restoredUrl = globalThis.location.href;
    expect(restoredUrl).toContain("?ticket=");

    firstRender.unmount();
    render(<RootApplication />);
    expect(await screen.findByRole("banner", { name: "客户帮助中心" })).toBeInTheDocument();
    expect(await screen.findByText(description)).toBeInTheDocument();
  });

  it("客服工作台从独立 Spring 快照恢复共享队列且不公开转人工理由详情", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path =
        typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return nativeFetch(new URL(path, liveBaseUrl), init);
    });

    render(<SupportWorkbench />);

    expect(await screen.findByRole("heading", { name: "客服共享队列" })).toBeInTheDocument();
    expect(await screen.findByText("队列可发现不等于工单详情授权")).toBeInTheDocument();
    expect(
      screen.queryByText(/CUSTOMER_REQUESTED_HANDOFF|AGENT_HUMAN_HANDOFF|调查摘要/),
    ).not.toBeInTheDocument();
  });
});
