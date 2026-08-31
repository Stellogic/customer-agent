import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SupportAssistancePanel, type SupportAssistancePanelProps } from "./SupportAssistancePanel";
import {
  createSupportAssistanceState,
  reduceSupportAssistance,
  type AssistanceView,
  type SupportAssignment,
} from "./supportAssistanceState";

// 仅测试展示交互的合成 fixture；不代表真实 Agent 或检索契约、质量证据。
const assignment: SupportAssignment = {
  sessionKey: "session-a",
  ticketId: "ticket-a",
  assignmentId: "claim-1",
};
const fixture: AssistanceView = {
  status: "ready",
  kind: "draft",
  requestId: "fixture-request-1",
  text: "您好，我们会继续核实物流情况。",
  suggestions: ["人工核实签收信息"],
  citations: [
    {
      title: "合成物流政策",
      version: "fixture-v1",
      articleId: "fixture-article",
      chunkId: "fixture-chunk",
      updatedAt: "2026-08-31T01:00:00Z",
      startLine: 3,
      endLine: 5,
      snippet: "合成引用：先核实签收情况。",
      applicability: ["合成测试范围"],
    },
  ],
};

function props(content: AssistanceView = fixture): SupportAssistancePanelProps {
  let state = createSupportAssistanceState(assignment);
  if (content.status !== "idle") {
    const request = {
      assignment,
      requestId: "requestId" in content ? content.requestId : "fixture-request-1",
      kind: "kind" in content ? content.kind : ("draft" as const),
    };
    state = reduceSupportAssistance(state, { type: "start", request });
    if (content.status === "empty") state = reduceSupportAssistance(state, { type: "noMatch", request });
    else if (content.status !== "loading")
      state = reduceSupportAssistance(state, { type: "complete", request, view: content });
  }
  return { state, onReviewDraft: null };
}

function editor() {
  return screen.getByRole("textbox", { name: "内部编辑区（尚未发送）" });
}

function review() {
  fireEvent.click(screen.getByRole("checkbox", { name: "我已核实事实、政策与客户可见措辞" }));
}

