import { expect, test } from "@playwright/test";
import { OPERATOR, VIEWER, csrf, instrumentBySymbol, login } from "./helpers";

const ORIGIN = "http://localhost:5174";

// Gate (BUILD_PLAN M4): no uncaught page errors or console errors during any workflow.
// Tests that deliberately provoke an HTTP error may list its status; Chrome logs those responses.
let consoleErrors: string[] = [];
let expectedStatuses: number[] = [];
test.beforeEach(({ page }) => {
  consoleErrors = [];
  expectedStatuses = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));
});
test.afterEach(() => {
  const unexpected = consoleErrors.filter(
    (text) => !expectedStatuses.some((status) => text.includes(`status of ${status} `)),
  );
  expect(unexpected, unexpected.join("\n")).toEqual([]);
});

test("1. watchlist membership persists across reload", async ({ page }) => {
  await login(page, OPERATOR);
  const name = `E2E ${Date.now()}`;
  await page.getByRole("button", { name: "+ New watchlist" }).click();
  await page.getByLabel("Watchlist name").fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByLabel("☆ adds to")).toHaveValue(/.+/);
  await expect(page.getByLabel("☆ adds to").locator("option:checked")).toHaveText(name);

  const target = await instrumentBySymbol(page.request, 3);
  await page.getByLabel("Search symbol or name").fill(target.symbol);
  await page.getByRole("button", { name: `Add ${target.symbol} to ${name}` }).click();
  await expect(page.getByRole("button", { name: `Remove ${target.symbol} from ${name}` })).toBeVisible();

  await page.reload();
  await page.getByLabel("Show").selectOption({ label: `Watchlist: ${name} (1)` });
  await page.getByLabel("Search symbol or name").fill("");
  const grid = page.getByRole("grid");
  await expect(grid.getByRole("gridcell").filter({ hasText: /^(● Fresh|■ Stale|No quote)$/ })).toHaveCount(1);
  await expect(grid.getByRole("link", { name: target.symbol, exact: true })).toBeVisible();
});

