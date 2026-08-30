import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CustomerCapabilityGuide, CustomerTrustStrip } from "./CustomerHelpTrust";

describe("Issue #192 客户帮助信任说明与能力边界", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("帮助中心呈现信任说明以及 AI、人工、补偿三块边界", () => {
    render(
      <MemoryRouter>
        <CustomerTrustStrip />
        <CustomerCapabilityGuide />
      </MemoryRouter>,
    );

    const trust = screen.getByRole("region", { name: "信任说明" });
    expect(trust).toHaveTextContent("确认后才创建工单");
    expect(trust).toHaveTextContent("不承诺回复时限");
    expect(screen.getByRole("heading", { name: "AI 调查" })).toBeInTheDocument();
    expect(screen.getByText("建议，不是决定")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "人工客服" })).toBeInTheDocument();
    expect(screen.getByText("人工承担责任")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "补偿审批" })).toBeInTheDocument();
    expect(screen.getByText("待审批不是已获赔")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "阅读 AI 说明" })).toHaveAttribute(
      "href",
      "/help/docs#ai",
    );
    expect(screen.getByRole("link", { name: "阅读人工说明" })).toHaveAttribute(
      "href",
      "/help/docs#human",
    );
    expect(screen.getByRole("link", { name: "阅读补偿说明" })).toHaveAttribute(
      "href",
      "/help/docs#compensation",
    );
  });

  it("未实现帮助条目点击只显示开发中且不发送写请求", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(
      <MemoryRouter>
        <CustomerCapabilityGuide />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "补偿到账明细（开发中）" }));

    expect(screen.getByRole("status")).toHaveTextContent(
      "补偿到账明细入口正在开发中；本次点击不会发送写请求，也不会改变工单或补偿状态。",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
