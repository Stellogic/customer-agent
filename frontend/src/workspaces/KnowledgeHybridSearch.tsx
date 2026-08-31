import { useEffect, useRef, useState, type FormEvent } from "react";
import { Spin } from "antd";
import { humanSessionFetch } from "../humanSessionLifecycle";

type Hit = {
  chunkId: string;
  articleId: string;
  version: string;
  title: string;
  applicability: string[];
  sourceFile: string;
  startLine: number;
  endLine: number;
  snippet: string;
  score: number;
  lexicalScore: number | null;
  vectorScore: number | null;
};

type Retrieval = {
  schema: "knowledge-hybrid-v2";
  query: string;
  generation: number;
  revision: string;
  lexicalCandidates: Hit[];
  vectorCandidates: Hit[];
  results: Hit[];
};

export default function KnowledgeHybridSearch() {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("INTERNAL");
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [result, setResult] = useState<Retrieval | null>(null);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function search(event: FormEvent) {
    event.preventDefault();
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setResult(null);
    setError("");
    setState("loading");
    try {
      const parameters = new URLSearchParams({ q: query, scope });
      const response = await humanSessionFetch(`/api/internal/knowledge/search?${parameters}`, {
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
      });
      const value: unknown = await response.json();
      if (response.status === 403) throw new Error("当前身份无权检索所选适用范围。");
      if (!response.ok) {
        const stale = record(value) && value.code === "INDEX_STALE";
        throw new Error(
          stale
            ? "混合检索索引过期，请联系维护者重新准备索引。"
            : "混合检索不可用；没有返回知识结果，请稍后重试。",
        );
      }
      if (!isRetrieval(value)) throw new Error("检索返回的数据不兼容，已停止显示结果。");
      if (controller.signal.aborted) return;
      setResult(value);
      setState("ready");
    } catch (cause) {
      if (controller.signal.aborted) return;
      setError(cause instanceof Error ? cause.message : "混合检索不可用。");
      setState("error");
    }
  }

  return (
    <section className="knowledge-search-panel" aria-label="中文混合检索">
      <h2>中文混合检索</h2>
      <p>在当前身份可读、当前已发布的知识片段中检索；全文与离线 BGE 候选经 RRF 融合。</p>
      <form onSubmit={(event) => void search(event)}>
        <label htmlFor="hybrid-query">检索问题</label>
        <div className="knowledge-search-row">
          <input
            id="hybrid-query"
            maxLength={200}
            required
            value={query}
            placeholder="例如：客户问退款是不是已经到账，怎么说明？"
            onChange={(event) => setQuery(event.target.value)}
          />
          <button type="submit" disabled={state === "loading" || !query.trim()}>
            {state === "loading" ? "混合检索中…" : "混合检索"}
          </button>
        </div>
        <label htmlFor="hybrid-scope">检索适用范围</label>
        <select id="hybrid-scope" value={scope} onChange={(event) => setScope(event.target.value)}>
          <option value="INTERNAL">内部规则</option>
          <option value="SUPPORT">客服规则（需当前身份授权）</option>
          <option value="APPROVER">审批规则（需当前身份授权）</option>
        </select>
      </form>
      {state === "loading" && (
        <p role="status" aria-busy="true">
          <Spin /> 正在读取真实混合检索结果…
        </p>
      )}
      {state === "error" && <p role="alert">{error}</p>}
      {state === "ready" && result && (
        <>
          <p role="status">
            全文候选 {result.lexicalCandidates.length} · 向量候选 {result.vectorCandidates.length} ·
            索引代次 {result.generation}
          </p>
          {result.results.length === 0 ? (
            <p>当前授权范围内没有匹配的知识片段。</p>
          ) : (
            <HitList hits={result.results} label="RRF 检索片段" />
          )}
          <details>
            <summary>查看两路合法候选与分值</summary>
            <p>检索片段不代表资料足以回答问题；分值只用于排序。模型 revision：{result.revision}</p>
            <HitList hits={result.lexicalCandidates} label="全文候选" />
            <HitList hits={result.vectorCandidates} label="向量候选" />
          </details>
        </>
      )}
    </section>
  );
}

function HitList({ hits, label }: { hits: Hit[]; label: string }) {
  return (
    <ol className="knowledge-result-list" aria-label={label}>
      {hits.map((hit) => (
        <li key={hit.chunkId} className="knowledge-result-card">
          <strong>
            {hit.title} · {hit.articleId} · {hit.version}
          </strong>
          <span className="knowledge-result-meta">{hit.applicability.join("、")}</span>
          <p className="knowledge-result-snippet">{hit.snippet}</p>
          <span className="knowledge-result-citation">
            {hit.sourceFile} · 第 {hit.startLine}–{hit.endLine} 行
          </span>
          <small>
            分值 {hit.score.toFixed(5)} · 全文 {hit.lexicalScore?.toFixed(5) ?? "—"} · 向量{" "}
            {hit.vectorScore?.toFixed(5) ?? "—"}
          </small>
        </li>
      ))}
    </ol>
  );
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isHit(value: unknown): value is Hit {
  return (
    record(value) &&
    ["chunkId", "articleId", "version", "title", "sourceFile", "snippet"].every(
      (key) => typeof value[key] === "string",
    ) &&
    Array.isArray(value.applicability) &&
    value.applicability.every((item) => typeof item === "string") &&
    Number.isSafeInteger(value.startLine) &&
    Number(value.startLine) > 0 &&
    Number.isSafeInteger(value.endLine) &&
    Number(value.endLine) >= Number(value.startLine) &&
    finite(value.score) &&
    (value.lexicalScore === null || finite(value.lexicalScore)) &&
    (value.vectorScore === null || finite(value.vectorScore))
  );
}

function isRetrieval(value: unknown): value is Retrieval {
  return (
    record(value) &&
    value.schema === "knowledge-hybrid-v2" &&
    typeof value.query === "string" &&
    value.revision === "7999e1d3359715c523056ef9478215996d62a620" &&
    Number.isSafeInteger(value.generation) &&
    Number(value.generation) > 0 &&
    Array.isArray(value.results) &&
    value.results.length <= 5 &&
    value.results.every(isHit) &&
    Array.isArray(value.lexicalCandidates) &&
    value.lexicalCandidates.length <= 20 &&
    value.lexicalCandidates.every(isHit) &&
    Array.isArray(value.vectorCandidates) &&
    value.vectorCandidates.length <= 20 &&
    value.vectorCandidates.every(isHit)
  );
}
