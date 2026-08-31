import { expect, test } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql } from "./support/database";

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`Issue #190 真实混合检索与失效状态 ${viewport.width}`, async ({ browser }, testInfo) => {
    const context = await newAcceptanceContext(browser, { viewport });
    const page = await context.newPage();
    try {
      await login(page, "internal", "support-demo");
      await page.goto("/internal/knowledge");
      const panel = page.getByRole("region", { name: "中文混合检索" });
      const query = "物流节点超过承诺时间没有更新时，先核对订单与物流的当前权威状态";
      await panel.getByLabel("检索问题", { exact: true }).fill(query);
      const fetched = page.waitForResponse((response) =>
        response.url().includes("/api/internal/knowledge/search?"),
      );
      await panel.getByRole("button", { name: "混合检索", exact: true }).click();
      const response = await fetched;
      expect(response.status()).toBe(200);
      const data = await response.json();
      expect(data.schema).toBe("knowledge-hybrid-v2");
      expect(data.results.length).toBeGreaterThan(0);
      expect(data.lexicalCandidates.length).toBeGreaterThan(0);
      expect(data).not.toHaveProperty("policy");
      for (const hit of [...data.results, ...data.lexicalCandidates, ...data.vectorCandidates]) {
        expect(hit.version === "v1" && hit.articleId === "logistics-delay").toBe(false);
        expect(hit.sourceFile).toMatch(/^knowledge\//);
        expect(hit.startLine).toBeGreaterThan(0);
      }
      await expect(panel.getByRole("list", { name: "RRF 检索片段" })).toContainText(
        "logistics-delay",
      );
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`hybrid-${viewport.width}.png`) });

      // 真数据库代次失配必须停止返回，恢复本测试改变的标记。
      executeFixtureSql(
        "UPDATE knowledge_vector_state SET generation=generation+1000000 WHERE id=1",
      );
      try {
        await panel.getByRole("button", { name: "混合检索", exact: true }).click();
        await expect(panel.getByRole("alert")).toContainText("索引过期");
        await expect(panel.getByRole("list", { name: "RRF 检索片段" })).toHaveCount(0);
      } finally {
        executeFixtureSql(
          "UPDATE knowledge_vector_state SET generation=generation-1000000 WHERE id=1",
        );
      }

      // UI loading/empty/error 使用显式网络状态夹具，不冒充真实模型质量证据。
      let release: (() => void) | undefined;
      await page.route("**/api/internal/knowledge/search?**", async (route) => {
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        await route.fulfill({
          json: { ...data, results: [], lexicalCandidates: [], vectorCandidates: [] },
        });
      });
      await panel.getByRole("button", { name: "混合检索", exact: true }).click();
      await expect(panel.getByRole("status")).toContainText("正在读取真实混合检索结果");
      release?.();
      await expect(panel.getByText("当前授权范围内没有匹配的知识片段。")).toBeVisible();
      await page.unroute("**/api/internal/knowledge/search?**");
      await page.route("**/api/internal/knowledge/search?**", (route) =>
        route.fulfill({ status: 503, json: { code: "MODEL_UNAVAILABLE" } }),
      );
      await panel.getByRole("button", { name: "混合检索", exact: true }).click();
      await expect(panel.getByRole("alert")).toContainText("没有返回知识结果");
    } finally {
      await context.close();
    }
  });
}

test("Issue #190 真实会话拒绝客户与无知识读权限人员", async ({ browser }) => {
  for (const username of ["customer-demo", "support-no-knowledge", "approver-no-knowledge"]) {
    const context = await newAcceptanceContext(browser);
    try {
      const csrf = await context.request.get("/api/auth/csrf");
      const token = await csrf.json();
      const signedIn = await context.request.post("/api/auth/login", {
        headers: { [token.headerName]: token.token },
        form: { username, password: "local-demo-password" },
      });
      expect(signedIn.status()).toBe(204);
      const response = await context.request.get("/api/internal/knowledge/search?q=物流延迟");
      expect(response.status()).toBe(403);
      expect(await response.text()).not.toContain("chunk-");
    } finally {
      await context.close();
    }
  }
});

test("Issue #190 无答案问题仍可返回授权候选而不冒充充分性判断", async ({ browser }) => {
  const context = await newAcceptanceContext(browser);
  try {
    await login(await context.newPage(), "internal", "support-demo");
    // 独立工程样例，不取自冻结评测题；当前知识库没有园艺指导。
    const response = await context.request.get("/api/internal/knowledge/search", {
      params: { q: "温室里马铃薯每周应该浇几次水", scope: "INTERNAL" },
    });
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.schema).toBe("knowledge-hybrid-v2");
    expect(result.results.length).toBeGreaterThan(0);
    expect(result.results.length).toBeLessThanOrEqual(5);
    expect(result).not.toHaveProperty("policy");
    expect(result).not.toHaveProperty("answerable");
    for (const hit of result.results) expect(hit.applicability).toContain("INTERNAL");
  } finally {
    await context.close();
  }
});

