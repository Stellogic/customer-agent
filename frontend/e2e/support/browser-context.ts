import type { Browser, BrowserContextOptions } from "@playwright/test";

declare const process: { env: Record<string, string | undefined> };

export const issue80ContextOptions: BrowserContextOptions = {
  baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "https://browser-frontend:8443",
  ignoreHTTPSErrors: true,
};

export function newIssue80Context(browser: Browser, options: BrowserContextOptions = {}) {
  return browser.newContext({ ...issue80ContextOptions, ...options });
}
