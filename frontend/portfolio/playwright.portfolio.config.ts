import { defineConfig, devices } from "@playwright/test";

/** Screenshots + restart/recovery check against an already running deployment (local or cloud). */
export default defineConfig({
  testDir: ".",
  testMatch: /.*\.portfolio\.ts/,
  workers: 1,
  timeout: 360_000,
  reporter: "list",
  use: {
    baseURL: process.env.PORTFOLIO_URL ?? "http://localhost:4174",
    ignoreHTTPSErrors: process.env.PORTFOLIO_INSECURE === "1",
    colorScheme: "light",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
