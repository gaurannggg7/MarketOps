# Testing

> **Update 2026-10-15:** latest local counts are 62 pytest, 84 Vitest, and 6 Playwright
> workflows, run in both the same-origin and the split-origin (stream-ticket) topology. New
> backend tests cover public-demo read-only sessions, demo-entry rate limiting, the autopilot's
> full incident lifecycle, stream tickets (single use, expiry, logout revocation, Origin,
> connection caps), Neon-style URLs, in-process bootstrap on an empty database, and the
> late-seeded-catalog self-heal. GitHub Actions passed for `40a52aa`
> ([run 38485052338](https://github.com/gaurannggg7/MarketOps/actions/runs/38485052338));
> newer commits have not run in CI yet. The tables below describe the 2026-10-13 baseline.

All results below were produced on 2026-10-13 on the machine in `docs/performance.md`
(Apple M3, 8 cores, 16 GB, macOS 15.2), against PostgreSQL 17.11 in Docker. CI is defined in
`.github/workflows/ci.yml` but has **not run on GitHub** (nothing has been pushed).

## Commands and latest results
| Gate | Command | Result |
| --- | --- | --- |
| Lint | `make lint` (ruff check + format check, ESLint strictTypeChecked, max-warnings 0) | pass |
| Types | `make typecheck` (mypy --strict on `app` and `tests`, `tsc -b`) | pass (45 Python files) |
| Backend tests | `make test-backend` | **49 passed**, 1 warning (Starlette's TestClient deprecation notice about httpx) |
| Frontend tests | `make test-frontend` | **80 passed** in 6 files |
| Build | `make build` | Vite build ok; backend import ok |
| E2E | `make e2e` | **5 passed** (≈30 s); also run 3× consecutively without failure before the console gate was added, and passing after it |
| Contract | `make api-check` | no drift |
| Secrets | `make secrets-scan` | no findings (150 tracked files) |
| Clean clone | `git clone` → `make env install` → migrate/seed on a fresh DB → readiness → `make check` → `make api-check` | all passed |
| Smoke (nginx :8080) | `make smoke` | 7/7 |
| Smoke (HTTPS :8443 overlay) | `MARKETOPS_URL=https://localhost:8443 MARKETOPS_SMOKE_INSECURE=1 … smoke.py` | 7/7 (self-signed cert; `Secure` cookie flag confirmed) |

## Backend (pytest, real PostgreSQL)
`tests/conftest.py` drops and recreates `marketops_test`, runs Alembic to head (so partial indexes
and check constraints are exercised), and truncates + seeds 5 instruments per test. The app runs
with the simulator loops disabled and an injected `FakeClock`; tests drive quotes and the
evaluator deterministically. WebSocket end-to-end tests use Starlette's TestClient with the real
lifespan (simulator enabled).

| Area | Tests |
| --- | --- |
| Decimal math | mid/spread rounding incl. a half-even case, invalid quotes, strict threshold boundaries (`test_market_math.py`) |
| Staleness | warm-up suppression + staleness with no incoming quotes; heartbeats never freshen; repeated evaluation keeps one incident; recovery updates but never resolves (`test_evaluator.py`) |
| Concurrency | 6 concurrent `record_breach` calls → exactly 1 incident and 1 episode |
| Restart | new epoch; unresolved incident stays active through warm-up; recovers only on fresh quotes |
| Incident workflow | resolve before ack → 409; ack; duplicate ack → 409; assignment; comments; resolve blocked while active; blank note → 422; resolve; timeline order; new breach after resolution → new incident (`test_incidents.py`) |
| Concurrency control | stale `version` → 409 with `current_version`, no audit row written; rule version conflict |
| Auth/security | login/profile/logout; replayed revoked token → 401; token stored only as hash; generic errors + throttling (429); idle and absolute expiry; CSRF missing/forged → 403; foreign Origin → 403; login requires Origin; viewer gets 403 on all 7 write routes; unauthenticated reads → 401; logout revokes only that session; session probe |
| Ownership | other users' watchlists → 404 for rename/delete/add/remove/filter |
| API | catalog search/detail, snapshot decimal strings, history bucketing & bounds (2 h of samples), events pagination/sort/filter with forced timestamp ties and stable tie-breakers, invalid params → 422 |
| Streaming | snapshot/subscription race (50 registrations during continuous publishing), heartbeat doesn't advance seq, queue overflow → resync control (no unbounded buffering), epoch reset, WS handshake rejection (4401/4403), ordered deltas over a real socket, scenario disconnect (4001), logout closes stream, shutdown cancels tasks and connections |
| Schema | partial unique index definitions, negative price rejected by DB check, readiness checks, request-ID/error shape |

## Frontend (Vitest + React Testing Library)
Written by a delegated subagent and reviewed/re-run by the main agent (see
`ai-development-log.md`). Reducer (snapshot, dup, gap, epoch, heartbeat gap, server resync,
server-clock age), `MarketStream` (single socket, detach on resync, backoff bounds with jitter,
attempt reset, stop cleanup, logout close, ignoring replaced sockets), transport vs freshness
display, threshold validation, `RuleEditor` (bounds message, 409 conflict + reload, viewer
read-only), `IncidentActions` (viewer read-only, transition blockers, note validation, 409).

## Playwright workflows (`frontend/e2e`)
Isolated backend on :8001 with a freshly created `marketops_e2e` DB and test-only passwords
(`playwright.config.ts`), Vite on :5174, one worker, condition-based waits (no fixed sleeps).
Every test fails if the browser logs a console error or page error, except HTTP statuses a test
explicitly expects.
1. Create watchlist → star an instrument → reload → membership persists.
2. Stale scenario → incident appears → detail + chart load → acknowledge + comment → recovery →
   resolve → timeline shows opened/acknowledged/comment/recovered/resolved.
3. Viewer: no mutation controls; direct HTTP POST/PATCH with valid CSRF → 403 `FORBIDDEN`.
4. Disconnect scenario → snapshot count 2 → live again → sequence advances → exactly one new
   socket (no duplicate listeners).
5. Invalid threshold messages; a concurrent edit makes the UI save fail with the conflict notice;
   "Reload latest rule" shows the newer value.

## Known gaps
- CI has never executed on GitHub; first push may surface environment differences.
- No load test of many concurrent browsers; the benchmark uses 5 protocol-level clients.
- Visual regression, cross-browser (Firefox/WebKit), and screen-reader testing were not done.
- Vite's dev proxy prints `write EPIPE` when sockets close during E2E; it is server-side log
  noise from the dev proxy, not a browser error (the production nginx proxy does not use it).