test("Issue #190 显式未授权范围返回权限错误而非空结果", async ({ browser }) => {
  const context = await newAcceptanceContext(browser);
  try {
    const page = await context.newPage();
    await login(page, "internal", "support-demo");
    await page.goto("/internal/knowledge");
    const panel = page.getByRole("region", { name: "中文混合检索" });
    await panel.getByLabel("检索问题", { exact: true }).fill("物流延迟");
    await panel.getByLabel("检索适用范围").selectOption("APPROVER");
    const fetched = page.waitForResponse((response) =>
      response.url().includes("/api/internal/knowledge/search?"),
    );
    await panel.getByRole("button", { name: "混合检索", exact: true }).click();
    const response = await fetched;
    expect(response.status()).toBe(403);
    expect((await response.json()).code).toBe("KNOWLEDGE_ACCESS_DENIED");
    await expect(panel.getByRole("alert")).toContainText("无权检索所选适用范围");
    await expect(panel.getByText("当前授权范围内没有匹配的知识片段。")).toHaveCount(0);
    await expect(panel.getByRole("list", { name: "RRF 检索片段" })).toHaveCount(0);
  } finally {
    await context.close();
  }
});

test("Issue #190 两路排名前排除高分草稿和退役版本", async ({ browser }) => {
  const context = await newAcceptanceContext(browser);
  try {
    const page = await context.newPage();
    await login(page, "internal", "support-demo");
    // 25 条与合法向量完全相同的草稿，超过候选 limit；若先排名后过滤，合法候选会丢失。
    executeFixtureSql(`
      INSERT INTO knowledge_article(article_id,version,title,updated_at,applicability,
        publication_status,is_current,source_file,content_hash,body,indexed_at)
      SELECT 'issue190-draft-' || n,'v1','物流延迟',now(),ARRAY['INTERNAL'],'DRAFT',false,
        'knowledge/issue190-draft-' || n || '.md',repeat('a',64),'物流延迟',now()
      FROM generate_series(1,25) n;
      INSERT INTO knowledge_chunk(chunk_id,article_id,version,ordinal,source_file,start_line,
        end_line,applicability,content,indexed_at)
      SELECT 'chunk-' || lpad(n::text,64,'0'),'issue190-draft-' || n,'v1',1,
        'knowledge/issue190-draft-' || n || '.md',1,1,ARRAY['INTERNAL'],'物流延迟',now()
      FROM generate_series(1,25) n;
      INSERT INTO knowledge_embedding(chunk_id,generation,content_hash,revision,embedding,lexical_vector)
      SELECT c.chunk_id,e.generation,repeat('a',64),e.revision,e.embedding,to_tsvector('simple','物流 流延 延迟')
      FROM knowledge_chunk c CROSS JOIN LATERAL
        (SELECT * FROM knowledge_embedding ORDER BY chunk_id LIMIT 1) e
      WHERE c.article_id LIKE 'issue190-draft-%';
      INSERT INTO knowledge_embedding(chunk_id,generation,content_hash,revision,embedding,lexical_vector)
      SELECT c.chunk_id,e.generation,a.content_hash,e.revision,e.embedding,to_tsvector('simple','物流 流延 延迟')
      FROM knowledge_chunk c JOIN knowledge_article a USING(article_id,version)
      CROSS JOIN LATERAL (SELECT * FROM knowledge_embedding ORDER BY chunk_id LIMIT 1) e
      WHERE a.publication_status='RETIRED' ON CONFLICT(chunk_id) DO NOTHING;
    `);
    const response = await context.request.get("/api/internal/knowledge/search?q=物流延迟");
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.vectorCandidates.length).toBeGreaterThan(0);
    expect(body.lexicalCandidates.length).toBeGreaterThan(0);
    for (const hit of [...body.results, ...body.vectorCandidates, ...body.lexicalCandidates]) {
      expect(hit.articleId).not.toMatch(/^issue190-draft-/);
      expect(hit.articleId === "logistics-delay" && hit.version === "v1").toBe(false);
    }
  } finally {
    executeFixtureSql(`
      DELETE FROM knowledge_article WHERE article_id LIKE 'issue190-draft-%';
      DELETE FROM knowledge_embedding WHERE chunk_id IN
        (SELECT c.chunk_id FROM knowledge_chunk c JOIN knowledge_article a USING(article_id,version)
         WHERE a.publication_status='RETIRED');
    `);
    await context.close();
  }
});
