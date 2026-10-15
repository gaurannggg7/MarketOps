# MarketOps — portfolio evidence

**Repository:** https://github.com/gaurannggg7/MarketOps (public)
**Public demo:** not deployed yet — URL will be added only after it is verified in a browser.
**Context:** prepared for the NYSE / ICE Full Stack Software Engineer application (Job ID 13416).
All market data is synthetic; no affiliation with ICE or NYSE.

## What it is
A market-operations console: an analyst monitors quote freshness and spreads for 200 synthetic
instruments, the server opens incidents when feeds go stale or spreads widen, and operators
acknowledge, comment, and resolve them with a full audit trail.

## Technologies actually used
React 19, TypeScript (strict), Vite 8, React Router 8, Tailwind 4, TanStack Query 5, AG Grid
Community 36, D3 (scale/shape/array/time-format) · Python 3.13, FastAPI, Pydantic 2,
SQLAlchemy 2.1 (async, psycopg 3), Alembic, Argon2 · PostgreSQL 17 · WebSockets · pytest, Vitest +
React Testing Library, Playwright · Ruff, mypy (strict), ESLint (strictTypeChecked) · Docker,
Docker Compose, nginx, Caddy · GitHub Actions · planned hosting: Vercel, Render, Neon.
Development: Claude Code (Opus 5.5) with one delegated subagent task — see `ai-development-log.md`.

## Features implemented (all exercised by automated tests)
1. Live market grid (AG Grid transactions, ~50 updates/s, cell flashes, stable selection).
2. Snapshot + epoch/sequence WebSocket protocol with duplicate/gap/epoch handling, bounded queues,
   reconnect with backoff, and single-use stream tickets for split-origin hosting.
3. Watchlists persisted in PostgreSQL, owner-scoped.
4. Alert rules (stale / wide spread) with unit-aware validation and optimistic versioning.
5. Server-side, clock-driven incident detection; one unresolved incident per rule enforced by a
   PostgreSQL partial unique index (tested with 6 concurrent evaluators).
6. Incident acknowledgment, assignment, comments, resolution (requires recovery + note), audit timeline.
7. D3 price/spread charts over sampled history; Infinite Row Model events grid over 100k rows.
8. System health: client transport vs server feed/evaluator/database/persistence; DB outage is
   visibly distinct and self-recovers.
9. Public read-only demo mode and an automated, clearly labelled demo operator.

## Test counts (latest local run, 2026-10-15)
| Suite | Count | Where it ran |
| --- | --- | --- |
| Backend pytest (real PostgreSQL) | 62 passed | local; 49 passed on GitHub Actions run 38485052338 (`40a52aa`) |
| Frontend Vitest + RTL | 84 passed | local; 80 passed on GitHub Actions run 38485052338 |
| Playwright workflows | 6 passed (same-origin) + 6 passed (split-origin) | local; 5 passed on GitHub Actions run 38485052338 |

## Measured performance (local, see `performance.md`)
- 10-minute run, 5 stream clients: 50 quotes/s per client, **0 sequence gaps**, delivery lag
  p95 4.6–6.7 ms (p99 < 10 ms); all REST endpoints p95 < 85 ms with 100k events; recovery
  snapshot 9–15 ms; RSS 65–103 MB after warm-up. (Apple M3, Docker PostgreSQL, loopback.)
- 1,000-instrument grid: 60 fps scrolling, 0 frames > 50 ms (headless Chromium, dev build).
- Free-tier rehearsal at 0.1 CPU / 512 MB: 50 quotes/s, 0 gaps, lag p95 15 ms; cold start 34–51 s.

## Security architecture
Server-side sessions (HttpOnly/Secure/SameSite cookies, hashed tokens), CSRF + Origin checks,
role enforcement in the API, read-only public sessions, rate limits, TLS to the database,
single-use stream tickets, no credentials in URLs or the bundle. Details: `production-readiness.md`.

## Deployment status
Not deployed. Configuration for Vercel + Render Free + Neon Free is prepared and rehearsed
locally (`deployment.md`, `cloud-cicd-evidence.md`). Awaiting the owner's authorization to push
and to create the cloud resources.

## Screenshots (`docs/screenshots/`, captured from the running app with Playwright)
`00-login-demo-entry.png`, `01-market-monitor.png`, `02-instrument-charts-rules.png`,
`03-incident-detail-timeline.png`, `04-system-status.png`, `05-d3-price-chart.png`,
`06-incident-list.png`, `07-how-to-explore.png`, `08-mobile-monitor.png` — taken from the local
free-tier rehearsal (public demo session; no credentials visible).

## Known limitations
Synthetic data only; single backend worker; sampled (not tick-level) history; free-tier cold
starts; no human security review yet; cloud behavior not yet measured.
