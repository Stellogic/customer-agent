import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SupportAssistancePanel,
  type AssistanceView,
  type SupportAssistancePanelProps,
} from "./SupportAssistancePanel";

// 仅测试展示交互的合成 fixture；不代表真实 Agent 或检索契约、质量证据。
const projectionKey = "session-a/ticket-a/claim-1";
const fixture: AssistanceView = {
  status: "ready",
  kind: "draft",
  requestId: "fixture-request-1",
  text: "您好，我们会继续核实物流情况。",
  suggestions: ["人工核实签收信息"],
  citations: [{
    title: "合成物流政策",
    version: "fixture-v1",
    articleId: "fixture-article",
    chunkId: "fixture-chunk",
    snippet: "合成引用：先核实签收情况。",
    applicability: ["合成测试范围"],
  }],
};

function props(content: AssistanceView = fixture): SupportAssistancePanelProps {
  return { projectionKey, view: { projectionKey, content }, onReviewDraft: null };
}

function editor() {
  return screen.getByRole("textbox", { name: "内部编辑区（尚未发送）" });
}

function review() {
  fireEvent.click(screen.getByRole("checkbox", { name: "我已核实事实、政策与客户可见措辞" }));
}

describe("独立客服辅助展示与草稿", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("四类入口仅反馈开发中，不发请求或传出草稿", () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const onReviewDraft = vi.fn();
    render(<SupportAssistancePanel {...props({ status: "idle" })} onReviewDraft={onReviewDraft} />);
    for (const label of ["工单总结", "知识检索", "政策查询", "回复草稿"]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(screen.getByText(`${label}接入开发中，未发起 Agent 请求。`)).toBeInTheDocument();
    }
    expect(fetch).not.toHaveBeenCalled();
    expect(onReviewDraft).not.toHaveBeenCalled();
  });

  it("展示内部引用，只呈现显式字段且不解释 HTML", () => {
    const content = {
      ...fixture,
      text: "<script>内部文本</script>",
      prompt: "不应呈现的 prompt",
      rawRetrieval: "不应呈现的原始载荷",
    };
    const { container } = render(<SupportAssistancePanel {...props(content)} />);
    for (const text of ["合成物流政策", "fixture-v1", "合成测试范围", "合成引用：先核实签收情况。", "<script>内部文本</script>"]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByText("fixture-article / fixture-chunk")).toBeInTheDocument();
    expect(screen.queryByText("不应呈现的 prompt")).not.toBeInTheDocument();
    expect(screen.queryByText("不应呈现的原始载荷")).not.toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.queryByRole("button", { name: "执行" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "转审批" })).not.toBeInTheDocument();
  });

  it("结果不会自动填入草稿，编辑后必须重新审阅，仅传出人工文本", () => {
    const onReviewDraft = vi.fn();
    render(<SupportAssistancePanel {...props()} onReviewDraft={onReviewDraft} />);
    expect(editor()).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "插入回复草稿" }));
    expect(editor()).toHaveValue(fixture.text);
    const handoff = screen.getByRole("button", { name: "交给人工发送区" });
    expect(handoff).toBeDisabled();
    review();
    expect(handoff).toBeEnabled();
    fireEvent.change(editor(), { target: { value: "人工修订后的客户回复" } });
    expect(handoff).toBeDisabled();
    review();
    fireEvent.click(handoff);
    expect(onReviewDraft).toHaveBeenCalledExactlyOnceWith("人工修订后的客户回复");
    expect(handoff).toBeDisabled();
    expect(screen.getByText(/仍需在那里显式发送/)).toBeInTheDocument();
  });

  it("不能覆盖正在编辑的草稿，替换需要再次确认", () => {
    render(<SupportAssistancePanel {...props()} />);
    fireEvent.change(editor(), { target: { value: "保留人工编辑" } });
    fireEvent.click(screen.getByRole("button", { name: "插入回复草稿" }));
    expect(editor()).toHaveValue("保留人工编辑");
    fireEvent.click(screen.getByRole("button", { name: "保留当前编辑" }));
    expect(editor()).toHaveValue("保留人工编辑");
    fireEvent.click(screen.getByRole("button", { name: "插入回复草稿" }));
    fireEvent.click(screen.getByRole("button", { name: "确认替换" }));
    expect(editor()).toHaveValue(fixture.text);
  });

  it("新的辅助结果不覆盖人工编辑，也不沿用旧结果的替换确认", () => {
    const { rerender } = render(<SupportAssistancePanel {...props()} />);
    fireEvent.change(editor(), { target: { value: "人工内容" } });
    fireEvent.click(screen.getByRole("button", { name: "插入回复草稿" }));
    rerender(<SupportAssistancePanel {...props({ ...fixture, requestId: "fixture-request-2", text: "另一草稿" })} />);
    expect(screen.queryByRole("button", { name: "确认替换" })).not.toBeInTheDocument();
    expect(editor()).toHaveValue("人工内容");
  });

  it("撤权立即卸载内容，迟到结果不会恢复；重新授权不恢复旧草稿", () => {
    const { rerender } = render(<SupportAssistancePanel {...props()} />);
    fireEvent.click(screen.getByRole("button", { name: "插入回复草稿" }));
    review();
    rerender(<SupportAssistancePanel {...props()} projectionKey={null} />);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText("合成物流政策")).not.toBeInTheDocument();
    rerender(<SupportAssistancePanel {...props()} projectionKey={null} />);
    expect(screen.queryByText(fixture.text)).not.toBeInTheDocument();
    rerender(<SupportAssistancePanel {...props()} projectionKey="session-a/ticket-a/claim-2" />);
    expect(editor()).toHaveValue("");
    expect(screen.queryByText("合成物流政策")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it.each(["session-b/ticket-a/claim-1", "session-a/ticket-b/claim-1", "session-a/ticket-a/claim-2"])(
    "身份/工单/责任切换清除内容与审阅状态：%s", (nextKey) => {
      const { rerender } = render(<SupportAssistancePanel {...props()} />);
      fireEvent.click(screen.getByRole("button", { name: "插入回复草稿" }));
      review();
      rerender(<SupportAssistancePanel {...props()} projectionKey={nextKey} />);
      expect(editor()).toHaveValue("");
      expect(screen.getByRole("checkbox")).not.toBeChecked();
      expect(screen.queryByText("合成物流政策")).not.toBeInTheDocument();
    },
  );

  it.each<AssistanceView>([
    { status: "loading", kind: "summary" },
    { status: "empty", kind: "knowledge" },
    { status: "error", reason: "conflict" },
    { status: "error", reason: "index" },
    { status: "error", reason: "model" },
  ])("辅助状态 $status 不阻止人工继续编辑", (content) => {
    const { rerender } = render(<SupportAssistancePanel {...props()} />);
    fireEvent.change(editor(), { target: { value: "保留人工回复" } });
    rerender(<SupportAssistancePanel {...props(content)} />);
    expect(editor()).toHaveValue("保留人工回复");
    expect(editor()).toBeEnabled();
    expect(screen.queryByText("合成物流政策")).not.toBeInTheDocument();
    expect(screen.getByRole(content.status === "error" ? "alert" : "status")).toBeInTheDocument();
  });

  it("未接线/人工发送未确认时不能移交；空白与超长草稿不能插入", () => {
    const { rerender } = render(<SupportAssistancePanel {...props()} />);
    fireEvent.change(editor(), { target: { value: "人工内容" } });
    review();
    expect(screen.getByRole("button", { name: "交给人工发送区" })).toBeDisabled();
    rerender(<SupportAssistancePanel {...props({ ...fixture, text: " ".repeat(3) })} />);
    expect(screen.getByRole("button", { name: "插入回复草稿" })).toBeDisabled();
    rerender(<SupportAssistancePanel {...props({ ...fixture, text: "字".repeat(2001) })} />);
    expect(screen.getByRole("button", { name: "插入回复草稿" })).toBeDisabled();
    expect(editor()).toHaveValue("人工内容");
  });
});
