/**
 * Real screenshots from a running MarketOps (public read-only demo session, no credentials),
 * plus an optional restart/recovery measurement when RESTART_CMD is set.
 *   PORTFOLIO_URL=https://… npx playwright test -c portfolio/playwright.portfolio.config.ts
 */
import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const OUT = process.env.SCREENSHOT_DIR ?? "../docs/screenshots";
mkdirSync(OUT, { recursive: true });

async function enterDemo(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "Explore the live demo (read-only)" }).click({ timeout: 180_000 });
  await expect(page.getByRole("heading", { name: "Market monitor" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Stream live").first()).toBeVisible({ timeout: 60_000 });
}

test("capture portfolio screenshots", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Explore the live demo (read-only)" })).toBeVisible({ timeout: 180_000 });
  await page.screenshot({ path: `${OUT}/00-login-demo-entry.png` });

  await enterDemo(page);
  await expect(page.getByRole("grid").getByRole("gridcell", { name: /Fresh|Stale/ }).first()).toBeVisible();
  await page.waitForTimeout(1500); // let a few live batches flash for a representative frame
  await page.screenshot({ path: `${OUT}/01-market-monitor.png` });

  await page.getByRole("grid").getByRole("link").first().click();
  await expect(page.getByRole("img", { name: /Mid price: \d+ points/ })).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: `${OUT}/02-instrument-charts-rules.png`, fullPage: true });
  const chart = page.locator("figure").filter({ has: page.getByRole("img", { name: /Mid price/ }) });
  const box = await chart.boundingBox();
  if (box) await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.55);
  await chart.screenshot({ path: `${OUT}/05-d3-price-chart.png` });

  await page.goto("/incidents?status=RESOLVED");
  const first = page.getByRole("link", { name: /^#\d+$/ }).first();
  await expect(first).toBeVisible({ timeout: 240_000 }); // autopilot resolves one every few minutes
  await first.click();
  await expect(page.getByText("Incident Resolved")).toBeVisible();
  await page.screenshot({ path: `${OUT}/03-incident-detail-timeline.png`, fullPage: true });

  await page.goto("/incidents?status=all");
  await expect(page.getByRole("table")).toBeVisible();
  await page.screenshot({ path: `${OUT}/06-incident-list.png` });

  await page.goto("/system");
  await expect(page.getByText("Synthetic feed", { exact: true })).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: `${OUT}/04-system-status.png`, fullPage: true });

  await page.goto("/guide");
  await page.screenshot({ path: `${OUT}/07-how-to-explore.png` });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByText("Stream live").first()).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: `${OUT}/08-mobile-monitor.png` });
});

test("backend restart → browser resynchronizes into a new epoch", async ({ page }) => {
  const cmd = process.env.RESTART_CMD;
  test.skip(!cmd, "set RESTART_CMD to run the restart/recovery measurement");
  await enterDemo(page);
  await page.goto("/system");
  const panel = page.locator("section").filter({ hasText: "Client stream (this browser)" });
  const epochCell = panel.getByText("Epoch", { exact: true }).locator("..");
  await expect(epochCell).not.toContainText("—");
  const epochBefore = (await epochCell.innerText()).replace("Epoch", "").trim();

  const t0 = Date.now();
  execSync(cmd ?? "", { stdio: "inherit" });
  const restartReturnedMs = Date.now() - t0;
  // Transport state must leave "live" (the socket really dropped) …
  await expect(panel.getByText(/Reconnecting|Resynchronizing|Connecting/)).toBeVisible({ timeout: 120_000 });
  const sawDegradedMs = Date.now() - t0;
  // … then recover on its own into a fresh epoch from a new snapshot.
  await expect(panel.getByText("Stream live")).toBeVisible({ timeout: 300_000 });
  await expect(epochCell).not.toContainText(epochBefore, { timeout: 30_000 });
  const recoveredMs = Date.now() - t0;
  const epochAfter = (await epochCell.innerText()).replace("Epoch", "").trim();
  const result = {
    target: process.env.PORTFOLIO_URL ?? "http://localhost:4174",
    restartCommand: cmd,
    epochBefore,
    epochAfter,
    restartCommandReturnedMs: restartReturnedMs,
    clientSawDegradedStateMs: sawDegradedMs,
    clientLiveInNewEpochMs: recoveredMs,
    measuredAt: new Date().toISOString(),
  };
  mkdirSync("../benchmarks/out", { recursive: true });
  writeFileSync(`../benchmarks/out/restart-recovery-${Date.now()}.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
  expect(epochAfter).not.toBe(epochBefore);
});
