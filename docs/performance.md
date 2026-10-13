# Performance

Targets from BUILD_PLAN §11 are goals, not claims. Everything below is a single measured run on
one machine; numbers will differ elsewhere. Raw JSON is committed under `benchmarks/results/`.

## Environment
- Apple M3 (8 cores), 16 GB RAM, macOS 15.2 (arm64); Python 3.13.5; Node 25.2.1.
- PostgreSQL 17.11 in Docker Desktop; backend = one uvicorn worker, `--log-level warning`.
- Load generator on the same machine (loopback), so client CPU competes with the server.

## Default workload (10 minutes)
Command: `scripts/bench_backend.sh` (fresh `marketops_bench` DB, 200 instruments, default rules,
100,000 synthetic events, `ANALYZE`), then
`scripts/benchmark.py --duration 600 --clients 5 --rest-concurrency 4`.
Run window: ≈19:05–19:15 UTC on 2026-10-13. (That run's JSON has one field named `started_at`
that actually holds the completion time; the script has since been fixed to record both.)
Raw: `benchmarks/results/default-workload-600s.json`.

### Stream (5 WebSocket clients for 600 s)
| Metric | Result |
| --- | --- |
| Configured / server-observed rate | 50 quotes/s / 50.0 quotes/s |
| Per-client received | 6,014 delta batches, 30,070 quotes each (50.1 quotes/s) |
| Sequence gaps / reconnects / overflow disconnects | 0 / 0 / 0 |
| Delivery lag (receive time − delta `ts`), per client | p50 0.9–1.8 ms · p95 4.6–6.7 ms · p99 8.7–9.9 ms · max ≈57 ms |

Batches were ≈10/s (100 ms coalescing), each with ≈5 quotes.

### REST (4 sequential workers with a 50 ms pause, concurrent with the stream; nearest-rank percentiles)
| Endpoint | n | p50 ms | p95 ms | p99 ms |
| --- | --- | --- | --- | --- |
| `GET /instruments?limit=1000` (200 rows + incident counts) | 3,609 | 28.4 | 40.9 | 72.9 |
| `GET /market/snapshot` | 3,605 | 19.3 | 24.1 | 27.3 |
| `GET /events` first page, newest first (100k rows) | 3,605 | 51.9 | 60.4 | 93.5 |
| `GET /events` offset 50,000 | 3,605 | 71.0 | 84.4 | 108.4 |
| `GET /events` type filter, sorted by symbol | 3,605 | 32.3 | 43.0 | 67.3 |
| `GET /instruments/{id}/history?range=1h` | 3,605 | 14.5 | 20.1 | 24.0 |
| `GET /incidents?limit=25` | 3,605 | 16.6 | 25.0 | 29.8 |
| `GET /system/status` | 3,605 | 15.0 | 25.3 | 31.3 |
No request errors. All measured endpoints met the "p95 < 300 ms local" aim under this load.
The events endpoint spends most of its time on `count(*)` over 100k rows plus `OFFSET`; deep
offsets cost more (p95 84 ms at offset 50,000). Keyset pagination would be the next step if the
fixture grew by an order of magnitude.

### Recovery and memory
- Disconnect → replacement connection's snapshot received: 8.6–15.3 ms over 5 trials. This
  script reconnects immediately; browsers add the 150 ms resync delay (and backoff only for
  abnormal closes). Target was < 5 s.
- Backend RSS (ps, every 5 s): 168 MB at the first sample, then 65.5–102.8 MB from 60 s to the
  end, 99.5 MB at the end. No upward trend over the run; macOS RSS reporting is noisy, so this is
  evidence of boundedness for 10 minutes, not a leak proof.

## Larger grid fixture (1,000 instruments)
Command: `MARKETOPS_SIMULATOR_UPDATES_PER_SECOND=250 scripts/bench_backend.sh 1000`, then
`BENCH_PASSWORD=… npx playwright test -c bench/playwright.bench.config.ts` (Vite dev server,
headless Chromium 1280×900). The update rate was raised to 250/s so every instrument still
updates within the 10 s stale threshold. Raw: `benchmarks/results/grid-1000-instruments.json`.
| Metric | Result |
| --- | --- |
| Sign-in click → first grid rows visible | 481 ms (includes login request and page navigation) |
| Scrolled element | the AG Grid viewport (`ag-grid-viewport`, 30,033 px tall) |
| 10 s continuous scroll with live updates | 601 frames (60.1 fps); frame time p50 16.7 ms, p95 16.7 ms, max 33.3 ms; 0 frames > 50 ms |
Caveats: headless Chromium on a fast laptop with a development (unminified) build; real
devices and production builds will differ.

## Not measured
- Many simultaneous browsers; WAN latency; the nginx container path under load.
- Frontend memory over long sessions (chart buffers are bounded at 600 history points per series
  by the API; the stream store keeps one quote per instrument).
- Throughput limits (no attempt to find the saturation point).
