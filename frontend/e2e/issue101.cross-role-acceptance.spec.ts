import { expect, test, type Browser, type Locator, type Page } from "@playwright/test";
import { login } from "./support/auth";
import { newAcceptanceContext } from "./support/browser-context";
import { executeFixtureSql } from "./support/database";

const approvalRevisionId = "80000000-0000-0000-0000-000000000008";
const desktopReducedMotion = {
  viewport: { width: 1440, height: 960 },
  reducedMotion: "reduce" as const,
};

function resetApprovalFixture() {
  executeFixtureSql(`
    DELETE FROM approval_release_request WHERE proposal_revision_id = '${approvalRevisionId}';
    DELETE FROM approval_claim_request WHERE proposal_revision_id = '${approvalRevisionId}';
    DELETE FROM approval_view_event WHERE proposal_revision_id = '${approvalRevisionId}';
    DELETE FROM audit_event
      WHERE subject_type = 'COMPENSATION_PROPOSAL_REVISION'
        AND subject_id = '${approvalRevisionId}'
        AND event_type LIKE 'APPROVAL_LEASE_%';
    DELETE FROM approval_lease WHERE proposal_revision_id = '${approvalRevisionId}';
    UPDATE compensation_proposal_revision
      SET status = 'PENDING_APPROVAL'
      WHERE id = '${approvalRevisionId}';
  `);
}

async function openIdentityPage(
  browser: Browser,
  audience: "customer" | "internal",
  username: string,
  heading: string | RegExp,
) {
  const context = await newAcceptanceContext(browser, desktopReducedMotion);
  const page = await context.newPage();
  await login(page, audience, username);
  await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  return { context, page };
}

async function assertKeyboardAndReducedMotion(page: Page, motionTarget: Locator) {
  await motionTarget.focus();
  await page.keyboard.press("Tab");
  if ((await page.locator(":focus").count()) === 0) await page.keyboard.press("Tab");
  const focused = page.locator(":focus");
  await expect(focused).toBeVisible();
  await expect(focused).toHaveCSS("outline-style", "solid");

  const motion = await motionTarget.evaluate((element) => {
    const style = getComputedStyle(element);
    const longestMilliseconds = (value: string) =>
      Math.max(
        ...value.split(",").map((duration) => {
          const normalized = duration.trim();
          const value = Number.parseFloat(normalized);
          return normalized.endsWith("ms") ? value : value * 1_000;
        }),
      );
    return {
      animationMilliseconds: longestMilliseconds(style.animationDuration),
      transitionMilliseconds: longestMilliseconds(style.transitionDuration),
      scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
    };
  });
  expect(motion.animationMilliseconds).toBeLessThanOrEqual(0.01);
  expect(motion.transitionMilliseconds).toBeLessThanOrEqual(0.01);
  expect(motion.scrollBehavior).toBe("auto");
}

async function visualLanguage(page: Page, pageShell: Locator, status: Locator, action: Locator) {
  await action.focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(action).toBeFocused();
  const [shellStyle, statusStyle, actionStyle] = await Promise.all([
    pageShell.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        paddingBlockStart: style.paddingBlockStart,
        paddingInlineStart: style.paddingInlineStart,
        paddingInlineEnd: style.paddingInlineEnd,
      };
    }),
    status.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        borderRadius: style.borderRadius,
        display: style.display,
        fontWeight: style.fontWeight,
        lineHeight: style.lineHeight,
        padding: style.padding,
      };
    }),
    action.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        outlineColor: style.outlineColor,
        outlineStyle: style.outlineStyle,
        outlineWidth: style.outlineWidth,
        outlineOffset: style.outlineOffset,
      };
    }),
  ]);
  const documentStyle = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    const heading = document.querySelector("h1");
    if (!heading) throw new Error("页面缺少一级标题");
    const headingStyle = getComputedStyle(heading);
    return {
      tokens: {
        forest: root.getPropertyValue("--forest-900").trim(),
        canvas: root.getPropertyValue("--canvas").trim(),
        line: root.getPropertyValue("--line").trim(),
        radius: root.getPropertyValue("--radius").trim(),
        radiusLarge: root.getPropertyValue("--radius-lg").trim(),
        shadow: root.getPropertyValue("--shadow-sm").trim(),
      },
      bodyFont: getComputedStyle(document.body).fontFamily,
      bodyFontSize: getComputedStyle(document.body).fontSize,
        heading: {
          color: headingStyle.color,
          fontFamily: headingStyle.fontFamily,
          fontSize: headingStyle.fontSize,
          fontWeight: headingStyle.fontWeight,
          lineHeightRatio: Number(
            (
              Number.parseFloat(headingStyle.lineHeight) / Number.parseFloat(headingStyle.fontSize)
            ).toFixed(3),
          ),
        },
      noHorizontalOverflow:
        document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    };
  });
  return { ...documentStyle, shellStyle, statusStyle, actionStyle };
}

async function assertTextAndIconStatus(status: Locator) {
  await expect(status).toContainText(/\S/);
  await expect(status.getByRole("img").first()).toBeVisible();
}

