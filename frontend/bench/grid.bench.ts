/**
 * Larger-grid fixture measurement (not part of CI). Requires:
 *   MARKETOPS_SIMULATOR_UPDATES_PER_SECOND=250 scripts/bench_backend.sh 1000   (backend :8002)
 *   npx vite --port 5175 with MARKETOPS_BACKEND_URL=http://127.0.0.1:8002      (started by config)
 *   BENCH_PASSWORD=<operator password from .env> npx playwright test -c bench/playwright.bench.config.ts
 * Records: time from navigation to first rendered grid row, rendered row count, and frame
 * timings while scrolling the grid for 10 s with live updates (requestAnimationFrame deltas).
 */
import { expect, test } from "@playwright/test";
import { writeFileSync, mkdirSync } from "node:fs";

test("1,000-instrument monitor renders and scrolls", async ({ page, browserName }) => {
  const password = process.env.BENCH_PASSWORD;
  if (!password) throw new Error("set BENCH_PASSWORD");
  await page.goto("/login");
  await page.getByLabel("Email").fill("operator@marketops.local");
  await page.getByLabel("Password").fill(password);
  const t0 = Date.now();
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("grid").getByRole("row").nth(5)).toBeVisible({ timeout: 30_000 });
  const firstRowsMs = Date.now() - t0;
  await expect(page.getByText("Fresh instruments")).toBeVisible();

  const frames = await page.evaluate(async () => {
    // The grid's vertical scroller: the largest scrollable element inside role=grid.
    const viewport = [...document.querySelectorAll("main *")]
      .filter((el) => el.scrollHeight > el.clientHeight + 10 && getComputedStyle(el).overflowY !== "visible")
      .sort((a, b) => b.scrollHeight - a.scrollHeight)
      .at(0);
    if (!viewport) throw new Error("no grid viewport");
    const deltas: number[] = [];
    let last = performance.now();
    const end = last + 10_000;
    let direction = 1;
    await new Promise<void>((resolve) => {
      const tick = (now: number) => {
        deltas.push(now - last);
        last = now;
        viewport.scrollTop += 120 * direction;
        if (viewport.scrollTop + viewport.clientHeight >= viewport.scrollHeight - 2) direction = -1;
        if (viewport.scrollTop <= 0) direction = 1;
        if (now < end) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    return { deltas, scroller: `${viewport.className} (scrollHeight ${viewport.scrollHeight}px)` };
  });
  const { deltas: frameDeltas, scroller } = frames;
  const sorted = [...frameDeltas].sort((a, b) => a - b);
  const at = (p: number) => sorted[Math.max(0, Math.ceil((p / 100) * sorted.length) - 1)] ?? null;
  const total = await page.evaluate(() => document.body.innerText.match(/Fresh instruments\s+([\d,]+)/)?.[1] ?? null);
  const result = {
    browser: browserName,
    viewport: page.viewportSize(),
    instrumentsFreshAtEnd: total,
    navigationToRowsMs: firstRowsMs,
    scrollSeconds: 10,
    scroller,
    frames: frameDeltas.length,
    fps: Math.round((frameDeltas.length / 10) * 10) / 10,
    frameMs: { p50: at(50), p95: at(95), p99: at(99), max: sorted.at(-1) ?? null },
    longFramesOver50ms: frameDeltas.filter((f) => f > 50).length,
  };
  mkdirSync("../benchmarks/out", { recursive: true });
  writeFileSync(`../benchmarks/out/grid-1000-${Date.now()}.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
});
