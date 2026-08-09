import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
  },
  server: {
    allowedHosts: ["localhost", "127.0.0.1", "frontend"],
    proxy: {
      "/api": process.env.VITE_DEV_PROXY_TARGET ?? "http://localhost:8080",
    },
  },
});
