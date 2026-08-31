import { useEffect, useState, type FormEvent } from "react";
import { Spin } from "antd";
import { StatusNotice } from "../components/SystemState";
import { humanSessionFetch } from "../humanSessionLifecycle";
import KnowledgeHybridSearch from "./KnowledgeHybridSearch";

const SCHEMA = "knowledge-catalog-v1" as const;
const CATALOG_URL = "/api/internal/knowledge";

type IndexStatus = {
  status: "EMPTY" | "READY" | "FAILED";
  generation: number;
  sourceDigest: string | null;
  indexedAt: string | null;
  updatedAt: string;
  articleCount: number;
  chunkCount: number;
  failureCode: string | null;
  failureMessage: string | null;
};

type SearchResult = {
  chunkId: string;
  articleId: string;
  version: string;
  title: string;
  updatedAt: string;
  applicability: string[];
  sourceFile: string;
  startLine: number;
  endLine: number;
  snippet: string;
  matchType: "FULL_TEXT" | "KEYWORD";
  lexicalScore: number;
};

type CatalogResponse = {
  view: "KNOWLEDGE_CATALOG";
  schema: typeof SCHEMA;
  index: IndexStatus;
  query: string;
  results: SearchResult[];
};

type ArticleVersion = {
  articleId: string;
  title: string;
  version: string;
  updatedAt: string;
  applicability: string[];
  publicationStatus: "DRAFT" | "PUBLISHED" | "RETIRED";
  current: boolean;
  sourceFile: string;
};

type Citation = {
  chunkId: string;
  articleId: string;
  version: string;
  sourceFile: string;
  startLine: number;
  endLine: number;
  applicability: string[];
  content: string;
};

type ArticleDetail = {
  articleId: string;
  title: string;
  version: string;
  updatedAt: string;
  applicability: string[];
  publicationStatus: "DRAFT" | "PUBLISHED" | "RETIRED";
  current: boolean;
  sourceFile: string;
  contentHash: string;
  body: string;
  versions: ArticleVersion[];
  chunks: Citation[];
};

type ArticleResponse = {
  view: "KNOWLEDGE_CATALOG";
  schema: typeof SCHEMA;
  index: IndexStatus;
  article: ArticleDetail;
};

