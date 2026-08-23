import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  build: {
    manifest: true,
  },
  test: {
    environment: "jsdom",
    fileParallelism: false,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: "./src/test-setup.ts",
    testTimeout: 30_000,
  },
  server: {
    allowedHosts: ["localhost", "127.0.0.1", "frontend"],
    proxy: {
      "/api": process.env.VITE_DEV_PROXY_TARGET ?? "http://localhost:8080",
    },
  },
});
