import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import CustomerHelpDocs from "./CustomerHelpDocs";

describe("Issue #192 客户帮助文档页", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("真实帮助内容连接到帮助中心，并区分 Agent 建议、人工责任与补偿状态", () => {
    render(
      <MemoryRouter>
        <CustomerHelpDocs />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "客户帮助中心信任说明" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回帮助中心" })).toHaveAttribute("href", "/help");
    expect(document.getElementById("ai")).toHaveTextContent("Agent 建议");
    expect(document.getElementById("ai")).toHaveTextContent("没有审批权");
    expect(document.getElementById("human")).toHaveTextContent("公开回复责任属于负责客服");
    expect(document.getElementById("human")).toHaveTextContent("不能越过人工责任");
    expect(document.getElementById("compensation")).toHaveTextContent("待审批");
    expect(document.getElementById("compensation")).toHaveTextContent("已批准");
    expect(document.getElementById("compensation")).toHaveTextContent("已执行");
    expect(document.getElementById("compensation")).toHaveTextContent(
      "不会在客户帮助中心显示为已经获得补偿",
    );
    expect(screen.queryByText("通常 24 小时内回复")).not.toBeInTheDocument();
  });

  it("未实现内容点击显示开发中且不发送写请求", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(
      <MemoryRouter>
        <CustomerHelpDocs />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "服务时间承诺（开发中）" }));
    expect(screen.getByRole("status")).toHaveTextContent("服务时间承诺入口正在开发中");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["ai", "AI 调查只提供建议"],
    ["human", "人工客服承担公开回复责任"],
    ["compensation", "待审批还不是已经获得补偿"],
  ])("打开 #%s 说明时将焦点移到对应章节", (anchor, name) => {
    render(
      <MemoryRouter initialEntries={[`/help/docs#${anchor}`]}>
        <CustomerHelpDocs />
      </MemoryRouter>,
    );

    expect(screen.getByRole("region", { name })).toHaveFocus();
  });
});
