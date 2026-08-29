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

test("parallel-safe：状态画廊十态具有 status/alert/aria-busy 读屏语义", async ({
  browser,
}, testInfo) => {
  const context = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 900 } });
  const unexpectedApiRequests: string[] = [];
  await context.route("**/api/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET" || !path.startsWith("/api/auth/session")) {
      unexpectedApiRequests.push(`${request.method()} ${path}`);
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
  await expect(gallery.getByRole("status", { name: "正在加载示例" })).toHaveAttribute(
    "aria-busy",
    "true",
  );
  await expect(gallery.getByRole("status", { name: "当前没有队列条目" })).toBeVisible();
  await expectCardNotice(gallery, "数据加载失败", "alert", "待审批队列暂时不可用");
  await expect(gallery.getByRole("status", { name: "禁止访问示例" })).toBeVisible();
  await expect(gallery.getByRole("status", { name: "页面未找到示例" })).toBeVisible();
  await expectCardNotice(gallery, "实时连接已断开", "alert", "实时连接已断开；当前队列可能过期。");
  await expectCardNotice(gallery, "正在重新同步", "status", "正在从 Spring 权威快照重新同步…");
  await expectCardNotice(gallery, "审批租约过期", "status", "审批责任已结束，证据和操作已移除。");
  await expectCardNotice(gallery, "操作成功", "status", "操作已完成（静态示例）");
  await expectCardNotice(
    gallery,
    "操作结果未知",
    "status",
    "结果尚未确认，正在恢复 Spring 权威状态…",
  );
  await expect(gallery.getByText("补偿已批准")).toHaveCount(0);
  await gallery.screenshot({
    path: testInfo.outputPath("desktop-states-semantics.png"),
    fullPage: true,
  });

  const narrow = await context.newPage();
  await narrow.setViewportSize({ width: 360, height: 800 });
  await assertNarrowGallery(narrow);
  await narrow.screenshot({ path: testInfo.outputPath("narrow-states.png"), fullPage: true });

  expect(unexpectedApiRequests).toEqual([]);
  await context.close();
});

test("parallel-safe：状态画廊与错误页键盘焦点可作为独立验收项", async ({ browser }, testInfo) => {
  const context = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 900 } });

  const gallery = await context.newPage();
  await gallery.goto("/states");
  await gallery.keyboard.press("Tab");
  const galleryBrand = gallery.getByRole("link", { name: "Stellogic 系统状态画廊" });
  await expect(galleryBrand).toBeFocused();
  await expect(galleryBrand).toHaveCSS("outline-style", "solid");
  await gallery.screenshot({ path: testInfo.outputPath("keyboard-focus-states.png") });

  const forbidden = await context.newPage();
  await forbidden.goto("/403");
  await forbidden.keyboard.press("Tab");
  const forbiddenLink = forbidden.getByRole("link").first();
  await expect(forbiddenLink).toBeFocused();
  await expect(forbiddenLink).toHaveCSS("outline-style", "solid");
  await forbidden.screenshot({ path: testInfo.outputPath("keyboard-focus-403.png") });

  const notFound = await context.newPage();
  await notFound.goto("/404");
  await notFound.keyboard.press("Tab");
  const notFoundLink = notFound.getByRole("link").first();
  await expect(notFoundLink).toBeFocused();
  await expect(notFoundLink).toHaveCSS("outline-style", "solid");
  await notFound.screenshot({ path: testInfo.outputPath("keyboard-focus-404.png") });

  await context.close();
});

test("parallel-safe：未登录独立 403/404 提供安全入口且不展示受保护内容", async ({
  browser,
}, testInfo) => {
  const context = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 900 } });

  const forbidden = await context.newPage();
  await forbidden.goto("/403");
  await expect(forbidden.getByRole("heading", { name: "当前身份无权访问此页面" })).toBeVisible();
  await expect(forbidden.getByText("403", { exact: true })).toBeVisible();
  await expect(forbidden.getByRole("img", { name: "禁止访问" })).toBeVisible();
  await expect(forbidden.getByText(/当前未登录或没有访问此页面的权限/)).toBeVisible();
  await expect(forbidden.getByRole("link", { name: "前往客户登录" })).toBeVisible();
  await expect(forbidden.getByRole("link", { name: "前往内部登录" })).toBeVisible();
  await expect(forbidden.getByText(/工单详情|审批证据|内部备注/)).toHaveCount(0);
  await forbidden.screenshot({
    path: testInfo.outputPath("desktop-403-anonymous.png"),
    fullPage: true,
  });

  const notFound = await context.newPage();
  await notFound.goto("/404");
  await expect(notFound.getByRole("heading", { name: "没有找到这个页面" })).toBeVisible();
  await expect(notFound.getByText("404", { exact: true })).toBeVisible();
  await expect(notFound.getByRole("img", { name: "页面未找到" })).toBeVisible();
  await expect(notFound.getByText(/当前未登录，无法确定适合你的工作区/)).toBeVisible();
  await expect(notFound.getByRole("link", { name: "前往客户登录" })).toBeVisible();
  await expect(notFound.getByRole("link", { name: "前往内部登录" })).toBeVisible();
  await notFound.screenshot({
    path: testInfo.outputPath("desktop-404-anonymous.png"),
    fullPage: true,
  });

  const narrow = await context.newPage();
  await narrow.setViewportSize({ width: 360, height: 800 });
  await narrow.goto("/403");
  await expect(narrow.getByRole("heading", { name: "当前身份无权访问此页面" })).toBeVisible();
  await narrow.screenshot({ path: testInfo.outputPath("narrow-403.png"), fullPage: true });
  await narrow.goto("/404");
  await expect(narrow.getByRole("heading", { name: "没有找到这个页面" })).toBeVisible();
  await narrow.screenshot({ path: testInfo.outputPath("narrow-404.png"), fullPage: true });

  await context.close();
});

async function expectCardNotice(page: Page, title: string, role: "alert" | "status", text: string) {
  const card = page.locator("article").filter({ has: page.getByRole("heading", { name: title }) });
  await expect(card.getByRole(role)).toContainText(text);
}

async function assertNarrowGallery(page: Page) {
  await page.goto("/states");
  await expect(page.getByRole("heading", { name: "关键状态组件画廊" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "状态画廊导航" })).toBeVisible();
  for (const title of galleryStates) {
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
  }
  await expect(page.getByRole("status", { name: "当前没有队列条目" })).toBeVisible();
}
