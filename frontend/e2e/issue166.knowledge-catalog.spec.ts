import { expect, test, type Page } from "@playwright/test";
import { newIssue80Context } from "./support/browser-context";

const SUPPORT_SESSION = {
  id: "support-demo",
  displayName: "演示客服",
  subjectType: "INTERNAL",
  roles: ["SUPPORT"],
  capabilities: ["SUPPORT_WORKBENCH_ACCESS", "KNOWLEDGE_READ_ACCESS"],
};

const READY_INDEX = {
  status: "READY",
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
  matchType: "KEYWORD",
  lexicalScore: 1.2,
};

const ARTICLE = {
  articleId: "logistics-delay",
  title: "物流延迟处理说明",
  version: "v2",
  updatedAt: "2026-08-28T00:00:00Z",
  applicability: ["INTERNAL", "SUPPORT"],
  publicationStatus: "PUBLISHED",
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
      publicationStatus: "PUBLISHED",
      current: true,
      sourceFile: "knowledge/logistics-delay-v2.md",
    },
    {
      articleId: "logistics-delay",
      title: "物流延迟处理说明",
      version: "v1",
      updatedAt: "2026-08-20T00:00:00Z",
      applicability: ["INTERNAL", "SUPPORT"],
      publicationStatus: "RETIRED",
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

async function fulfillSession(page: Page) {
  await page.route("**/api/auth/session", (route) =>
    route.fulfill({ json: SUPPORT_SESSION, headers: { "cache-control": "no-store" } }),
  );
}

function catalog(query: string, results: unknown[]) {
  return {
    view: "KNOWLEDGE_CATALOG",
    schema: "knowledge-catalog-v1",
    index: READY_INDEX,
    query,
    results,
  };
}

test.describe("Issue #166 知识目录桌面与窄屏状态", () => {
  test("桌面视口覆盖 loading、empty、error、无结果、旧版本和开发中", async ({
    browser,
  }, testInfo) => {
    const context = await newIssue80Context(browser, { viewport: { width: 1440, height: 900 } });
    await coverKnowledgeStates(await context.newPage(), testInfo, "desktop");
    await context.close();
  });

  test("窄屏视口覆盖 loading、empty、error、无结果、旧版本和开发中", async ({
    browser,
  }, testInfo) => {
    const context = await newIssue80Context(browser, { viewport: { width: 390, height: 844 } });
    await coverKnowledgeStates(await context.newPage(), testInfo, "narrow");
    await context.close();
  });
});

async function coverKnowledgeStates(
  page: Page,
  testInfo: { outputPath: (name: string) => string },
  label: "desktop" | "narrow",
) {
  await fulfillSession(page);

  let releaseCatalog: (() => void) | undefined;
  await page.route("**/api/internal/knowledge?**", async (route) => {
    if (!releaseCatalog) {
      await new Promise<void>((resolve) => {
        releaseCatalog = resolve;
      });
    }
    await route.fulfill({ json: catalog("", [SEARCH_RESULT]) });
  });
  await page.goto("/internal/knowledge", { waitUntil: "domcontentloaded" });
  await expect(page.getByLabel("正在读取知识目录")).toBeVisible();
  releaseCatalog?.();
  await expect(page.getByRole("button", { name: /物流延迟处理说明/ })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath(`${label}-ready.png`) });

  await page.unroute("**/api/internal/knowledge?**");
  await page.route("**/api/internal/knowledge?**", (route) =>
    route.fulfill({ json: catalog("", []) }),
  );
  await page.reload();
  await expect(page.getByRole("heading", { name: "知识目录为空" })).toBeVisible();

  await page.unroute("**/api/internal/knowledge?**");
  await page.route("**/api/internal/knowledge?**", (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("q") === "不存在的词") {
      return route.fulfill({ json: catalog("不存在的词", []) });
    }
    return route.fulfill({ json: catalog("", [SEARCH_RESULT]) });
  });
  await page.reload();
  await page.getByLabel("关键词").fill("不存在的词");
  await page.getByRole("button", { name: "检索知识" }).click();
  await expect(page.getByRole("heading", { name: "没有匹配的当前知识条目" })).toBeVisible();

  await page.unroute("**/api/internal/knowledge?**");
  await page.route("**/api/internal/knowledge?**", (route) =>
    route.fulfill({
      status: 503,
      json: {
        code: "KNOWLEDGE_INDEX_UNAVAILABLE",
        message: "知识索引当前不可用，请稍后重试",
        index: { ...READY_INDEX, status: "FAILED", articleCount: 0 },
      },
    }),
  );
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("知识索引当前不可用。");
  await expect(page.getByRole("heading", { name: "当前无法显示检索结果" })).toBeVisible();

  await page.unroute("**/api/internal/knowledge?**");
  await page.route("**/api/internal/knowledge?**", (route) =>
    route.fulfill({ json: catalog("", [SEARCH_RESULT]) }),
  );
  await page.route("**/api/internal/knowledge/articles/**", (route) =>
    route.fulfill({
      json: {
        view: "KNOWLEDGE_CATALOG",
        schema: "knowledge-catalog-v1",
        index: READY_INDEX,
        article: {
          ...ARTICLE,
          version: "v1",
          current: false,
          publicationStatus: "RETIRED",
          sourceFile: "knowledge/logistics-delay-v1.md",
          body: "旧版本规则只用于审计历史回复，不作为当前处理依据。",
        },
      },
    }),
  );
  await page.reload();
  await page.getByRole("button", { name: /物流延迟处理说明/ }).click();
  await expect(page.getByText("旧版本，仅供审计，不进入普通检索")).toBeVisible();
  await page.getByRole("button", { name: "重建索引（开发中）" }).click();
  await expect(page.getByRole("status")).toContainText("重建索引入口正在开发中");
  await page.screenshot({ path: testInfo.outputPath(`${label}-old-version-and-development.png`) });
}