test("Issue #101 客户、客服与审批页面共享视觉语言并保持投影隔离", async ({ browser }, testInfo) => {
  test.setTimeout(90_000);
  const { context: customerContext, page: customer } = await openIdentityPage(
    browser,
    "customer",
    "customer-demo",
    /物流遇到问题/,
  );
  await expect(customer.getByLabel("订单编号")).toBeVisible();
  await expect(customer.getByLabel("问题描述")).toBeVisible();
  await expect(customer.getByRole("navigation", { name: "内部工作区" })).toHaveCount(0);
  await customer.route("**/api/customer/v2/tickets", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 503, body: "temporarily unavailable" })
      : route.continue(),
  );
  await customer.getByLabel("订单编号").fill("ORDER-DELAY-UNDER-24");
  await customer.getByLabel("问题描述").fill("跨页面交互反馈验收");
  await customer.getByRole("button", { name: "提交物流延迟问题" }).click();
  const customerStatus = customer.getByRole("alert");
  await assertTextAndIconStatus(customerStatus);
  await assertKeyboardAndReducedMotion(
    customer,
    customer.getByRole("button", { name: "提交物流延迟问题" }),
  );
  const customerAction = customer.getByRole("button", { name: "提交物流延迟问题" });
  const customerStyle = await visualLanguage(
    customer,
    customer.locator(".help-center"),
    customerStatus,
    customerAction,
  );
  await customer.screenshot({
    path: testInfo.outputPath("customer-cross-page.png"),
    fullPage: true,
  });

  const { context: supportContext, page: support } = await openIdentityPage(
    browser,
    "internal",
    "support-demo",
    "客服共享队列",
  );
  await expect(support.getByRole("link", { name: "审批工作区", exact: true })).toHaveCount(0);
  const supportStatus = support.getByRole("status").first();
  await assertTextAndIconStatus(supportStatus);
  const claim = support.getByRole("button", { name: /领取工单/ }).first();
  await claim.click();
  const claimDialog = support.getByRole("dialog", { name: "确认领取工单" });
  await expect(claimDialog).toBeVisible();
  await support.keyboard.press("Escape");
  await expect(claimDialog).toHaveCount(0);
  await assertKeyboardAndReducedMotion(support, claim);
  const supportStyle = await visualLanguage(
    support,
    support.locator(".support-workbench"),
    supportStatus,
    claim,
  );
  await support.screenshot({ path: testInfo.outputPath("support-cross-page.png"), fullPage: true });

  const { context: approverContext, page: approver } = await openIdentityPage(
    browser,
    "internal",
    "approver-demo",
    "待审批补偿",
  );
  await expect(approver.getByRole("link", { name: "客服工作区", exact: true })).toHaveCount(0);
  const approverStatus = approver.getByRole("status").first();
  await assertTextAndIconStatus(approverStatus);
  const approvalClaim = approver.getByRole("button", { name: "领取审批" }).first();
  await assertKeyboardAndReducedMotion(approver, approvalClaim);
  const approverStyle = await visualLanguage(
    approver,
    approver.locator(".approval-workbench"),
    approverStatus,
    approvalClaim,
  );
  await approver.screenshot({
    path: testInfo.outputPath("approval-cross-page.png"),
    fullPage: true,
  });

  for (const style of [customerStyle, supportStyle, approverStyle]) {
    expect(style.shellStyle.paddingInlineStart).toBe("28px");
    expect(style.shellStyle.paddingInlineEnd).toBe("28px");
    expect(Number.parseFloat(style.shellStyle.paddingBlockStart)).toBeGreaterThanOrEqual(28);
    expect(Number.parseFloat(style.heading.fontSize)).toBeGreaterThan(
      Number.parseFloat(style.bodyFontSize) * 2,
    );
    expect(style.statusStyle).toEqual(customerStyle.statusStyle);
    expect(style.actionStyle).toEqual(customerStyle.actionStyle);
    expect(style.actionStyle.outlineStyle).toBe("solid");
    expect(style.actionStyle.outlineWidth).toBe("3px");
    expect(style.bodyFont).toBe(customerStyle.bodyFont);
    expect(style.noHorizontalOverflow).toBe(true);
  }
  expect(supportStyle.heading).toEqual({
    ...customerStyle.heading,
    fontSize: supportStyle.heading.fontSize,
  });
  expect(approverStyle.heading).toEqual({
    ...customerStyle.heading,
    fontSize: approverStyle.heading.fontSize,
  });
  expect(Number.parseFloat(customerStyle.heading.fontSize)).toBeGreaterThanOrEqual(
    Number.parseFloat(supportStyle.heading.fontSize),
  );
  expect(Number.parseFloat(supportStyle.heading.fontSize)).toBeGreaterThanOrEqual(
    Number.parseFloat(approverStyle.heading.fontSize),
  );
  expect(customerStyle.tokens.forest).toBe("#0b382b");
  expect(customerStyle.tokens.canvas).toBe("#f2f4f2");
  expect(customerStyle.tokens.radius).toBe("16px");
  expect(customerStyle.tokens.radiusLarge).toBe("22px");
  expect(customerStyle.heading.fontFamily).toMatch(
    /Iowan Old Style|Songti SC|STSong|Georgia|serif/,
  );
  expect(customerStyle.bodyFont).toMatch(/Aptos|Microsoft YaHei UI|PingFang SC|sans-serif/);

  await Promise.all([customerContext.close(), supportContext.close(), approverContext.close()]);
});

test("Issue #101 审批确认对话框在真实浏览器中管理和恢复焦点", async ({ browser }) => {
  resetApprovalFixture();
  const context = await newAcceptanceContext(browser, { viewport: { width: 1440, height: 960 } });
  const page = await context.newPage();
  try {
    await login(page, "internal", "approver-demo");
    const row = page.locator(".approval-table-row", { hasText: "80000000…0008" });
    await row.getByRole("button", { name: "领取审批" }).click();
    const trigger = page.getByRole("button", { name: "批准补偿" });
    await trigger.click();

    const dialog = page.getByRole("dialog", { name: "确认批准补偿" });
    const cancel = dialog.getByRole("button", { name: "取消" });
    await expect(cancel).toBeFocused();
    await dialog.getByRole("button", { name: "确认批准" }).focus();
    await page.keyboard.press("Tab");
    await expect(dialog.getByLabel("审批备注（可选）")).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  } finally {
    await context.close();
    resetApprovalFixture();
  }
});
