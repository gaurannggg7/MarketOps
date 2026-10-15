# Cloud, Docker, and CI/CD evidence

Facts only, with their source. Items marked **PENDING** require the owner's authorization
(push or cloud deployment) and are deliberately not claimed.

## GitHub Actions
| Run | Commit | Trigger | Result | Jobs | Source |
| --- | --- | --- | --- | --- | --- |
| [38485052338](https://github.com/gaurannggg7/MarketOps/actions/runs/38485052338) | `40a52aa` | push to `main` (2026-10-13 23:34 UTC; pushed outside the agent session) | **success** | backend ✔ (ruff, mypy, migrations + `alembic check`, 49 pytest on PostgreSQL 17, API drift), frontend ✔ (eslint, tsc, 80 Vitest, build), e2e ✔ (5 Playwright workflows), images ✔ (secret scan, `docker compose build`) | GitHub REST API `actions/runs` + `jobs`, read 2026-10-15 |
| — | `6774b1f`…`HEAD` (local) | — | **PENDING** — not pushed | adds split-origin Playwright, stack smoke, separate secret-scan job, release workflow | — |

The CI status badge in the README reflects whatever GitHub currently reports for `main`.

## Local verification of the unpushed commits (2026-10-15, Apple M3 / macOS 15.2)
| Check | Command | Result |
| --- | --- | --- |
| Lint + strict types + tests + build | `make check` | pass — 62 pytest (PostgreSQL), 84 Vitest, Vite build, backend import |
| E2E, same-origin | `cd frontend && npx playwright test` | 6/6 passed |
| E2E, split-origin (Vercel+Render layout, stream tickets asserted) | `npx playwright test -c playwright.split.config.ts` | 6/6 passed |
| Secret scan | `make secrets-scan` | no findings (tracked files) |
| Production Compose (Caddy TLS, fresh volumes, deploy order) | see deployment.md "Paid fallback" | 7/7 HTTPS smoke checks; DB port not published; autopilot resolved incidents with full audit trail |
| Free-tier rehearsal: backend `--cpus 0.1 --memory 512m`, TLS PostgreSQL with Neon-style URL (`sslmode=require&channel_binding=require`), prod frontend build behind proxy, WS direct with tickets | `scripts/smoke.py` with `MARKETOPS_STREAM_URL` | 8/8 smoke checks; DB sessions TLSv1.3 |
| Cold start at 0.1 CPU | `docker run --cpus 0.1 …` timing | first boot (migrate + seed) 51 s; restart on migrated DB 34 s (in-process bootstrap; was 101–102 s before) |
| Load at 0.1 CPU (2 min, 2 stream clients) | `scripts/benchmark.py --duration 120` | 50 quotes/s, 0 gaps, lag p95 15 ms / p99 100 ms, REST p95 152–339 ms, RSS ≈ 120 MB |
| Restart/recovery (browser) | `RESTART_CMD="docker restart mo-free"` portfolio script | stream degraded immediately; live again in a **new epoch after 35.8 s** without page reload |

These are local container rehearsals, not cloud measurements.

## Docker
- Images: `marketops-backend:1.1.0` (python:3.13.5-slim, hashed lockfile, non-root, entrypoint
  migrations/bootstrap, `$PORT`), `marketops-web:1.1.0` (node:24.11 build → nginx:1.29.3 with
  per-IP rate/connection limits, WS upgrade).
- Health checks: backend `/api/v1/health/ready` in Compose; Render uses `/api/v1/health/live`.
- Non-destructive restarts: free-tier rehearsal container restarted against existing data —
  row counts before/after identical (incidents 7, watchlist items 18, audit events 43, users 4),
  operator login still valid (no password re-hash), new stream epoch, browser resynced.

## Cloud deployment — PENDING authorization
Planned: Vercel Hobby + Render Free + Neon Free ($0/month), see `docs/deployment.md`.
To be filled after deployment, with evidence:
| Item | Result |
| --- | --- |
| Public URL | PENDING |
| Deployed commit SHA | PENDING |
| HTTPS (Vercel, Render) / WSS | PENDING |
| Cookie flags on Vercel origin | PENDING |
| Migrations at head on Neon | PENDING |
| Persistence across Render restart | PENDING |
| Public smoke (`scripts/smoke.py` with stream ticket) | PENDING |
| Incident workflow in production (autopilot timeline + operator login) | PENDING |
| Cloud restart/recovery measurement | PENDING |
| Cold start from idle (Render spin-up + boot) | PENDING |

## Limitations (current)
- No cloud deployment yet; no CI run yet for the split-origin changes.
- The release workflow has never run (needs secrets/variables that only exist after deployment).
- Free tier: cold starts of roughly 1–2 minutes after 15 minutes idle; single 0.1-CPU instance;
  Neon compute budget (100 CU-hours/month) caps awake time.