describe("独立客服辅助展示与草稿", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

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
    for (const text of [
      "合成物流政策",
      "fixture-v1",
      "合成测试范围",
      "合成引用：先核实签收情况。",
      "<script>内部文本</script>",
    ]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByText("fixture-article / fixture-chunk")).toBeInTheDocument();
    expect(screen.getByText("2026-08-31T01:00:00Z")).toBeInTheDocument();
    expect(screen.getByText("3–5")).toBeInTheDocument();
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
    rerender(
      <SupportAssistancePanel
        {...props({ ...fixture, requestId: "fixture-request-2", text: "另一草稿" })}
      />,
    );
    expect(screen.queryByRole("button", { name: "确认替换" })).not.toBeInTheDocument();
    expect(editor()).toHaveValue("人工内容");
  });

  it("撤权立即卸载内容，迟到结果不会恢复；重新授权不恢复旧草稿", () => {
    const { rerender } = render(<SupportAssistancePanel {...props()} />);
    fireEvent.click(screen.getByRole("button", { name: "插入回复草稿" }));
    review();
    const denied = reduceSupportAssistance(props().state, { type: "accessDenied", assignment });
    rerender(<SupportAssistancePanel {...props()} state={denied} />);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText("合成物流政策")).not.toBeInTheDocument();
    const late = reduceSupportAssistance(denied, {
      type: "complete",
      request: props().state.request!,
      view: fixture,
    });
    rerender(<SupportAssistancePanel {...props()} state={late} />);
    expect(screen.queryByText(fixture.text)).not.toBeInTheDocument();
    const reclaimed = reduceSupportAssistance(late, {
      type: "authorize",
      assignment: { ...assignment, assignmentId: "claim-2" },
    });
    rerender(<SupportAssistancePanel {...props()} state={reclaimed} />);
    expect(editor()).toHaveValue("");
    expect(screen.queryByText("合成物流政策")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it.each([
    { ...assignment, sessionKey: "session-b" },
    { ...assignment, ticketId: "ticket-b" },
    { ...assignment, assignmentId: "claim-2" },
  ])("身份/工单/责任切换清除内容与审阅状态：%j", (nextAssignment) => {
    const { rerender } = render(<SupportAssistancePanel {...props()} />);
    fireEvent.click(screen.getByRole("button", { name: "插入回复草稿" }));
    review();
    const state = reduceSupportAssistance(props().state, {
      type: "authorize",
      assignment: nextAssignment,
    });
    rerender(<SupportAssistancePanel {...props()} state={state} />);
    expect(editor()).toHaveValue("");
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.queryByText("合成物流政策")).not.toBeInTheDocument();
  });

  it.each<AssistanceView>([
    { status: "loading", kind: "summary" },
    { status: "empty", kind: "knowledge" },
    { status: "error", reason: "conflict" },
    { status: "error", reason: "index" },
    { status: "error", reason: "model" },
    { status: "error", reason: "embedding" },
    { status: "error", reason: "retrieval" },
    { status: "error", reason: "request" },
    { status: "error", reason: "format" },
  ])("辅助状态 $status 不阻止人工继续编辑", (content) => {
    const { rerender } = render(<SupportAssistancePanel {...props()} />);
    fireEvent.change(editor(), { target: { value: "保留人工回复" } });
    rerender(<SupportAssistancePanel {...props(content)} />);
    expect(editor()).toHaveValue("保留人工回复");
    expect(editor()).toBeEnabled();
    expect(screen.queryByText("合成物流政策")).not.toBeInTheDocument();
    expect(screen.getByRole(content.status === "error" ? "alert" : "status")).toBeInTheDocument();
  });

  it("向量检索模型与回复生成模型失败展示不同原因", () => {
    const { rerender } = render(
      <SupportAssistancePanel {...props({ status: "error", reason: "embedding" })} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("知识向量模型暂不可用");
    rerender(<SupportAssistancePanel {...props({ status: "error", reason: "model" })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("回复生成模型暂不可用");
  });

  it("检索无匹配不冒称正常拒答，模型资料不足说明保留人工编辑", () => {
    const onReviewDraft = vi.fn();
    const { rerender } = render(<SupportAssistancePanel {...props()} onReviewDraft={onReviewDraft} />);
    fireEvent.change(editor(), { target: { value: "已有人工草稿" } });
    rerender(<SupportAssistancePanel {...props({ status: "empty", kind: "draft" })} onReviewDraft={onReviewDraft} />);
    expect(screen.getByRole("status")).toHaveTextContent("尚未形成回答充分性判断");
    expect(screen.queryByRole("heading", { name: "资料不足" })).not.toBeInTheDocument();
    rerender(<SupportAssistancePanel {...props({
      status: "insufficient", kind: "draft", requestId: "fixture-request-1",
      explanation: "现有资料未说明该情形的处理规则，不能据此给出结论。",
      followUp: "请确认您希望了解的是哪项规则。",
    })} onReviewDraft={onReviewDraft} />);
    expect(screen.getByRole("heading", { name: "资料不足" })).toBeInTheDocument();
    expect(screen.getByText(/可补充确认/)).toBeInTheDocument();
    expect(editor()).toHaveValue("已有人工草稿");
    expect(onReviewDraft).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "插入回复草稿" })).not.toBeInTheDocument();
  });

  it("引用超过24字符仍完整展示，不实施单条截断", () => {
    const snippet = "这是一段超过二十四个字符的合成政策引用，用于核实片段完整展示而非产品知识质量。";
    render(<SupportAssistancePanel {...props({ ...fixture, citations: [{ ...fixture.citations[0], snippet }] })} />);
    expect(screen.getByText(snippet)).toBeInTheDocument();
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
