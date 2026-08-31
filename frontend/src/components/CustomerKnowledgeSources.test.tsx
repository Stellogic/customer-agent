import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  CustomerKnowledgeSources,
  type CustomerKnowledgeSourcesState,
} from "./CustomerKnowledgeSources";

// 合成展示 fixture，仅在测试源码中使用，不代表真实检索或服务端安全校验。
const source = { title: "配送说明（测试）", updatedAt: "2026-08-01T00:00:00Z" };

describe("Issue #169 独立客户知识来源展示（未接入检索）", () => {
  afterEach(cleanup);

  it("只渲染标题和更新时间，不把内部元数据或链接转交给来源组件", () => {
    const internalExtraFields = {
      ...source,
      sourceFile: "private/policy.md",
      chunkId: "private-chunk-1",
      snippet: "不可见正文",
      score: 0.987654,
      url: "https://internal.invalid/policy",
    };
    const { container } = render(
      <CustomerKnowledgeSources state={{ status: "ready", sources: [internalExtraFields] }} />,
    );

    expect(screen.getByText(source.title)).toBeInTheDocument();
    expect(screen.getByText(source.updatedAt)).toHaveAttribute("datetime", source.updatedAt);
    expect(container).not.toHaveTextContent("private/policy.md");
    expect(container).not.toHaveTextContent("private-chunk-1");
    expect(container).not.toHaveTextContent("不可见正文");
    expect(container).not.toHaveTextContent("0.987654");
    expect(container.querySelector("[href]")).toBeNull();
    expect(container).toHaveTextContent("订单、支付和补偿结果以本工单已核验的业务事实为准");
  });

  it.each([
    ["loading", "正在确认本次回复的知识来源。"],
    ["empty", "本次回复没有可展示的知识来源。"],
    ["conflict", "知识说明与当前核验事实存在冲突"],
    ["error", "知识来源暂时不可用"],
    ["recovering", "连接恢复中"],
  ] as const)("从就绪转为 %s 时不保留旧来源", (status, message) => {
    const { rerender } = render(
      <CustomerKnowledgeSources state={{ status: "ready", sources: [source] }} />,
    );
    rerender(<CustomerKnowledgeSources state={{ status }} />);

    expect(screen.queryByText(source.title)).not.toBeInTheDocument();
    expect(screen.getByRole(status === "error" ? "alert" : "status")).toHaveTextContent(message);
    expect(screen.getByRole("region", { name: "知识来源" })).toHaveAttribute(
      "aria-busy",
      String(status === "loading" || status === "recovering"),
    );
  });

  it("恢复后仅展示调用方新传入的来源，空结果不假装有来源", () => {
    const { rerender } = render(<CustomerKnowledgeSources state={{ status: "recovering" }} />);
    const recovered: CustomerKnowledgeSourcesState = {
      status: "ready",
      sources: [{ title: "新的配送说明（测试）", updatedAt: "2026-08-02T00:00:00Z" }],
    };
    rerender(<CustomerKnowledgeSources state={recovered} />);
    expect(screen.getByText("新的配送说明（测试）")).toBeInTheDocument();
    rerender(<CustomerKnowledgeSources state={{ status: "ready", sources: [] }} />);
    expect(screen.queryByText("新的配送说明（测试）")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("没有可展示的知识来源");
  });
});
