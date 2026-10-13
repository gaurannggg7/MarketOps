import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: /.*\.bench\.ts/,
  workers: 1,
  timeout: 120_000,
  reporter: "list",
  use: { baseURL: "http://localhost:5175" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } }],
  webServer: {
    command: "npx vite --port 5175 --strictPort",
    url: "http://localhost:5175",
    cwd: "..",
    reuseExistingServer: true,
    env: { MARKETOPS_BACKEND_URL: "http://127.0.0.1:8002", MARKETOPS_WEB_PORT: "5175" },
  },
});
