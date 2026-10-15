import { defineConfig } from "@playwright/test";
import base, { E2E_PASSWORDS } from "./playwright.config";

/**
 * Same workflows as playwright.config.ts, but in the split-origin topology used by the free
 * hosting plan (Vercel frontend + Render backend): a production build served by `vite preview`
 * proxies /api (like the vercel.json rewrite) while the WebSocket connects directly to a
 * different host (127.0.0.1), so no session cookie reaches it and stream tickets are required.
 */
// Read by e2e/workflows.spec.ts (workers load this config too): assert the ticket path is used.
process.env.E2E_EXPECT_STREAM_TICKETS = "1";

export default defineConfig({
  ...base,
  webServer: [
    {
      command: "bash ../scripts/e2e_backend.sh",
      url: "http://127.0.0.1:8001/api/v1/health/ready",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { ...E2E_PASSWORDS, MARKETOPS_STREAM_TICKET_AUTH_ENABLED: "true" },
      stdout: "pipe",
    },
    {
      command: "npx vite build --mode production && npx vite preview --port 5174 --strictPort",
      url: "http://localhost:5174",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        VITE_STREAM_URL: "ws://127.0.0.1:8001/ws/market",
        MARKETOPS_BACKEND_URL: "http://127.0.0.1:8001",
        MARKETOPS_WEB_PORT: "5174",
      },
    },
  ],
});
