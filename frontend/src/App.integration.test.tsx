import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
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
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return nativeFetch(new URL(path, liveBaseUrl), init);
    });

    const description = `React 全栈验收 ${globalThis.crypto.randomUUID()}`;
    const firstRender = render(<App />);
    fireEvent.change(screen.getByLabelText("订单编号"), { target: { value: "ORDER-DELAY-001" } });
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: description } });
    fireEvent.click(screen.getByRole("button", { name: "提交物流延迟问题" }));

    expect(await screen.findByText("调查中")).toBeInTheDocument();
    expect(screen.getByText(description)).toBeInTheDocument();
    const restoredUrl = globalThis.location.href;
    expect(restoredUrl).toContain("?ticket=");

    firstRender.unmount();
    render(<App />);
    expect(await screen.findByText(description)).toBeInTheDocument();
  });

  it("客服工作台从独立 Spring 快照恢复共享队列且不公开转人工理由详情", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return nativeFetch(new URL(path, liveBaseUrl), init);
    });

    render(<SupportWorkbench supportId="support-demo" />);

    expect(await screen.findByRole("heading", { name: "客服共享队列" })).toBeInTheDocument();
    expect(await screen.findByText("队列可发现不等于工单详情授权")).toBeInTheDocument();
    expect(screen.queryByText(/CUSTOMER_REQUESTED_HANDOFF|AGENT_HUMAN_HANDOFF|调查摘要/)).not.toBeInTheDocument();
  });
});