export default function KnowledgeWorkspace() {
  const [query, setQuery] = useState("");
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [index, setIndex] = useState<IndexStatus | null>(null);
  const [catalogState, setCatalogState] = useState<"loading" | "ready" | "error">("loading");
  const [catalogError, setCatalogError] = useState("");
  const [detail, setDetail] = useState<ArticleDetail | null>(null);
  const [detailState, setDetailState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [detailError, setDetailError] = useState("");
  const [developmentNotice, setDevelopmentNotice] = useState("");

  useEffect(() => {
    const parameters = new URLSearchParams(globalThis.location.search);
    const articleId = parameters.get("article");
    const version = parameters.get("version");
    void loadCatalog("");
    if (articleId) void loadArticle(articleId, version);
  }, []);

  async function loadCatalog(nextQuery: string) {
    setCatalogState("loading");
    setCatalogError("");
    try {
      const url = `${CATALOG_URL}?q=${encodeURIComponent(nextQuery)}&limit=20`;
      const response = await humanSessionFetch(url, {
        credentials: "same-origin",
        cache: "no-store",
      });
      const value = (await response.json().catch(() => undefined)) as unknown;
      if (!response.ok) {
        if (isRecord(value) && isIndexStatus(value.index)) setIndex(value.index);
        throw new Error(response.status === 503 ? "知识索引当前不可用。" : "知识目录读取失败。");
      }
      const parsed = parseCatalog(value);
      if (!parsed) throw new Error("知识目录返回了不兼容的数据。");
      setCatalog(parsed);
      setIndex(parsed.index);
      setQuery(parsed.query);
      setCatalogState("ready");
    } catch (error) {
      setCatalog(null);
      setCatalogState("error");
      setCatalogError(error instanceof Error ? error.message : "知识目录暂时无法读取。");
    }
  }

  async function loadArticle(articleId: string, version: string | null = null) {
    setDetailState("loading");
    setDetailError("");
    try {
      const versionQuery = version ? `?version=${encodeURIComponent(version)}` : "";
      const response = await humanSessionFetch(
        `${CATALOG_URL}/articles/${encodeURIComponent(articleId)}${versionQuery}`,
        { credentials: "same-origin", cache: "no-store" },
      );
      const value = (await response.json().catch(() => undefined)) as unknown;
      if (!response.ok)
        throw new Error(response.status === 404 ? "知识条目不存在。" : "知识条目读取失败。");
      const parsed = parseArticleResponse(value);
      if (!parsed) throw new Error("知识条目返回了不兼容的数据。");
      setDetail(parsed.article);
      setIndex(parsed.index);
      setDetailState("ready");
      const search = new URLSearchParams(globalThis.location.search);
      search.set("article", parsed.article.articleId);
      search.set("version", parsed.article.version);
      globalThis.history.replaceState(null, "", `${globalThis.location.pathname}?${search}`);
    } catch (error) {
      setDetail(null);
      setDetailState("error");
      setDetailError(error instanceof Error ? error.message : "知识条目暂时无法读取。");
    }
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadCatalog(query);
  }

  function development(label: string) {
    setDevelopmentNotice(`${label}入口正在开发中；本次点击不会修改知识内容或发布状态。`);
  }

  const results = catalog?.results ?? [];
  const noResults = catalogState === "ready" && results.length === 0;

  return (
    <main className="knowledge-workspace" aria-label="知识目录工作区">
      <header className="knowledge-header">
        <div>
          <p className="eyebrow">KNOWLEDGE CATALOG</p>
          <h1>版本化知识目录</h1>
          <p className="knowledge-lede">
            从真实中文 Markdown 条目检索规则说明，查看版本、适用范围和可回到源文件的引用片段。
          </p>
        </div>
        <IndexBadge index={index} />
      </header>

      <KnowledgeHybridSearch />

      <section className="knowledge-search-panel" aria-label="知识检索">
        <form onSubmit={submitSearch} role="search">
          <label htmlFor="knowledge-query">关键词</label>
          <div className="knowledge-search-row">
            <input
              id="knowledge-query"
              aria-label="关键词"
              maxLength={200}
              placeholder="例如：物流延迟、部分退款"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <button type="submit" disabled={catalogState === "loading"}>
              {catalogState === "loading" ? "正在检索…" : "检索知识"}
            </button>
          </div>
        </form>
        <p className="knowledge-search-hint">
          普通检索只使用当前已发布版本；历史版本需要从条目详情进入审计查看。
        </p>
      </section>

      {developmentNotice && (
        <p className="knowledge-development-note" role="status">
          {developmentNotice}
        </p>
      )}
      {catalogState === "error" && (
        <StatusNotice role="alert" tone="danger" className="knowledge-status-notice">
          {catalogError || "知识目录暂时无法读取。"}
        </StatusNotice>
      )}
      {catalogState === "loading" && (
        <section className="knowledge-loading" aria-busy="true" aria-label="正在读取知识目录">
          <Spin />
          <span>正在读取真实知识索引…</span>
        </section>
      )}

      <div className="knowledge-layout">
        <section
          className="knowledge-results"
          aria-labelledby="knowledge-results-title"
          aria-busy={catalogState === "loading"}
        >
          <header className="knowledge-section-header">
            <div>
              <p className="eyebrow">SEARCH RESULTS</p>
              <h2 id="knowledge-results-title">
                {query ? `“${query}”的当前结果` : "当前知识条目"}
              </h2>
            </div>
            <span>{catalogState === "ready" ? `${results.length} 条引用` : "—"}</span>
          </header>
          {catalogState === "error" ? (
            <div className="knowledge-empty" role="status">
              <span aria-hidden="true">!</span>
              <h3>当前无法显示检索结果</h3>
              <p>请根据上方提示恢复知识索引后再试。</p>
            </div>
          ) : noResults ? (
            <div className="knowledge-empty" role="status">
              <span aria-hidden="true">⌕</span>
              <h3>{query ? "没有匹配的当前知识条目" : "知识目录为空"}</h3>
              <p>
                {query
                  ? "换一个关键词，或确认当前身份的适用范围。"
                  : "当前没有可检索的已发布版本。"}
              </p>
            </div>
          ) : (
            <ol className="knowledge-result-list">
              {results.map((result) => (
                <li key={result.chunkId}>
                  <button
                    type="button"
                    className={`knowledge-result-card${detail?.articleId === result.articleId && detail.version === result.version ? " selected" : ""}`}
                    onClick={() => void loadArticle(result.articleId, result.version)}
                  >
                    <span className="knowledge-result-topline">
                      <strong>{result.title}</strong>
                      <span>{result.version}</span>
                    </span>
                    <span className="knowledge-result-meta">
                      {result.articleId} · {result.applicability.join("、")} · 更新于{" "}
                      {formatDate(result.updatedAt)}
                    </span>
                    <span className="knowledge-result-snippet">{result.snippet}</span>
                    <span className="knowledge-result-citation">
                      {result.sourceFile} · 第 {result.startLine}–{result.endLine} 行 ·{" "}
                      {result.matchType === "KEYWORD" ? "关键词命中" : "全文命中"}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </section>

        <aside className="knowledge-detail-panel" aria-label="知识条目详情">
          {detailState === "idle" && (
            <div className="knowledge-detail-placeholder">
              <span aria-hidden="true">↳</span>
              <p className="eyebrow">ARTICLE DETAIL</p>
              <h2>选择一条知识引用</h2>
              <p>这里会展示真实正文、可审计版本以及每个分段的源文件位置。</p>
            </div>
          )}
          {detailState === "loading" && (
            <div className="knowledge-detail-placeholder" aria-busy="true" role="status">
              <Spin />
              <h2>正在读取条目…</h2>
            </div>
          )}
          {detailState === "error" && (
            <div className="knowledge-detail-placeholder knowledge-detail-error" role="alert">
              <span aria-hidden="true">!</span>
              <h2>条目暂时无法读取</h2>
              <p>{detailError}</p>
            </div>
          )}
          {detailState === "ready" && detail && (
            <ArticleDetail article={detail} onVersion={loadArticle} />
          )}
        </aside>
      </div>

      <section
        className="knowledge-development-panel"
        aria-labelledby="knowledge-development-title"
      >
        <div>
          <p className="eyebrow">OPERATIONS ROADMAP</p>
          <h2 id="knowledge-development-title">内容运营入口</h2>
          <p>第一阶段只提供真实查看、检索、版本和引用；内容变更仍通过仓库审阅。</p>
        </div>
        <div className="knowledge-development-actions">
          {(["编辑", "审核", "发布", "回滚", "重建索引"] as const).map((label) => (
            <button key={label} type="button" onClick={() => development(label)}>
              {label}（开发中）
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}

function IndexBadge({ index }: { index: IndexStatus | null }) {
  if (!index) return <span className="knowledge-index-badge busy">正在确认索引…</span>;
  const label =
    index.status === "READY"
      ? `索引就绪 · ${index.articleCount} 条目`
      : index.status === "EMPTY"
        ? "索引为空"
        : "索引需要修复";
  return <span className={`knowledge-index-badge ${index.status.toLowerCase()}`}>{label}</span>;
}

function ArticleDetail({
  article,
  onVersion,
}: {
  article: ArticleDetail;
  onVersion: (articleId: string, version: string) => Promise<void> | void;
}) {
  return (
    <article className="knowledge-article" aria-labelledby="knowledge-article-title">
      <header className="knowledge-article-header">
        <p className="eyebrow">{article.current ? "CURRENT PUBLISHED" : "AUDIT VERSION"}</p>
        <h2 id="knowledge-article-title">{article.title}</h2>
        <p>
          {article.articleId} · {article.version} · 更新于 {formatDate(article.updatedAt)}
        </p>
        {!article.current && (
          <span className="knowledge-old-version">旧版本，仅供审计，不进入普通检索</span>
        )}
      </header>
      <dl className="knowledge-article-facts">
        <div>
          <dt>适用范围</dt>
          <dd>{article.applicability.join("、")}</dd>
        </div>
        <div>
          <dt>发布状态</dt>
          <dd>{article.publicationStatus}</dd>
        </div>
        <div>
          <dt>源文件</dt>
          <dd>{article.sourceFile}</dd>
        </div>
        <div>
          <dt>内容校验</dt>
          <dd>{article.contentHash.slice(0, 12)}…</dd>
        </div>
      </dl>
      <section className="knowledge-version-section" aria-labelledby="knowledge-version-title">
        <header>
          <p className="eyebrow">VERSION HISTORY</p>
          <h3 id="knowledge-version-title">版本审计</h3>
        </header>
        <div className="knowledge-version-list">
          {article.versions.map((version) => (
            <button
              key={`${version.articleId}-${version.version}`}
              type="button"
              className={version.version === article.version ? "current" : ""}
              onClick={() => void onVersion(version.articleId, version.version)}
            >
              <strong>{version.version}</strong>
              <span>
                {version.current ? "当前" : "历史"} · {version.publicationStatus}
              </span>
              <small>{formatDate(version.updatedAt)}</small>
            </button>
          ))}
        </div>
      </section>
      <section className="knowledge-body-section" aria-labelledby="knowledge-body-title">
        <header>
          <p className="eyebrow">SOURCE CONTENT</p>
          <h3 id="knowledge-body-title">正文</h3>
        </header>
        <div className="knowledge-markdown">
          {article.body.split("\n").map((line, index) => (
            <p key={`${index}-${line}`}>{line || " "}</p>
          ))}
        </div>
      </section>
      <section className="knowledge-citation-section" aria-labelledby="knowledge-citation-title">
        <header>
          <p className="eyebrow">TRACEABLE CITATIONS</p>
          <h3 id="knowledge-citation-title">引用分段</h3>
        </header>
        <ol className="knowledge-citation-list">
          {article.chunks.map((chunk) => (
            <li key={chunk.chunkId}>
              <div>
                <strong>{chunk.sourceFile}</strong>
                <span>
                  第 {chunk.startLine}–{chunk.endLine} 行 · {chunk.applicability.join("、")}
                </span>
              </div>
              <p>{chunk.content}</p>
              <small>{chunk.chunkId}</small>
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}

function parseCatalog(value: unknown): CatalogResponse | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ["view", "schema", "index", "query", "results"]))
    return null;
  if (
    value.view !== "KNOWLEDGE_CATALOG" ||
    value.schema !== SCHEMA ||
    typeof value.query !== "string" ||
    !isIndexStatus(value.index) ||
    !Array.isArray(value.results) ||
    !value.results.every(isSearchResult)
  )
    return null;
  return value as unknown as CatalogResponse;
}

function parseArticleResponse(value: unknown): ArticleResponse | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ["view", "schema", "index", "article"])) return null;
  if (
    value.view !== "KNOWLEDGE_CATALOG" ||
    value.schema !== SCHEMA ||
    !isIndexStatus(value.index) ||
    !isArticleDetail(value.article)
  )
    return null;
  return value as unknown as ArticleResponse;
}

function isIndexStatus(value: unknown): value is IndexStatus {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "status",
      "generation",
      "sourceDigest",
      "indexedAt",
      "updatedAt",
      "articleCount",
      "chunkCount",
      "failureCode",
      "failureMessage",
    ]) &&
    ["EMPTY", "READY", "FAILED"].includes(String(value.status)) &&
    Number.isSafeInteger(value.generation) &&
    Number(value.generation) >= 0 &&
    (typeof value.sourceDigest === "string" || value.sourceDigest === null) &&
    (typeof value.indexedAt === "string" || value.indexedAt === null) &&
    typeof value.updatedAt === "string" &&
    Number.isSafeInteger(value.articleCount) &&
    Number(value.articleCount) >= 0 &&
    Number.isSafeInteger(value.chunkCount) &&
    Number(value.chunkCount) >= 0 &&
    (typeof value.failureCode === "string" || value.failureCode === null) &&
    (typeof value.failureMessage === "string" || value.failureMessage === null)
  );
}

function isSearchResult(value: unknown): value is SearchResult {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "chunkId",
      "articleId",
      "version",
      "title",
      "updatedAt",
      "applicability",
      "sourceFile",
      "startLine",
      "endLine",
      "snippet",
      "matchType",
      "lexicalScore",
    ]) &&
    typeof value.chunkId === "string" &&
    typeof value.articleId === "string" &&
    typeof value.version === "string" &&
    typeof value.title === "string" &&
    typeof value.updatedAt === "string" &&
    Array.isArray(value.applicability) &&
    value.applicability.every((entry) => typeof entry === "string") &&
    typeof value.sourceFile === "string" &&
    Number.isSafeInteger(value.startLine) &&
    Number.isSafeInteger(value.endLine) &&
    typeof value.snippet === "string" &&
    ["FULL_TEXT", "KEYWORD"].includes(String(value.matchType)) &&
    typeof value.lexicalScore === "number"
  );
}

function isArticleDetail(value: unknown): value is ArticleDetail {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "articleId",
      "title",
      "version",
      "updatedAt",
      "applicability",
      "publicationStatus",
      "current",
      "sourceFile",
      "contentHash",
      "body",
      "versions",
      "chunks",
    ]) &&
    typeof value.articleId === "string" &&
    typeof value.title === "string" &&
    typeof value.version === "string" &&
    typeof value.updatedAt === "string" &&
    Array.isArray(value.applicability) &&
    value.applicability.every((entry) => typeof entry === "string") &&
    ["DRAFT", "PUBLISHED", "RETIRED"].includes(String(value.publicationStatus)) &&
    typeof value.current === "boolean" &&
    typeof value.sourceFile === "string" &&
    typeof value.contentHash === "string" &&
    typeof value.body === "string" &&
    Array.isArray(value.versions) &&
    value.versions.every(isArticleVersion) &&
    Array.isArray(value.chunks) &&
    value.chunks.every(isCitation)
  );
}

