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
      expect(data.schema).toBe("knowledge-hybrid-v1");
      expect(data.results.length).toBeGreaterThan(0);
      for (const hit of [...data.results, ...data.lexicalCandidates, ...data.vectorCandidates]) {
        expect(hit.version === "v1" && hit.articleId === "logistics-delay").toBe(false);
        expect(hit.sourceFile).toMatch(/^knowledge\//);
        expect(hit.startLine).toBeGreaterThan(0);
      }
      await expect(panel.getByRole("list", { name: "RRF 合格结果" })).toContainText(
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
        await expect(panel.getByRole("list", { name: "RRF 合格结果" })).toHaveCount(0);
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
      await expect(panel.getByText("没有足够相关的可引用知识，不生成无来源答案。")).toBeVisible();
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