test("2. stale scenario → incident → ack/comment → recover → resolve → audit timeline", async ({ page }) => {
  await login(page, OPERATOR);
  const target = await instrumentBySymbol(page.request, 7);

  await page.goto("/system");
  await page.getByLabel("Scenario", { exact: true }).selectOption("STALE_QUOTES");
  await page.getByLabel("Instrument").selectOption(target.id);
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.getByText(`STALE_QUOTES started for ${target.symbol}`)).toBeVisible();

  await page.goto(`/incidents?symbol=${target.symbol}`);
  const link = page.getByRole("link", { name: /^#\d+$/ }).first();
  await expect(link).toBeVisible({ timeout: 40_000 }); // threshold 10s + evaluator tick
  await link.click();
  await expect(page.getByText("Status: OPEN")).toBeVisible();
  await expect(page.getByLabel("Incident state").getByText("Condition active")).toBeVisible();
  await expect(page.getByText(/no quote received for/)).toBeVisible();

  // Evidence → instrument detail and its chart
  await page.getByRole("link", { name: target.symbol }).click();
  await expect(page.getByRole("heading", { name: new RegExp(target.symbol) })).toBeVisible();
  await expect(page.getByRole("img", { name: /Mid price: \d+ points/ })).toBeVisible({ timeout: 20_000 });
  await page.goBack();

  await page.getByRole("button", { name: "Acknowledge" }).click();
  await expect(page.getByText("Status: ACKNOWLEDGED")).toBeVisible();
  await expect(page.getByText(/condition is still active/)).toBeVisible();
  await page.getByLabel("Comment").fill("E2E: investigating paused synthetic feed.");
  await page.getByRole("button", { name: "Post comment" }).click();
  await expect(page.getByText("E2E: investigating paused synthetic feed.")).toBeVisible();

  const incidentUrl = page.url();
  await page.goto("/system");
  await page.getByLabel("Scenario", { exact: true }).selectOption("RECOVERY");
  await page.getByLabel("Instrument (blank = all)").selectOption(target.id);
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.getByText(/Stopped 1 scenario/)).toBeVisible();

  await page.goto(incidentUrl);
  await expect(page.getByLabel("Incident state").getByText("Condition recovered")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Status: ACKNOWLEDGED")).toBeVisible(); // recovery never auto-resolves
  await page.getByLabel("Resolution note (required)").fill("Recovered after scenario stop.");
  await page.getByRole("button", { name: "Resolve incident" }).click();
  await expect(page.getByText("Status: RESOLVED")).toBeVisible();

  const timeline = page.getByRole("list").filter({ hasText: "Incident Opened" });
  for (const entry of ["Incident Opened", "Incident Acknowledged", "Comment", "Condition Recovered", "Incident Resolved"]) {
    await expect(timeline.getByText(entry, { exact: true })).toBeVisible();
  }
});

test("3. viewer cannot mutate through the UI or direct HTTP", async ({ page }) => {
  await login(page, VIEWER);
  await expect(page.getByText("Viewer (read-only)")).toBeVisible();
  await page.goto("/system");
  await expect(page.getByText("Viewers can see scenario state but cannot start or stop scenarios.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run scenario" })).toHaveCount(0);

  const target = await instrumentBySymbol(page.request, 0);
  await page.goto(`/instruments/${target.id}`);
  await expect(page.getByLabel("Threshold (seconds)")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save rule" })).toHaveCount(0);

  const token = await csrf(page.request);
  const headers = { "X-CSRF-Token": token, Origin: ORIGIN };
  const scenario = await page.request.post("/api/v1/demo/scenarios", { headers, data: { kind: "STALE_QUOTES", instrument_id: target.id } });
  expect(scenario.status()).toBe(403);
  expect(((await scenario.json()) as { error: { code: string } }).error.code).toBe("FORBIDDEN");
  const rules = (await (await page.request.get(`/api/v1/rules?instrument_id=${target.id}`)).json()) as { id: string; version: number }[];
  const rule = rules.at(0);
  if (!rule) throw new Error("expected a rule");
  const patch = await page.request.patch(`/api/v1/rules/${rule.id}`, { headers, data: { version: rule.version, threshold: "99" } });
  expect(patch.status()).toBe(403);
});

test("4. disconnect → resynchronization → live values resume without duplicate sockets", async ({ page }) => {
  let ticketRequests = 0;
  page.on("request", (req) => {
    if (req.url().endsWith("/api/v1/stream/ticket")) ticketRequests += 1;
  });
  const sockets: { url: string; closed: boolean }[] = [];
  page.on("websocket", (ws) => {
    const entry = { url: ws.url(), closed: false };
    sockets.push(entry);
    ws.on("close", () => (entry.closed = true));
  });
  await login(page, OPERATOR);
  await page.goto("/system");
  const clientPanel = page.locator("section").filter({ hasText: "Client stream (this browser)" });
  await expect(clientPanel.getByText("Snapshots").locator("..")).toContainText("1");

  const openedBefore = sockets.length;
  await page.getByLabel("Scenario", { exact: true }).selectOption("DISCONNECT_STREAM");
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(page.getByText(/Closed 1 live connection/)).toBeVisible();
  await expect(clientPanel.getByText("Snapshots").locator("..")).toContainText("2", { timeout: 15_000 });
  await expect(page.getByText("Stream live").first()).toBeVisible();

  const seqCell = clientPanel.getByText("Sequence").locator("..");
  const before = Number((await seqCell.innerText()).replace(/\D/g, ""));
  await expect.poll(async () => Number((await seqCell.innerText()).replace(/\D/g, "")), { timeout: 10_000 }).toBeGreaterThan(before);

  // The server closed our one socket; the client opened exactly one replacement (no duplicates).
  const opened = sockets.slice(openedBefore).filter((s) => s.url.endsWith("/ws/market"));
  expect(opened).toHaveLength(1);
  expect(opened[0]?.closed).toBe(false);
  expect(sockets.slice(0, openedBefore).filter((s) => !s.closed && s.url.endsWith("/ws/market")).length).toBeLessThanOrEqual(1);
  if (process.env.E2E_EXPECT_STREAM_TICKETS === "1") {
    // Split-origin mode: every socket (initial + reconnect) was authenticated by a fresh ticket.
    expect(ticketRequests).toBeGreaterThanOrEqual(2);
  } else {
    expect(ticketRequests).toBe(0);
  }
});

test("5. invalid threshold and stale-version edit show actionable messages", async ({ page }) => {
  expectedStatuses = [409]; // the stale-version save is supposed to be rejected
  await login(page, OPERATOR);
  const target = await instrumentBySymbol(page.request, 11);
  await page.goto(`/instruments/${target.id}`);
  const staleRule = page.getByRole("form", { name: "Stale quote rule" });
  const input = staleRule.getByLabel("Threshold (seconds)");

  await input.fill("0");
  await expect(staleRule.getByText("Threshold must be between 1 and 3600 seconds.")).toBeVisible();
  await input.fill("12.345");
  await expect(staleRule.getByText("Use at most two decimal places.")).toBeVisible();

  // Another operator changes the rule after this page loaded.
  const rules = (await (await page.request.get(`/api/v1/rules?instrument_id=${target.id}&rule_type=STALE`)).json()) as { id: string; version: number }[];
  const rule = rules.at(0);
  if (!rule) throw new Error("expected a rule");
  const token = await csrf(page.request);
  const concurrent = await page.request.patch(`/api/v1/rules/${rule.id}`, {
    headers: { "X-CSRF-Token": token, Origin: ORIGIN },
    data: { version: rule.version, threshold: "25" },
  });
  expect(concurrent.status()).toBe(200);

  await input.fill("15");
  await staleRule.getByRole("button", { name: "Save rule" }).click();
  await expect(staleRule.getByText("Someone else changed this rule.")).toBeVisible();
  await staleRule.getByRole("button", { name: "Reload latest rule" }).click();
  await expect(page.getByRole("form", { name: "Stale quote rule" }).getByLabel("Threshold (seconds)")).toHaveValue("25");
});

test("6. public demo visitor is read-only (UI and API)", async ({ page }) => {
  expectedStatuses = [403]; // the direct write attempt below must be rejected
  await page.goto("/login");
  await page.getByRole("button", { name: "Explore the live demo (read-only)" }).click();
  await expect(page.getByRole("heading", { name: "Market monitor" })).toBeVisible();
  await expect(page.getByText("Public demo (read-only)")).toBeVisible();
  await expect(page.getByRole("note")).toContainText("simulated");
  await expect(page.getByText("Stream live").first()).toBeVisible({ timeout: 15_000 });
  await page.getByRole("note").getByRole("link", { name: "How to explore" }).click();
  await expect(page.getByRole("heading", { name: "How to explore MarketOps" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("button", { name: "+ New watchlist" })).toHaveCount(0);
  await page.goto("/system");
  await expect(page.getByRole("button", { name: "Run scenario" })).toHaveCount(0);

  const token = await csrf(page.request);
  const r = await page.request.post("/api/v1/watchlists", {
    headers: { "X-CSRF-Token": token, Origin: ORIGIN },
    data: { name: "public visitor" },
  });
  expect(r.status()).toBe(403);
  expect(((await r.json()) as { error: { code: string } }).error.code).toBe("PUBLIC_DEMO_READ_ONLY");
});
