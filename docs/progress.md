# MarketOps progress log

Live status for humans and agents. Update at every milestone gate. Newest gate entries are at the
bottom of "Gate evidence".

## Environment observed (2026-10-13)

- macOS 24.2 (Darwin), Apple M3, 16 GB RAM.
- Node 25.2.1 / npm 11.6.2; Python 3.13.5 (Anaconda); Docker 29.0.1 (Docker Desktop);
  a pre-existing Homebrew PostgreSQL 16 occupies port 5432 with password auth we do not have, so
  MarketOps' PostgreSQL runs in Docker on **port 55432**.
- Git remote `origin` = https://github.com/gaurannggg7/MarketOps.git. **Owner instruction: do not
  push without permission.** A local `.git/hooks/pre-push` guard blocks pushes.

## Milestone checklist

Status as of 2026-10-13: M0–M5 complete locally; M6 complete except deployment (not authorized,
no credentials) and CI execution on GitHub (requires a push, which needs owner permission).

### M0 — foundation and prototype ✅
- [x] AGENTS.md, CLAUDE.md, progress checklist
- [x] ADRs 0001–0005 (stack, single worker, sessions/CSRF, stream protocol, incident integrity)
- [x] Low-fidelity layouts + primary workflow (`docs/prototype/layouts.md`; drafted during build)
- [x] Backend skeleton, pinned deps with hashed lockfiles; frontend skeleton with lockfile
- [x] Models + Alembic `0001` (partial unique indexes, checks); `alembic check` clean
- [x] Deterministic seed; Docker Compose; `.env.example`; Makefile; ruff/mypy/eslint/tsc; CI workflow
- [x] Gate: clean clone → install → migrate → seed → readiness 200; build + import; secret scan clean

### M1 — first durable vertical slice ✅
- [x] Login/logout/me/session probe, CSRF + Origin, throttling, idle/absolute expiry
- [x] Roles enforced server-side; catalog; watchlists (owner-scoped, idempotent membership)
- [x] History endpoint + D3 charts; error payload + request IDs; generated API types + drift check
- [x] Gate: logins work; watchlist survives reload and runtime restart; cross-user change → 404; viewer writes → 403

### M2 — stream and grid behavior ✅
- [x] Lifespan simulator (200 instruments, 50 updates/s, seeded); hub with atomic register+snapshot
- [x] `/ws/market` auth + Origin; heartbeats with server time + stale set; bounded queues
- [x] Sampled persistence (≤1/s/instrument, batched) + retention (`make prune`, 10-min loop)
- [x] Client store/reducer, backoff + jitter, cleanup; AG Grid transactions, flashes, stable IDs
- [x] Events endpoint + Infinite Row Model grid
- [x] Gate: live updates; disconnect recovers; dup/gap/epoch handled (unit + E2E); events sort/filter against PostgreSQL

### M3 — alert-to-resolution workflow ✅
- [x] Rules with versions; evaluator with warm-up; episodes; one-unresolved-incident index
- [x] Transitions, assignment, comments, optimistic concurrency, transactional audit, timeline
- [x] Gate: stale + spread each open one incident; no duplicates (incl. 6-way race); full lifecycle; invalid transitions 409; new incident after resolution

### M4 — operational UI and polish ✅
- [x] System status with client vs server health; scenarios with descriptions/expiry; reset with typed confirmation
- [x] DB outage visibly distinct (verified by stopping PostgreSQL: stream live, DB down, auto-recovery)
- [x] Labels/focus/keyboard (chart arrow keys), 390 px layout (no page scroll), empty/error states
- [x] Gate: demo works end-to-end in browser; viewer read-only server-enforced; E2E fails on any console error

### M5 — verification and performance ✅
- [x] 49 pytest, 80 Vitest, 5 Playwright; 10-min benchmark + 1,000-instrument grid measurement
- [x] Gate: all checks pass; `docs/performance.md` records machine, workload, duration, percentile method

### M6 — release and handoff (local) ✅ / deployment ⛔ not authorized
- [x] Versioned images; nginx single origin with WS upgrade; HTTPS overlay verified (Secure cookie)
- [x] README, architecture, api, runbook (incl. rollback), deployment, testing, performance, demo script, CHANGELOG, review checklist, AI log
- [x] Smoke checks 7/7 on :8080 and on HTTPS :8443
- [ ] Hosted deployment — blocked: needs owner authorization, hosting account, credentials
- [ ] CI run on GitHub — blocked: requires pushing, which the owner has not authorized

## Gate evidence

### M0–M3 (backend core, 2026-10-13)
- Files: `backend/app/**`, `backend/alembic/versions/0001_initial_schema.py`, `backend/tests/**`.
- Checks: `alembic upgrade head && alembic downgrade base && alembic upgrade head && alembic check`
  → clean; `ruff check`, `ruff format --check`, `mypy app tests` → pass; `pytest -q` → 48 passed
  (49 after the session-probe test). Manual: uvicorn + curl login/catalog/status; Python
  websockets client saw consecutive seqs and 403 for bad Origin / no cookie.
- Bugs fixed: expired-attribute access after rollback (rule PATCH); Decimal formatting in
  incident reasons.

### M1–M4 (frontend + workflow)
- Files: `frontend/**`, `scripts/{smoke,e2e_backend,secret_scan}.*`, Dockerfiles, nginx config.
- Checks: `tsc -b`, `eslint --max-warnings=0`, `vite build`; Vitest 80/80 (subagent-written,
  re-run by main agent); Playwright 5/5 (3 consecutive clean runs, then with console gate).
  Manual in-app browser: full demo flow (incident #1001), mobile 390 px, DB outage.
- Limitations found and fixed: freshness cell refresh, rule-edit preservation, watchlist star
  target, session-probe error state, mobile grid height.

### M5–M6
- Benchmark: `benchmarks/results/default-workload-600s.json`, `grid-1000-instruments.json`.
- `make check` (clean clone and working tree) → pass; `make api-check` → no drift;
  `make secrets-scan` → clean; `make images && make stack-up && make stack-seed && make smoke` →
  7/7; HTTPS overlay smoke → 7/7.

## Next steps / continuation
1. Owner decision: push to GitHub (then watch the first CI run; fix any Linux-only issues).
2. Optional: register individual AG Grid Community modules to shrink the ~1.1 MB grid chunk.
3. Optional: keyset pagination for events if the fixture grows ≥1M rows.
4. Human review using `docs/review-checklist.md`.
5. Deployment only after authorization: follow `docs/deployment.md`.
