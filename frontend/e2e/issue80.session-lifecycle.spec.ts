import { expect, test } from "@playwright/test";
import { login, password } from "./support/auth";

test("真实密码 Session 经刷新恢复，执行 CSRF、主体替换与跨标签退出", async ({ context, page }) => {
  await login(page, "customer", "customer-demo");
  await expect(page).toHaveURL(/\/help$/);

  const sessionCookie = (await context.cookies()).find((cookie) => cookie.name === "JSESSIONID");
  expect(sessionCookie).toMatchObject({
    httpOnly: true,
    secure: true,
    sameSite: "Strict",
    expires: -1,
  });

  await page.reload();
  await expect(page.getByRole("banner", { name: "客户帮助中心" })).toBeVisible();

  const forgedLogoutStatus = await page.evaluate(async () => {
    const response = await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "same-origin",
    });
    return response.status;
  });
  expect(forgedLogoutStatus).toBe(403);
  await expect(page.getByRole("banner", { name: "客户帮助中心" })).toBeVisible();

  const replacementStatus = await page.evaluate(
    async ({ username, password: nextPassword }) => {
      const csrf = (await (
        await fetch("/api/auth/csrf", { credentials: "same-origin" })
      ).json()) as {
        token: string;
        headerName: string;
      };
      return (
        await fetch("/api/auth/login", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            [csrf.headerName]: csrf.token,
          },
          body: new URLSearchParams({ username, password: nextPassword }),
        })
      ).status;
    },
    { username: "support-demo", password },
  );
  expect(replacementStatus).toBe(204);

  await page.goto("/");
  await expect(page).toHaveURL(/\/internal\/support$/);
  const peer = await context.newPage();
  const peerStreamOpened = peer.waitForResponse(
    (response) =>
      response.url().endsWith("/api/support/workbench/events") && response.status() === 200,
  );
  await peer.goto("/internal/support");
  await expect(peer.getByRole("heading", { name: "客服共享队列" })).toBeVisible();
  await peerStreamOpened;

  const logoutStartedAt = Date.now();
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page).toHaveURL(/\/internal\/login/);
  await expect(peer).toHaveURL(/\/internal\/login/);
  await expect(peer.getByRole("heading", { name: "内部工作人员登录" })).toBeVisible();
  expect(Date.now() - logoutStartedAt).toBeLessThan(60_000);
});

test("服务端 Session 失效使已建立 SSE 在 60 秒内断流并回到权威登录状态", async ({
  context,
  page,
}) => {
  test.setTimeout(70_000);
  await login(page, "internal", "support-demo");
  const streamOpened = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/support/workbench/events") && response.status() === 200,
  );
  await page.goto("/internal/support");
  await expect(page.getByRole("heading", { name: "客服共享队列" })).toBeVisible();
  await streamOpened;

  const invalidator = await context.newPage();
  await invalidator.goto("/internal");
  const logoutStatus = await invalidator.evaluate(async () => {
    const csrf = (await (
      await fetch("/api/auth/csrf", { credentials: "same-origin", cache: "no-store" })
    ).json()) as { token: string; headerName: string };
    return (
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: { [csrf.headerName]: csrf.token },
      })
    ).status;
  });
  expect(logoutStatus).toBe(204);
  const authorityStatus = await invalidator.evaluate(async () => {
    return (await fetch("/api/auth/session", { credentials: "same-origin", cache: "no-store" }))
      .status;
  });
  expect(authorityStatus).toBe(401);

  const invalidatedAt = Date.now();
  await expect(page).toHaveURL(/\/internal\/login/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "内部工作人员登录" })).toBeVisible();
  expect(Date.now() - invalidatedAt).toBeLessThan(60_000);
});