function isArticleVersion(value: unknown): value is ArticleVersion {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "articleId",
      "title",
      "version",
      "updatedAt",
      "applicability",
      "publicationStatus",
      "current",
      "sourceFile",
    ]) &&
    typeof value.articleId === "string" &&
    typeof value.title === "string" &&
    typeof value.version === "string" &&
    typeof value.updatedAt === "string" &&
    Array.isArray(value.applicability) &&
    value.applicability.every((entry) => typeof entry === "string") &&
    ["DRAFT", "PUBLISHED", "RETIRED"].includes(String(value.publicationStatus)) &&
    typeof value.current === "boolean" &&
    typeof value.sourceFile === "string"
  );
}

function isCitation(value: unknown): value is Citation {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "chunkId",
      "articleId",
      "version",
      "sourceFile",
      "startLine",
      "endLine",
      "applicability",
      "content",
    ]) &&
    typeof value.chunkId === "string" &&
    typeof value.articleId === "string" &&
    typeof value.version === "string" &&
    typeof value.sourceFile === "string" &&
    Number.isSafeInteger(value.startLine) &&
    Number.isSafeInteger(value.endLine) &&
    Array.isArray(value.applicability) &&
    value.applicability.every((entry) => typeof entry === "string") &&
    typeof value.content === "string"
  );
}

function hasOnlyKeys(value: Record<string, unknown>, keys: string[]) {
  return Object.keys(value).every((key) => keys.includes(key)) && keys.every((key) => key in value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(date);
}
