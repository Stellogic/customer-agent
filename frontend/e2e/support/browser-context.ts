import type { Browser, BrowserContextOptions } from "@playwright/test";

declare const process: { env: Record<string, string | undefined> };

export const acceptanceContextOptions: BrowserContextOptions = {
  baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "https://browser-frontend:8443",
  ignoreHTTPSErrors: true,
};

export function newAcceptanceContext(browser: Browser, options: BrowserContextOptions = {}) {
  return browser.newContext({ ...acceptanceContextOptions, ...options });
}

export const newIssue80Context = newAcceptanceContext;
