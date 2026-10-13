import { defineConfig, devices } from "@playwright/test";

// Test-only credentials for the throwaway `marketops_e2e` database (seeded by scripts/e2e_backend.sh).
export const E2E_PASSWORDS = {
  DEMO_OPERATOR_PASSWORD: "e2e-operator-password",
  DEMO_OPERATOR2_PASSWORD: "e2e-operator2-password",
  DEMO_VIEWER_PASSWORD: "e2e-viewer-password",
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // one shared backend runtime and database per run
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:5174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } }],
  webServer: [
    {
      command: "bash ../scripts/e2e_backend.sh",
      url: "http://127.0.0.1:8001/api/v1/health/ready",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { ...E2E_PASSWORDS },
      stdout: "pipe",
    },
    {
      command: "npx vite --port 5174 --strictPort",
      url: "http://localhost:5174",
      reuseExistingServer: false,
      timeout: 60_000,
      env: { MARKETOPS_BACKEND_URL: "http://127.0.0.1:8001", MARKETOPS_WEB_PORT: "5174" },
    },
  ],
});
