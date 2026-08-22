import { defineConfig } from "@playwright/test";
import { issue80ContextOptions } from "./e2e/support/browser-context";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  use: {
    ...issue80ContextOptions,
    trace: "retain-on-failure",
  },
});
