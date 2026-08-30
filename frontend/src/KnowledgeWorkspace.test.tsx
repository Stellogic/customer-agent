import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import KnowledgeWorkspace from "./workspaces/KnowledgeWorkspace";

vi.mock("./csrf", () => ({
  loadCsrfToken: async () => ({ token: "knowledge-csrf", headerName: "X-CSRF-TOKEN" }),
}));

const READY_INDEX = {
  status: "READY" as const,
  generation: 2,
  sourceDigest: "a".repeat(64),
  indexedAt: "2026-08-28T00:00:00Z",
  updatedAt: "2026-08-28T00:00:00Z",
  articleCount: 1,
  chunkCount: 1,
  failureCode: null,
  failureMessage: null,
};

const SEARCH_RESULT = {
  chunkId: `chunk-${"b".repeat(64)}`,
  articleId: "logistics-delay",
  version: "v2",
  title: "物流延迟处理说明",
  updatedAt: "2026-08-28T00:00:00Z",
  applicability: ["INTERNAL", "SUPPORT"],
  sourceFile: "knowledge/logistics-delay-v2.md",
  startLine: 10,
  endLine: 14,
  snippet: "物流节点超过承诺时间没有更新时，先核对订单与物流的当前权威状态。",
  matchType: "KEYWORD" as const,
  lexicalScore: 1.2,
};

const CURRENT_ARTICLE = {
  articleId: "logistics-delay",
  title: "物流延迟处理说明",
  version: "v2",
  updatedAt: "2026-08-28T00:00:00Z",
  applicability: ["INTERNAL", "SUPPORT"],
  publicationStatus: "PUBLISHED" as const,
  current: true,
  sourceFile: "knowledge/logistics-delay-v2.md",
  contentHash: "c".repeat(64),
  body: "物流节点超过承诺时间没有更新时，先核对订单与物流的当前权威状态。",
  versions: [
    {
      articleId: "logistics-delay",
      title: "物流延迟处理说明",
      version: "v2",
      updatedAt: "2026-08-28T00:00:00Z",
      applicability: ["INTERNAL", "SUPPORT"],
      publicationStatus: "PUBLISHED" as const,
      current: true,
      sourceFile: "knowledge/logistics-delay-v2.md",
    },
    {
      articleId: "logistics-delay",
      title: "物流延迟处理说明",
      version: "v1",
      updatedAt: "2026-08-20T00:00:00Z",
      applicability: ["INTERNAL", "SUPPORT"],
      publicationStatus: "RETIRED" as const,
      current: false,
      sourceFile: "knowledge/logistics-delay-v1.md",
    },
  ],
  chunks: [
    {
      chunkId: SEARCH_RESULT.chunkId,
      articleId: "logistics-delay",
      version: "v2",
      sourceFile: "knowledge/logistics-delay-v2.md",
      startLine: 10,
      endLine: 14,
      applicability: ["INTERNAL", "SUPPORT"],
      content: SEARCH_RESULT.snippet,
    },
  ],
};

describe("版本化知识目录工作区", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    globalThis.history.replaceState(null, "", "/");
  });

  it("读取中显示 loading，就绪后展示真实检索结果", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise((resolve) => {
          globalThis.setTimeout(
            () =>
              resolve(
                Response.json({
                  view: "KNOWLEDGE_CATALOG",
                  schema: "knowledge-catalog-v1",
                  index: READY_INDEX,
                  query: "",
                  results: [SEARCH_RESULT],
                }),
              ),
            0,
          );
        }),
    );

    render(<KnowledgeWorkspace />);

    expect(screen.getByRole("region", { name: "正在读取知识目录" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /物流延迟处理说明/ })).toBeInTheDocument();
    expect(
      screen.getByText("knowledge/logistics-delay-v2.md · 第 10–14 行 · 关键词命中"),
    ).toBeInTheDocument();
  });

  it("空目录显示明确空状态", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      Response.json({
        view: "KNOWLEDGE_CATALOG",
        schema: "knowledge-catalog-v1",
        index: { ...READY_INDEX, articleCount: 0, chunkCount: 0 },
        query: "",
        results: [],
      }),
    );

    render(<KnowledgeWorkspace />);
    expect(await screen.findByRole("heading", { name: "知识目录为空" })).toBeInTheDocument();
  });

  it("无匹配关键词显示无结果状态", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        Response.json({
          view: "KNOWLEDGE_CATALOG",
          schema: "knowledge-catalog-v1",
          index: READY_INDEX,
          query: "",
          results: [SEARCH_RESULT],
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          view: "KNOWLEDGE_CATALOG",
          schema: "knowledge-catalog-v1",
          index: READY_INDEX,
          query: "不存在的词",
          results: [],
        }),
      );

    render(<KnowledgeWorkspace />);
    fireEvent.change(await screen.findByLabelText("关键词"), { target: { value: "不存在的词" } });
    fireEvent.submit(screen.getByRole("search"));
    expect(
      await screen.findByRole("heading", { name: "没有匹配的当前知识条目" }),
    ).toBeInTheDocument();
  });

  it("索引不可用时显示错误状态", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      Response.json(
        {
          code: "KNOWLEDGE_INDEX_UNAVAILABLE",
          message: "知识索引当前不可用，请稍后重试",
          index: { ...READY_INDEX, status: "FAILED" },
        },
        { status: 503 },
      ),
    );

    render(<KnowledgeWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent("知识索引当前不可用。");
    expect(screen.getByRole("heading", { name: "当前无法显示检索结果" })).toBeInTheDocument();
  });

  it("旧版本详情标明仅供审计，开发中入口不写入", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        Response.json({
          view: "KNOWLEDGE_CATALOG",
          schema: "knowledge-catalog-v1",
          index: READY_INDEX,
          query: "",
          results: [SEARCH_RESULT],
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          view: "KNOWLEDGE_CATALOG",
          schema: "knowledge-catalog-v1",
          index: READY_INDEX,
          article: {
            ...CURRENT_ARTICLE,
            version: "v1",
            current: false,
            publicationStatus: "RETIRED",
            sourceFile: "knowledge/logistics-delay-v1.md",
            body: "旧版本规则只用于审计历史回复，不作为当前处理依据。",
          },
        }),
      );

    render(<KnowledgeWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: /物流延迟处理说明/ }));
    expect(await screen.findByText("旧版本，仅供审计，不进入普通检索")).toBeInTheDocument();

    const writesBefore = vi.mocked(globalThis.fetch).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "编辑（开发中）" }));
    fireEvent.click(screen.getByRole("button", { name: "审核（开发中）" }));
    fireEvent.click(screen.getByRole("button", { name: "发布（开发中）" }));
    fireEvent.click(screen.getByRole("button", { name: "回滚（开发中）" }));
    fireEvent.click(screen.getByRole("button", { name: "重建索引（开发中）" }));
    expect(screen.getByRole("status")).toHaveTextContent("重建索引入口正在开发中");
    expect(vi.mocked(globalThis.fetch).mock.calls.length).toBe(writesBefore);
  });
});
