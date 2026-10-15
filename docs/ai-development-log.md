# AI-assisted development log

This project was built in one Claude Code session (desktop app, Code tab) on 2026-10-13. Entries
record only what is verifiable from that session. Where a model, cost, or latency was not
observable, it says so. No human review has happened yet (see `review-checklist.md`), and no
second tool (e.g. Codex) was used.

**Tools/models observed**
- Main agent: Claude Code running model `claude-opus-5-5` (Opus 5.5), as reported by the session
  environment. Token/cost totals for the main session were not visible to the agent: **unknown**.
- One subagent: launched through Claude Code's Agent tool with the model alias `sonnet`. The
  harness reported 103,443 subagent tokens, 15 tool uses, and 152.9 s wall time. The exact model
  version behind the alias was not independently verified (the environment lists Sonnet 5.5 as
  the current Sonnet). Cost in dollars: **unknown**.

**Model-choice policy applied:** the stronger main model handled planning, architecture,
concurrency (stream protocol, incident races), security (sessions/CSRF), and debugging. The
smaller/faster model got one tightly specified task (frontend unit tests) with explicit file
ownership, acceptance commands, and a rule not to edit application code.

---

## 1. Planning the workflow (main agent)
- **Task**: turn BUILD_PLAN.md into an executable plan: milestone checklist (`docs/progress.md`),
  shared rules (`AGENTS.md`, `CLAUDE.md`), and version selection.
- **Rationale for model**: architectural ambiguity and compatibility research.
- **What happened**: queried npm/PyPI for current versions. Found that TypeScript 7.0 is outside
  the peer range of typescript-eslint 8.71 (`<6.1.0`) and openapi-typescript 7.13 (`^5.x`), so
  pinned TS 5.9.3 (ADR 0001). Found port 5432 taken by an existing Homebrew PostgreSQL with
  unknown credentials, so used Docker PostgreSQL on 55432 instead of touching it.
- **Verification**: `npm view … peerDependencies`; `pg_isready`; later all builds/tests on the
  pinned versions.

## 2. Vertical feature: alert → incident → resolution (main agent)
- **Code**: `backend/app/streaming/evaluator.py`, `services/incidents.py`, `api/incidents.py`,
  migration `0001` partial indexes/check constraints, `frontend/src/features/incidents/*`.
- **Verification**: `pytest tests/test_evaluator.py tests/test_incidents.py` (warm-up, no-message
  staleness, 6 concurrent `record_breach` calls → exactly one incident and one episode, restart
  rebuild, transitions, 409 without partial audit, new incident after resolution); then the full
  flow driven by hand in the in-app browser (stale scenario → incident #1001 → ack → comment →
  stop scenario → recovered → resolve → timeline), later automated as Playwright workflow 2.

## 3. Reproducing and fixing bugs (main agent; found by tests or browser checks)
| Bug | How found | Fix |
| --- | --- | --- |
| `MissingGreenlet` when a rule PATCH hit the one-enabled-rule index | pytest `test_one_enabled_rule_per_instrument_and_type` | capture `rule_type` before flush; ORM attributes expire on rollback |
| Incident reason showed `threshold 1E+1s` | manual browser demo of incident #1001 | format with `fmt()`; added assertion in `test_evaluator.py` |
| Freshness cell said "No quote" for live rows | Playwright page snapshot during workflow 1 | column now has its own `valueGetter` so AG Grid refreshes it |
| Rule editor remounted on refetch, discarding an operator's in-progress edit and hiding the conflict | reasoning while writing Playwright workflow 5 | keep edits across refetches; save with the base version → 409 shown |
| Star (☆) always targeted the first watchlist in "All instruments" view | Playwright workflow 1 failure | explicit "☆ adds to" selector persisted in the URL |
| App hung on "Checking session…" when the session probe failed | in-app browser after a stale dev server returned 404 | explicit "Cannot reach MarketOps" error with Retry |
| Monitor grid blank at 390 px width | mobile check in in-app browser | definite grid height on small screens |
| Cold load logged 401s in the console | console check | added `GET /auth/session` (200 when signed out) for bootstrap |

## 4. Refactoring shared components (main agent)
- Extracted AG Grid module registration and theme from the monitor page into
  `frontend/src/components/grid.ts` after the events grid imported them from a lazily loaded page
  module. Shared UI primitives (`components/ui.tsx`: Button, Pill, Field with aria wiring, Panel,
  notices) and `TimeSeriesChart` are used by every screen.
- **Verification**: `tsc -b`, ESLint strict, Vite build, Vitest, Playwright.

## 5. Delegated task: frontend unit-test suite (subagent, `sonnet`)
- **Scope given**: only `src/**/*.test.ts(x)` and `src/test/`; do not edit app code; report
  suspected bugs instead. Required passing `vitest`, `tsc`, and strict ESLint.
- **Output**: 6 test files plus helpers (`fakeSocket.ts`, `fixtures.ts`, `streamHarness.ts`,
  `network.ts`), 80 tests: reducer, `MarketStream` reconnect/cleanup, transport vs freshness,
  threshold validation, `RuleEditor`, `IncidentActions`.
- **Review by main agent**: re-ran `npx vitest run` myself (80/80), read the store tests, and
  checked lint/types. The agent noticed openapi-fetch captures `fetch` at import time and
  installed a delegating stub instead of `vi.stubGlobal`. It reported 3 lint errors in my E2E
  files (outside its scope); I fixed them.
- **Correction caught by the agent's tests**: my later RuleEditor change sent unchanged fields in
  the PATCH body; the agent's test failed on the request body, and I restored the minimal body.

## Rejected/corrected AI proposals
- My first `test_market_math` expectation (9.99 bps) was wrong; the exact value 9.99500… rounds
  to 10.00. Replaced with a true half-even case (1.245 → 1.24). Found by the test run.
- Initial CSRF design rotated the token on every `/auth/me`, which would break multiple tabs;
  replaced before commit with a session-bound derived token (ADR 0003).

---

## 6. Deployment hardening and $0 hosting (2026-10-15, main agent, Opus 5.5)
- **Task**: prepare a public portfolio deployment; requirements changed mid-task from a paid
  single-host plan to $0 hosting (Vercel + Render Free + Neon Free).
- **Research**: read official Render/Vercel/Neon/DigitalOcean docs and pricing pages. Vercel's
  rewrite docs do not cover WebSocket upgrades, so the design does not depend on them (ADR 0006).
- **Bugs found by rehearsing, not by reading code**:
  | Bug | How found | Fix |
  | --- | --- | --- |
  | Fresh database: backend started before the seed → simulator had 0 instruments forever | production Compose rehearsal smoke: `seq 0`, no deltas | seed before serving + runtime self-heal; regression test |
  | Cold start 101 s / wake 102 s at 0.1 CPU (three Python processes importing the stack) | timing under `docker run --cpus 0.1` | in-process bootstrap: 51 s / 34 s; test on an empty DB |
  | Login page redirect raced the demo navigation | Playwright workflow 6 | land demo visitors on the monitor |
  | Screenshot captured a loading frame | inspected the PNG (8.8 kB) | wait for the page heading |
- **Not a bug, documented instead**: Starlette TestClient raises `CancelledError` if a test leaves
  a socket context while the server is still streaming; reproduced outside pytest, fixed in tests
  by closing the client socket.
- **Verification**: `make check` (62 pytest, 84 Vitest), Playwright 6/6 in two topologies (ticket
  usage asserted), smoke 7/7 (Compose + Caddy TLS), 8/8 (free-tier rehearsal), restart/recovery
  measurement. Cost/latency of the agent session: unknown.
