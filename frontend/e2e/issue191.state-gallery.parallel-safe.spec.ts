import { expect, test, type Page } from "@playwright/test";
import { newAcceptanceContext } from "./support/browser-context";

const galleryStates = [
  "首次加载骨架",
  "暂无队列条目",
  "数据加载失败",
  "当前身份无权访问此页面",
  "没有找到这个页面",
  "实时连接已断开",
  "正在重新同步",
  "审批租约过期",
  "操作成功",
  "操作结果未知",
] as const;

test("parallel-safe：状态画廊与独立 403/404 不读写业务数据", async ({ browser }, testInfo) => {
  const context = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 900 } });
  const writes: string[] = [];
  await context.route("**/api/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET" || !path.startsWith("/api/auth/session")) {
      writes.push(`${request.method()} ${path}`);
    }
    return route.continue();
  });

  const gallery = await context.newPage();
  await gallery.goto("/states");
  await expect(gallery.getByRole("heading", { name: "关键状态组件画廊" })).toBeVisible();
  await expect(gallery.getByText("不读取、不写入业务数据")).toBeVisible();
  for (const title of galleryStates) {
    await expect(gallery.getByRole("heading", { name: title })).toBeVisible();
  }
  await expect(gallery.getByText("补偿已批准")).toHaveCount(0);
  await gallery.keyboard.press("Tab");
  await expect(gallery.getByRole("link", { name: "Stellogic 系统状态画廊" })).toBeFocused();
  await gallery.screenshot({ path: testInfo.outputPath("desktop-states.png"), fullPage: true });

  const forbidden = await context.newPage();
  await forbidden.goto("/403");
  await expect(forbidden.getByRole("heading", { name: "当前身份无权访问此页面" })).toBeVisible();
  await expect(forbidden.getByText("403", { exact: true })).toBeVisible();
  await expect(forbidden.getByRole("img", { name: "禁止访问" })).toBeVisible();
  await expect(forbidden.getByText(/工单详情|审批证据|内部备注/)).toHaveCount(0);
  await forbidden.keyboard.press("Tab");
  await expect(forbidden.getByRole("link").first()).toBeFocused();
  await forbidden.screenshot({ path: testInfo.outputPath("desktop-403.png"), fullPage: true });

  const notFound = await context.newPage();
  await notFound.goto("/404");
  await expect(notFound.getByRole("heading", { name: "没有找到这个页面" })).toBeVisible();
  await expect(notFound.getByText("404", { exact: true })).toBeVisible();
  await expect(notFound.getByRole("img", { name: "页面未找到" })).toBeVisible();
  await notFound.keyboard.press("Tab");
  await expect(notFound.getByRole("link").first()).toBeFocused();
  await notFound.screenshot({ path: testInfo.outputPath("desktop-404.png"), fullPage: true });

  const narrow = await context.newPage();
  await narrow.setViewportSize({ width: 360, height: 800 });
  await assertNarrowGallery(narrow);
  await narrow.screenshot({ path: testInfo.outputPath("narrow-states.png"), fullPage: true });
  await narrow.goto("/403");
  await expect(narrow.getByRole("heading", { name: "当前身份无权访问此页面" })).toBeVisible();
  await narrow.screenshot({ path: testInfo.outputPath("narrow-403.png"), fullPage: true });
  await narrow.goto("/404");
  await expect(narrow.getByRole("heading", { name: "没有找到这个页面" })).toBeVisible();
  await narrow.screenshot({ path: testInfo.outputPath("narrow-404.png"), fullPage: true });

  expect(writes).toEqual([]);
  await context.close();
});

async function assertNarrowGallery(page: Page) {
  await page.goto("/states");
  await expect(page.getByRole("heading", { name: "关键状态组件画廊" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "状态画廊导航" })).toBeVisible();
  for (const title of galleryStates) {
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
  }
}
