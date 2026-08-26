import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const applicationStyles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("Issue #99 窄屏队列在自身范围内提供确定的横向滚动", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 640, height: 960 });
  await page.setContent(`
    <style>${applicationStyles}</style>
    <main class="support-workbench" aria-label="客服工作台">
      <section class="support-workspace-layout">
        <div class="support-queues">
          <section class="queue-panel">
            <div class="queue-table-wrap" aria-label="队列滚动区">
              <table class="queue-table">
                <thead>
                  <tr>
                    <th>工单</th>
                    <th>生命周期</th>
                    <th>处理模式</th>
                    <th>进入时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><span class="support-ticket-identifier compact">示例工单</span></td>
                    <td><span class="status support-status">调查中</span></td>
                    <td>人工处理</td>
                    <td><time>2026-08-26 19:00</time></td>
                    <td><button class="queue-claim-action">领取</button></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>
        <aside class="detail-placeholder" aria-label="授权详情等待区">等待领取</aside>
      </section>
    </main>
  `);

  const queueScroller = page.getByLabel("队列滚动区");
  const dimensions = await queueScroller.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  await page.screenshot({
    path: testInfo.outputPath("queue-layout-red.png"),
    fullPage: true,
  });

  expect(dimensions.scrollWidth).toBeGreaterThan(dimensions.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(640);
  await expect(page.getByLabel("授权详情等待区")).toHaveCSS("position", "static");
});
