import { expect, test, type BrowserContext } from "@playwright/test";
import { login } from "./support/auth";
import { newIssue80Context } from "./support/browser-context";

async function freshPage(context: BrowserContext, path: string) {
  const page = await context.newPage();
  await page.goto(path);
  return page;
}

test.describe("Issue #80 五类身份的 Shell 与静态路由", () => {
  test("桌面视口真实呈现加载、错误、404，并可用 Tab 看见焦点", async ({ browser }, testInfo) => {
    const context = await newIssue80Context(browser, { viewport: { width: 1440, height: 900 } });

    const notFound = await freshPage(context, "/not-a-business-resource");
    await expect(notFound.getByRole("heading", { name: "没有找到这个页面" })).toBeVisible();
    await expect(notFound.getByText("404", { exact: true })).toBeVisible();
    await expect(notFound.getByRole("img", { name: "页面未找到" })).toBeVisible();
    await notFound.keyboard.press("Tab");
    const focusedLink = notFound.getByRole("link", { name: "前往客户登录" });
    await expect(focusedLink).toBeFocused();
    await expect(focusedLink).toHaveCSS("outline-style", "solid");
    await notFound.screenshot({ path: testInfo.outputPath("desktop-404-and-keyboard-focus.png") });

    const error = await context.newPage();
    await error.route("**/api/auth/session", (route) =>
      route.fulfill({ status: 503, body: "temporarily unavailable" }),
    );
    await error.goto("/help");
    await expect(error.getByRole("heading", { name: "暂时无法进入工作区" })).toBeVisible();
    await expect(error.getByRole("alert")).toContainText("当前身份暂时无法确认");
    await expect(error.getByRole("img", { name: "身份确认失败" })).toBeVisible();

    const loading = await context.newPage();
    let releaseSession: (() => void) | undefined;
    await loading.route("**/api/auth/session", async (route) => {
      await new Promise<void>((resolve) => {
        releaseSession = resolve;
      });
      await route.fulfill({ status: 401 });
    });
    await loading.goto("/help", { waitUntil: "domcontentloaded" });
    const busyState = loading.locator("main[aria-busy='true']");
    await expect(busyState).toBeVisible();
    await expect(busyState.getByRole("status", { name: "正在确认当前身份" })).toBeVisible();
    await expect(busyState.getByRole("img", { name: "正在加载身份" })).toBeVisible();
    releaseSession?.();
    await expect(loading).toHaveURL(/\/help\/login\?returnTo=%2Fhelp$/);
    await context.close();
  });

  test("真实浏览器在客服事件流断开后显示重新同步状态", async ({ page }) => {
    await page.route("**/api/support/workbench/events", (route) =>
      route.fulfill({ status: 200, contentType: "text/event-stream", body: "" }),
    );
    await login(page, "internal", "support-demo");
    await expect(page.getByRole("heading", { name: "客服共享队列" })).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: "正在从 Spring 权威快照重新同步" }),
    ).toBeVisible();
  });

  test("未登录直达客户和内部 URL 时进入对应登录页", async ({ browser }) => {
    const context = await newIssue80Context(browser);
    const customer = await freshPage(context, "/help");
    await expect(customer).toHaveURL(/\/help\/login\?returnTo=%2Fhelp$/);
    await expect(customer.getByRole("heading", { name: "客户登录" })).toBeVisible();

    const internal = await freshPage(context, "/internal/approvals");
    await expect(internal).toHaveURL(/\/internal\/login\?returnTo=%2Finternal%2Fapprovals$/);
    await expect(internal.getByRole("heading", { name: "内部工作人员登录" })).toBeVisible();
    await context.close();
  });

  test("Issue #97 真实密码登录后呈现双界面壳、静态工作区选择并可安全退出", async ({
    browser,
  }, testInfo) => {
    const customerContext = await newIssue80Context(browser, {
      viewport: { width: 1440, height: 900 },
    });
    const customer = await freshPage(customerContext, "/help/login");
    await login(customer, "customer", "customer-demo");
    await expect(customer.getByRole("link", { name: "Stellogic 客户帮助中心" })).toBeVisible();
    await expect(customer.getByText("当前客户：演示客户")).toBeVisible();
    await expect(customer.getByRole("navigation", { name: "内部工作区" })).toHaveCount(0);
    await customer.screenshot({ path: testInfo.outputPath("issue97-customer-shell.png") });
    await customer.getByRole("button", { name: "退出登录" }).click();
    await expect(customer).toHaveURL(/\/help\/login\?returnTo=%2Fhelp$/);
    await expect(customer.getByRole("heading", { name: "客户登录" })).toBeVisible();
    await customerContext.close();

    const internalContext = await newIssue80Context(browser, {
      viewport: { width: 1440, height: 900 },
    });
    const internal = await freshPage(internalContext, "/internal/login");
    const businessReads: string[] = [];
    internal.on("request", (request) => {
      const pathname = new URL(request.url()).pathname;
      if (pathname.startsWith("/api/support/") || pathname.startsWith("/api/approver/")) {
        businessReads.push(pathname);
      }
    });
    await login(internal, "internal", "internal-demo");
    await expect(internal.getByRole("heading", { name: "选择工作区" })).toBeVisible();
    await expect(
      internal
        .getByLabel("内部工作台", { exact: true })
        .getByText("当前工作人员：演示双角色工作人员"),
    ).toBeVisible();
    await expect(internal.getByRole("link", { name: "进入客服工作区" })).toBeVisible();
    await expect(internal.getByRole("link", { name: "进入审批工作区" })).toBeVisible();
    expect(businessReads).toEqual([]);
    await internal.screenshot({
      path: testInfo.outputPath("issue97-internal-workspace-choice.png"),
    });
    await internal.getByRole("button", { name: "退出登录" }).click();
    await expect(internal).toHaveURL(/\/internal\/login\?returnTo=%2Finternal$/);
    await expect(internal.getByRole("heading", { name: "内部工作人员登录" })).toBeVisible();
    await internalContext.close();
  });

  test("Issue #97 窄屏双界面壳保留身份、退出入口且不产生横向溢出", async ({ browser }) => {
    const context = await newIssue80Context(browser, { viewport: { width: 390, height: 844 } });

    const customer = await freshPage(context, "/help/login");
    await login(customer, "customer", "customer-demo");
    await expect(customer.getByText("当前客户：演示客户")).toBeVisible();
    await expect(customer.getByRole("button", { name: "退出登录" })).toBeVisible();
    await customer.getByLabel("订单编号").fill("ORDER-DELAY-UNDER-24");
    await customer.getByLabel("问题描述").fill("Issue #151 窄屏真实 v2 公开沟通验收");
    const createdResponse = customer.waitForResponse(
      (response) =>
        /\/api\/customer\/v2\/intakes\/[^/]+\/messages$/.test(new URL(response.url()).pathname) &&
        [200, 201].includes(response.status()),
    );
    const snapshotResponse = customer.waitForResponse(
      (response) =>
        /\/api\/customer\/v2\/tickets\/[^/]+$/.test(new URL(response.url()).pathname) &&
        response.status() === 200,
    );
    await customer.getByRole("button", { name: "提交物流延迟问题" }).click();
    await expect(customer.getByRole("heading", { name: "请确认我的理解" })).toBeVisible();
    await customer.getByRole("button", { name: "确认，就是这个问题" }).click();
    const created = (await (await createdResponse).json()) as {
      schema: string;
      ticketId: string;
    };
    const snapshot = (await (await snapshotResponse).json()) as {
      view: string;
      schema: string;
      ticket: { id: string };
    };
    expect(created.schema).toBe("customer-intake-v2");
    expect(snapshot).toMatchObject({
      view: "PUBLIC_CONVERSATION",
      schema: "public-conversation-v2",
      ticket: { id: created.ticketId },
    });
    await expect(customer.getByText("Issue #151 窄屏真实 v2 公开沟通验收")).toBeVisible();
    await expect(customer.getByRole("button", { name: "转人工处理" })).toBeVisible();
    expect(
      await customer.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await customer.getByRole("button", { name: "退出登录" }).click();
    await expect(customer).toHaveURL(/\/help\/login\?returnTo=%2Fhelp$/);
    await expect(customer.getByRole("heading", { name: "客户登录" })).toBeVisible();

    const internal = await freshPage(context, "/internal/login");
    await login(internal, "internal", "internal-demo");
    await expect(
      internal
        .getByLabel("内部工作台", { exact: true })
        .getByText("当前工作人员：演示双角色工作人员"),
    ).toBeVisible();
    await expect(internal.getByRole("button", { name: "退出登录" })).toBeVisible();
    expect(
      await internal.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await context.close();
  });

  const identities = [
    {
      username: "customer-demo",
      audience: "customer" as const,
      landing: "/help",
      shell: "客户帮助中心",
      visibleMenus: [] as string[],
      forbidden: "/internal/support",
    },
    {
      username: "support-demo",
      audience: "internal" as const,
      landing: "/internal/support",
      shell: "内部工作台",
      visibleMenus: ["客服工作区"],
      forbidden: "/internal/approvals",
    },
    {
      username: "approver-demo",
      audience: "internal" as const,
      landing: "/internal/approvals",
      shell: "内部工作台",
      visibleMenus: ["审批工作区"],
      forbidden: "/internal/support",
    },
    {
      username: "internal-demo",
      audience: "internal" as const,
      landing: "/internal",
      shell: "内部工作台",
      visibleMenus: ["客服工作区", "审批工作区"],
    },
  ] as const;

  for (const identity of identities) {
    test(`${identity.username} 只看到本身份 Shell、菜单和默认落点`, async ({ page }) => {
      await login(page, identity.audience, identity.username);
      await expect(page).toHaveURL(new RegExp(`${identity.landing.replaceAll("/", "\\/")}$`));
      if (identity.audience === "customer") {
        await expect(page.getByRole("banner", { name: identity.shell })).toBeVisible();
      } else {
        await expect(page.getByRole("banner").filter({ hasText: "统一内部工作台" })).toBeVisible();
      }

      for (const menu of identity.visibleMenus) {
        await expect(page.getByRole("link", { name: menu, exact: true })).toBeVisible();
      }
      if (identity.username === "support-demo") {
        await expect(page.getByRole("link", { name: "审批工作区", exact: true })).toHaveCount(0);
      }
      if (identity.username === "approver-demo") {
        await expect(page.getByRole("link", { name: "客服工作区", exact: true })).toHaveCount(0);
      }
      if (identity.username === "customer-demo") {
        await expect(page.getByRole("navigation", { name: "内部工作区" })).toHaveCount(0);
      }

      if ("forbidden" in identity) {
        await page.goto(identity.forbidden);
        await expect(page.getByRole("heading", { name: "当前身份无权访问此页面" })).toBeVisible();
      } else {
        await page.goto("/internal/support");
        await expect(page.getByRole("heading", { name: "客服共享队列" })).toBeVisible();
        await page.goto("/internal/approvals");
        await expect(
          page.getByRole("heading", { level: 1, name: /待审批补偿|补偿提案审批/ }),
        ).toBeVisible();
      }
    });
  }
});
