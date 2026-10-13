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

### M0 — foundation and prototype
- [ ] AGENTS.md, CLAUDE.md, progress checklist
- [ ] ADRs: stack, single worker, auth/session
- [ ] Low-fidelity layouts / navigation / primary workflow prototype doc
- [ ] Backend skeleton (FastAPI, settings, health endpoints), pinned deps + lockfile
- [ ] Frontend skeleton (Vite, React, TS strict, Tailwind, Router), lockfile
- [ ] SQLAlchemy models + Alembic initial migration (partial unique indexes)
- [ ] Deterministic seed command
- [ ] Docker Compose (postgres, backend, frontend/proxy), .env.example, Makefile
- [ ] Quality tooling: ruff, mypy, eslint, tsc; CI workflow skeleton
- [ ] Gate: compose up → readiness OK; frontend build; backend import; secret scan

### M1 — first durable vertical slice
- [ ] Login/logout/me with server sessions, CSRF, Origin checks, throttling
- [ ] Roles VIEWER/OPERATOR enforced server-side
- [ ] Instruments catalog + detail endpoints
- [ ] Watchlist CRUD + idempotent membership (owner-scoped)
- [ ] History endpoint (bounded, bucketed) + D3 price chart
- [ ] Error payload + request IDs; generated OpenAPI TS types (`make api-types`)
- [ ] Frontend: login, layout, monitor grid (AG Grid), detail route
- [ ] Gate: logins work; watchlist survives refresh/restart; cross-user change rejected; 403 on forbidden writes

### M2 — stream and grid behavior
- [ ] Lifespan-managed simulator (200 instruments, ~50 updates/s, seeded)
- [ ] Hub: epoch/seq, lock-protected snapshot+registration, 100ms coalescing, bounded queues
- [ ] `/ws/market` auth + Origin; heartbeat with server time and stale set
- [ ] Sampled quote persistence (≤1/s/instrument, batched) + retention command
- [ ] Frontend stream store (selectors), reducer (dup/gap/epoch), reconnect backoff + cleanup
- [ ] Live grid updates via transactions, cell flash, transport vs freshness states
- [ ] Events endpoint + Infinite Row Model grid
- [ ] Gate: live updates; reconnect recovers; dup/out-of-order/gap handled; epoch resync; event blocks sort/filter

### M3 — alert-to-resolution workflow
- [ ] Rules API with versions + one-enabled-rule-per-type index
- [ ] Clock-driven evaluator with warm-up; episodes; unique unresolved incident index
- [ ] Incident transitions, assignment, comments, optimistic concurrency, transactional audit
- [ ] Timeline endpoint; incident list/detail UI; rule editor UI
- [ ] Gate: stale & spread scenarios → one incident each; no duplicates; ack/comment/restore/resolve; invalid transitions fail; new breach after resolve → new incident

### M4 — operational UI and polish
- [ ] System status screen, scenario controls with descriptions/expiry, reset confirmation
- [ ] Health diagnostics (DB vs feed distinct), persistence error handling
- [ ] Accessibility (labels, focus, keyboard), mobile layouts, empty/error states, tooltips
- [ ] Gate: three-minute demo from seed; viewer read-only (server-enforced); no console errors

### M5 — verification and performance
- [ ] Backend test suite (list in BUILD_PLAN §10) on PostgreSQL
- [ ] Frontend unit tests (store/reducer/reconnect/forms/conflicts/incident controls)
- [ ] Playwright workflows 1–5
- [ ] Benchmark script + fixtures + docs/performance.md with actual results
- [ ] Gate: all checks pass; benchmark evidence recorded honestly

### M6 — release and handoff
- [ ] Production images, nginx proxy (WS upgrade), optional TLS overlay
- [ ] README, architecture, api, runbook, deployment, testing, demo script, CHANGELOG, release notes
- [ ] Smoke check script against compose stack
- [ ] Gate: clean setup from README; reproducible migrations/seed; smoke checks pass

## Gate evidence

(entries appended per milestone)

## Next step / continuation

Start M0.
