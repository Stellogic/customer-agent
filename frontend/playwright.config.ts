import { defineConfig } from "@playwright/test";
import { acceptanceContextOptions } from "./e2e/support/browser-context";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  use: {
    ...acceptanceContextOptions,
    trace: "retain-on-failure",
  },
});
