# MarketOps — Claude Code Build Plan

## 1. How to use this plan

Place this file in a new project directory as `BUILD_PLAN.md`. Start Claude Code in that directory and paste the kickoff prompt in section 16. This document specifies proposed behavior; none of the application, measurements, tests, or deployments described here have been completed yet.

Build in milestones. Complete and verify a working vertical slice before expanding it. Maintain `docs/progress.md` so another session can resume without reconstructing the conversation. Do not stop after producing scaffolding or a plan.

## 2. Objective and scope

Build MarketOps, an independent market-data monitoring and incident-management application inspired by the engineering requirements of ICE/NYSE Full Stack Software Engineer requisition 13416. It must show full-stack ownership, thoughtful UI design, financial-data literacy, streaming reliability, automated testing, operational documentation, and disciplined AI-assisted engineering.

Primary user: a market-operations analyst monitoring quote freshness and spreads, investigating an alert, acknowledging an incident, and documenting resolution.

Core demonstration: healthy synthetic feed → inject stale quotes for one instrument → automatic alert and incident → inspect instrument evidence → acknowledge and comment → restore feed → resolve → inspect audit history.

Every screen must label data as synthetic. Use fictional instruments or clearly labeled simulated prices. Do not imply affiliation with ICE/NYSE, connectivity to an exchange, real-time licensed market data, or suitability for actual trading.

Version 1 includes four screens, durable database-backed workflows, login and role enforcement, synthetic streaming, alert rules, and repeatable failure scenarios. It does not need brokerage integration, order execution, Kafka, Kubernetes, microservices, a paid data feed, or an LLM at runtime. An AI product feature is optional future work; the role's central AI requirement concerns how the software is developed.

## 3. Fixed architecture and development choices

| Area | Decision |
| --- | --- |
| Frontend | React, TypeScript in strict mode, Vite, React Router |
| Styling | Tailwind CSS; accessible reusable primitives; restrained financial-console design |
| REST state | TanStack Query; URL query parameters for persistent filter state |
| Streaming state | Small typed external store with selector subscriptions; bounded buffers |
| Data grid | AG Grid Community; client-side live instruments and Infinite Row Model for historical events |
| Charts | D3 scales, axes, and line/area calculations rendered within React-owned SVG |
| Backend | FastAPI, Pydantic, SQLAlchemy, Alembic |
| Storage | PostgreSQL; database migrations and deterministic seed command |
| Streaming | Authenticated WebSocket connection with epoch/sequence protocol |
| Tests | pytest, Vitest + React Testing Library, Playwright |
| Quality | Ruff, backend type checking, ESLint, frontend type checking |
| Packaging | Docker Compose for PostgreSQL, backend, and frontend/reverse proxy |
| Automation | GitHub Actions for quality checks, tests, builds, and image packaging |

At setup, consult official documentation for package compatibility and select current stable releases. Pin dependencies and commit lockfiles. Do not use AG Grid Enterprise-only features or trial keys. FastAPI satisfies the posting's allowance for another modern backend framework; do not add Spring Boot merely to include another keyword.

Production topology: one HTTPS origin serving the frontend and proxying `/api` and `/ws` to the backend. Vite proxies these paths during development. This keeps session authentication straightforward. WebSocket upgrades must be supported by the proxy.

Start with ONE backend worker/replica: the simulator, sequence allocator, snapshot, and connection registry are in-process. Clearly document this limitation. Do not deploy multiple workers until a shared feed/broadcast design exists. Business records remain in PostgreSQL. A restart creates a new stream epoch and requires clients to resynchronize.

Suggested directory structure:

```text
frontend/src/{app,components,features,lib,test}
backend/app/{api,auth,models,schemas,services,streaming}
backend/{alembic,tests}
infra/
scripts/
docs/
.github/workflows/
```

Provide `.env.example`, `Makefile`, `AGENTS.md`, `CLAUDE.md`, `README.md`, and `BUILD_PLAN.md`. `CLAUDE.md` should point to the shared engineering instructions in `AGENTS.md` and this plan without duplicating them.

## 4. User experience and screens

Use a compact left navigation, a top status bar, readable numbers, restrained colors, and a persistent synthetic-data badge. Use color plus text/icons for statuses. Support keyboard navigation, labeled fields, visible focus, loading/empty/error states, and approximately 1280px desktop and 390px mobile widths. Allow grid horizontal scrolling on small screens; make detail and incident views usable without it.

### Market monitor

- Grid: symbol, name, bid, ask, mid, spread in basis points, synthetic cumulative volume, last quote time, freshness, and active incident count.
- Sort/filter/search, selected watchlist, stable row IDs, explicit selection, and instrument links.
- Brief cell-change highlighting; never reorder a user's selected row on every tick.
- Show transport connection state separately from quote freshness.
- Persist watchlists and membership through REST and PostgreSQL. A browser refresh must not erase them.
- Header summarizes fresh/stale instruments, active incidents, and observed throughput.

### Instrument detail

- Bid/ask, mid, spread, freshness, and links to incidents.
- D3 price and spread charts with 5m/15m/1h ranges, tooltips, legends, and units.
- Historical events table with server-backed block loading, stable sorting, and filters.
- Rule editor with threshold units, validation, and enable/disable controls.
- Distinguish historical persistence from live data; charts must not suggest unsupported history resolution.

### Incident workspace

- List with status/severity/type/symbol filters and pagination.
- Detail: trigger reason, snapshot evidence, rule version, assigned user, comments, current condition, and chronological timeline.
- States: OPEN → ACKNOWLEDGED → RESOLVED. Resolution requires an acknowledgment, a recovery condition, and a nonempty resolution note. No arbitrary state jumps.
- An operator can acknowledge, assign, comment, and resolve. A viewer can read.
- A recovered market condition updates the incident but does not silently resolve it.
- Validation/conflict messages must explain what the user can do next.

### System status and scenario controls

- Connection health, simulator state, epoch, throughput, stale count, active scenarios, and persistence health.
- Operator-only scenarios: stale symbol, wide spread, normal recovery, and disconnect current user's stream.
- Visible scenario descriptions, confirmation only for resetting demo data, and automatic scenario expiry.
- Stop emitting one symbol for staleness; keep heartbeats and other symbols active.
- Scenarios affect this demo workspace and must never contact external market services.

## 5. Data model and invariants

Use UUID primary keys where appropriate, UTC timestamp-with-time-zone fields, explicit foreign keys, and migrations. Avoid cascading away audit history. Database prices use NUMERIC/Decimal; API prices are decimal strings. Calculations on the server use Decimal. Convert to JavaScript numbers only for chart rendering.

| Table | Key fields and rules |
| --- | --- |
| users | email, password hash, role VIEWER/OPERATOR, active flag |
| sessions | hashed opaque token, user, expiry, CSRF token reference; no plaintext token storage |
| instruments | unique symbol, name, asset label, active flag |
| quote_samples | instrument, bid, ask, volume, source time, received time; indexed instrument/time/id |
| market_events | instrument, event type, observed time, JSON evidence; indexed time/id and instrument/time |
| watchlists | owner user, name, timestamps |
| watchlist_items | unique watchlist/instrument pair |
| alert_rules | instrument, type STALE/WIDE_SPREAD, threshold, unit, enabled, version, creator |
| alert_episodes | rule, breach/recovery times, trigger evidence, linked incident |
| incidents | rule, episode, status, severity, assignee, condition_active, resolution note, version |
| incident_comments | incident, author, body, created time |
| audit_events | actor or system, action, entity, before/after metadata, correlation ID, created time |

For V1, use one seeded demo workspace. Watchlists belong to users; rules and incidents are shared. Do not claim multi-tenancy.

Invariants:

- Positive prices; ask >= bid for normal quotes; mid = (bid + ask) / 2.
- Spread basis points = ((ask - bid) / mid) × 10,000. Define rounding centrally.
- Staleness uses elapsed time since last backend receipt, not the browser clock. Record source timestamps separately. A heartbeat does not freshen an instrument.
- Allow one enabled rule per instrument/type in V1. Enforce it in the database.
- At most one unresolved incident per rule. Enforce with a PostgreSQL partial unique index, not a frontend check.
- Repeated breaches during an unresolved incident update condition/evidence without creating duplicate incidents. After resolution, a later breach may open a new incident.
- Incident mutation, corresponding audit entry, and episode update commit atomically.
- Use optimistic version checks for incident/rule edits; stale versions return 409 without overwriting newer changes.
- Never accept actor identity, role, calculated spread, or incident status directly from an untrusted client.

## 6. REST interface

Prefix endpoints with `/api/v1`. Define typed request/response schemas, bounded pagination, validated sort/filter fields, and consistent error payloads containing code, message, details where safe, and request_id.

| Endpoints | Behavior |
| --- | --- |
| POST /auth/login; POST /auth/logout; GET /auth/me | Session lifecycle and authenticated profile/CSRF bootstrap |
| GET /instruments; GET /instruments/{id} | Searchable catalog and instrument metadata |
| GET /market/snapshot | Authoritative current quote snapshot with epoch and sequence watermark |
| GET /instruments/{id}/history | Bounded sampled history by time range; max range/point count |
| GET /events | Block pagination, allowlisted sorting/filtering, total count, stable tie-breaker |
| GET/POST /watchlists; PATCH/DELETE /watchlists/{id} | Owner-scoped CRUD |
| POST/DELETE /watchlists/{id}/items/{instrument_id} | Idempotent membership operations |
| GET/POST /rules; PATCH /rules/{id} | Viewer read; operator mutations with version checks |
| GET /incidents; GET /incidents/{id} | Filtered list and detail |
| POST /incidents/{id}/acknowledge | Atomic transition and audit |
| PATCH /incidents/{id}/assignment | Valid operator assignment with version check |
| POST /incidents/{id}/comments | Validated comment; audit where appropriate |
| POST /incidents/{id}/resolve | Enforce transition/recovery/note rules |
| GET /incidents/{id}/timeline | Comments, lifecycle, and audited actions in stable order |
| GET /system/status | Safe operational metadata |
| POST /demo/scenarios; DELETE /demo/scenarios/{id} | Operator-only bounded scenario start/stop |
| GET /health/live; GET /health/ready | Process liveness; database/migrations/simulator readiness |

Return actual persisted data. Do not substitute hardcoded arrays after scaffolding. OpenAPI is the contract; generate TypeScript API types with a reproducible command and detect contract drift in CI.

## 7. Simulator, streaming, and recovery protocol

Default workload: 200 synthetic instruments, approximately 50 updates/second total, deterministic configurable random seed. Benchmarks may use a larger fixture. Generate plausible random-walk prices, nonnegative volume increments, and normal spreads. Explicit scenario controls alter these conditions predictably.

One lifespan-managed producer updates the in-memory quote state. It must not start once per HTTP request or WebSocket. Track background tasks, propagate/report exceptions, and cancel/drain safely at shutdown.

Persist sampled quotes at no more than one sample per instrument per second with batched inserts. Persist alert/incident events durably. Define a rolling retention window and an explicit maintenance command; do not allow storage to grow without bound. Synthetic historical events can be seeded separately for grid performance tests.

Protocol:

1. Authenticate the WebSocket at `/ws/market`. Validate its Origin before accepting.
2. Under the same stream-state lock, register the connection's bounded queue and capture a snapshot with `stream_epoch` and `seq`. Send snapshot first, then queued messages newer than that watermark. Avoid the REST-snapshot/subscription race.
3. Each delta batch carries epoch, globally consecutive seq, timestamp, and quote updates. Every client receives the same ordered batches; clients filter locally. Heartbeats do not advance the delta sequence.
4. Client ignores duplicate/older batches. A gap or epoch change marks displayed data as resynchronizing and obtains a fresh snapshot through reconnection. Do not quietly continue applying an incomplete stream.
5. Exponential reconnect backoff with jitter and a reasonable ceiling; cancel old sockets/timers on unmount, logout, and successful reconnect.
6. Coalesce updates into batches around 100ms. Slow connections have a bounded queue; overflow triggers resynchronization/disconnection instead of unbounded buffering or silent message loss.
7. Keep transport health separate from business freshness. An intentionally paused quote is stale even when the socket is connected.

Keep chart buffers bounded, for example 600 points per displayed series. Avoid rerendering all pages on each tick. Maintain stable grid row IDs. Server rule evaluation runs independently of connected browsers on a clock-driven loop, including freshness checks when no new quote arrives.

On restart, derive unresolved incident state from PostgreSQL, create a new epoch, and use a documented warm-up grace period before evaluating staleness. Preserve unresolved incidents; do not treat missing in-memory state as proof of recovery. Evaluate recovered quotes to update their conditions.

## 8. Authentication and security implementation

Use server-side opaque sessions with secure password hashing through a maintained library. Set HttpOnly, SameSite cookies; Secure in HTTPS environments. Document explicitly permitted local HTTP configuration. Enforce idle/absolute expiry and revoke sessions on logout.

Protect cookie-authenticated writes using a CSRF token and Origin checks. Verify permissions and ownership on the backend for every mutation. Reject an invalid session or Origin during WebSocket handshake. Never put credentials in WebSocket URLs or localStorage.

Seed viewer/operator users only through explicit local/demo setup. Read passwords from environment or generate them locally; never commit production credentials. Include login throttling and safe authentication errors. Avoid logging cookies, passwords, tokens, or full environment values.

For any future public demo, default to read-only access. Operator credentials and global scenario/reset controls stay private. A full public operator sandbox requires additional isolation and is outside V1. Local/private authenticated demonstration is sufficient for the first release.

## 9. Milestones and acceptance gates

### M0 — foundation and prototype

Inspect the repository and preserve existing work. Create a task checklist, ADRs for stack/single-worker/auth choices, low-fidelity layouts, and shared agent instructions. Bootstrap dependency lockfiles, Docker Compose, database migrations, seed command, quality tooling, and CI skeleton.

Gate: clean clone starts documented services; readiness succeeds; frontend build and backend import succeed; no committed secrets. Prototype documents navigation and primary workflow.

### M1 — first durable vertical slice

Implement login/profile/logout, roles, catalog, watchlist CRUD, grid, detail route, sampled history endpoint, and one working chart. Establish generated API types and shared error handling.

Gate: operator/viewer login works; watchlist survives refresh/restart; one user cannot change another's watchlist; instrument selection loads actual API data; forbidden writes return 403.

### M2 — stream and grid behavior

Implement simulator, snapshot/delta protocol, WebSocket authentication, batched rendering, transport states, reconnection, bounded queues/buffers, and historical Infinite Row Model.

Gate: quotes update without refresh; disconnect/reconnect recovers; duplicate/out-of-order/gapped batches are handled; epoch change resynchronizes; historical block sorting/filtering works against PostgreSQL.

### M3 — alert-to-resolution workflow

Implement stale/spread rules, scheduled evaluator, alert episodes, unique unresolved incidents, status transitions, optimistic concurrency, comments, assignment, and transactional audit history.

Gate: stale and spread scenarios each create one incident; repeated evaluation does not duplicate it; acknowledgment/comment/restore/resolution works; invalid transitions fail; a later breach after resolution creates a new incident.

### M4 — operational UI and polish

Add status screen, scenario expiry/recovery, health diagnostics, keyboard/accessibility improvements, mobile layouts, chart tooltips, understandable empty/error states, and persistence error handling.

Gate: the complete three-minute demo works from seeded state; feed and database failures are visibly distinct; viewer controls are read-only and server-enforced; no broken navigation or console errors.

### M5 — verification and performance

Complete the meaningful test suite below. Run a documented workload benchmark and inspect resource use. Fix failures before adding optional features. Capture actual commands/results and limitations.

Gate: all required checks pass; benchmarks record workload, hardware, duration, and percentile definitions; no invented metrics; retained evidence matches final code.

### M6 — release and handoff

Build images, exercise production-style proxy/TLS configuration where possible, write release notes and rollback/runbooks, and prepare deployment configuration. Deploy only if deployment is separately authorized and credentials are available. Otherwise deliver a locally verified release and exact deployment steps without claiming a live URL.

Gate: README setup succeeds; migrations/seed are reproducible; smoke checks pass; limitations are disclosed; demo script and development evidence are complete.

## 10. Tests that matter

Backend tests run against PostgreSQL, including migrations/partial indexes, rather than substituting SQLite for database-sensitive behavior.

- Decimal spread calculation and threshold boundary conditions.
- Stale detection with an injected clock, including no incoming messages and warm-up.
- Two concurrent evaluators cannot create duplicate unresolved incidents.
- Incident transition rules, recovery requirement, resolution note, and subsequent new breach.
- Conflicting versions return 409; failed changes leave no partial audit entry.
- Session expiry/logout, CSRF rejection, role enforcement, watchlist ownership, unauthorized socket handshake.
- API pagination/filter/sort and stable tie-breakers; bounds on history queries.
- WebSocket snapshot/subscription race, duplicate/gap/epoch behavior, queue overflow, shutdown cleanup.

Frontend tests cover stream reducer/store transitions, reconnection cleanup, stale/connected distinction, form validation, conflict messages, and incident controls. Prefer behavior assertions to implementation snapshots.

Playwright workflows:

1. Login → add watchlist instrument → reload → membership persists.
2. Operator starts stale scenario → incident appears → detail/chart loads → acknowledge/comment → recover → resolve → audit timeline reflects actions.
3. Viewer cannot mutate through UI or direct HTTP request.
4. Disconnect → resynchronization → live values resume without duplicated listeners.
5. Invalid threshold and stale-version edit show actionable messages.

Use deterministic isolated fixtures, fresh test database state, and event/condition-based waits. Do not rely on arbitrary sleeps or assert exact synthetic prices from an unseeded random feed. Separate the benchmark workload from ordinary CI tests.

## 11. Performance targets and measurement

These are targets, not accomplishments. Report misses honestly.

| Test | Proposed target |
| --- | --- |
| Default stream | 200 instruments, 50 updates/second, sustained 10-minute run |
| UI batching | Approximately 100ms update batches; no per-tick full-app rendering |
| Larger grid fixture | 1,000 instruments renders and scrolls usefully on documented machine |
| History fixture | 100,000 seeded events; indexed block queries and bounded payloads |
| REST latency | Aim for p95 <300ms for ordinary local reads under stated load |
| Recovery | Latest snapshot restored within 5 seconds after network availability returns in a controlled local test |
| Resource bounds | Bounded socket queues and chart buffers; stable memory after warm-up under default workload |

Provide a benchmark script, fixture generation command, endpoint timing definitions, and `docs/performance.md`. Record browser/machine, sample count, duration, actual results, and limitations. Quote persistence is sampled; do not describe it as a lossless tick archive. Use index/query analysis to investigate slow reads.

## 12. AI-assisted engineering evidence and guardrails

Create `docs/ai-development-log.md` with entries containing: task, tool/model if verifiable, rationale for model size, agent scope, code changed, review findings, verification commands, outcome, and cost/latency only when observable. If model/cost is unavailable, say unknown. Never fabricate a second tool session or a human review.

Document at least four real tasks: planning a workflow, implementing a vertical feature, reproducing/fixing a bug, and refactoring shared components. Record a rejected/corrected AI proposal only if one actually occurs. Preserve short useful artifacts rather than dumping full transcripts containing private information.

Model choice policy: small/fast models for tightly specified edits, documentation, and routine scaffolding; stronger models for architectural ambiguity, concurrency, or difficult security/debugging work. Record outcomes instead of unsupported provider rankings. If only one model/tool is available, finish the work and disclose that limitation.

`AGENTS.md` must require:

- Read the plan and progress file; respect existing code and repository instructions.
- Keep changes scoped and preserve unrelated work.
- Enforce backend authorization and validation; keep secrets out of source/logs.
- Explain schema/migration changes and test database invariants.
- Run relevant checks, then the milestone gate; record failures accurately.
- Validate generated API types and database contracts.
- Do not disable tests/type checks or hide exceptions to obtain a green result.
- Do not claim performance, production readiness, tool use, or human review without evidence.
- Keep `docs/progress.md` current with next steps and blockers.

Claude may review its own changes, but that is agent review, not human review. Add a human-review checklist for authentication, incident concurrency, migrations, deployment configuration, and measured claims. If the user later wants Codex comparison, create an independent review task; do not present hypothetical use as completed experience.

## 13. Release and support documentation

Deliver:

- `README.md`: purpose, synthetic-data notice, screenshots, stack, prerequisites, exact setup/test/seed commands, demo flow, limitations.
- `docs/architecture.md`: component relationships, sequence/snapshot logic, persistence boundaries, single-worker constraint, restart behavior.
- `docs/adr/`: short architecture decisions and tradeoffs.
- `docs/api.md`: generated-contract instructions and error/versioning conventions.
- `docs/runbook.md`: stale feed, unavailable database, dropped sockets, unhealthy deployment, restart, and rollback procedures.
- `docs/deployment.md`: environment configuration, proxy/WebSocket requirements, migrations, readiness, smoke checks, costs to verify before provisioning.
- `docs/testing.md` and `docs/performance.md`: commands, fixtures, actual results, known gaps.
- `docs/ai-development-log.md`, `docs/progress.md`, `docs/demo-script.md`, and `CHANGELOG.md`.

Rollback instructions must distinguish rolling back an application image from reversing a migration. Prefer backward-compatible migrations; do not automatically run destructive downgrades. A support runbook demonstrates preparedness, not actual on-call employment.

Required smoke checks: login, catalog, WebSocket upgrade, quote update, watchlist persistence, readiness, and one incident transition. Images must have explicit versions; documentation must match the final release.

## 14. JD evidence checklist

| Posting expectation | Required project evidence |
| --- | --- |
| Full-stack feature ownership | Complete market-monitor → incident → resolution workflow |
| React/TypeScript and core web | Typed components, state design, accessible HTML/forms, CSS layouts |
| REST and relational database | OpenAPI, migrations, PostgreSQL persistence, transactional audit |
| AG Grid/data virtualization | Live grid plus server-loaded historical blocks using Community features |
| D3 | Interactive chart code and meaningful units/time ranges |
| WebSockets | Ordered snapshot/delta protocol and tested recovery |
| Automated tests and review | Backend/component/E2E tests, CI, review checklist |
| AI tools and agents | Actual scoped tasks and documented validation |
| Model judgment/cost | Verifiable task-based choices and observed data where available |
| Shared component/testing frameworks | Reusable UI primitives and deterministic test fixtures |
| Wireframes/prototypes | Early layouts and decisions connected to final workflow |
| Cloud/containers/CI | Working containers, CI, deployment configuration; actual hosting only if performed |
| Documentation/releases/support | Release notes, smoke checks, rollback and incident runbook |
| Finance exposure | Quote freshness, bid/ask spread, basis points, feed operations |

The project cannot replace the degree/professional-experience requirement, prove teamwork or real after-hours support by itself, or establish mastery of every listed provider/tool. Portfolio claims must remain proportionate to completed evidence.

## 15. Definition of done and effort budgeting

V1 is done when a clean setup runs, core records survive restart, the full demo passes, permissions and streaming recovery are tested, all required checks are green, documentation is accurate, and there are no placeholders in the primary workflow.

Use the first 25–40 focused hours as a planning budget for a credible core release, not a guarantee of polished completion. Reserve additional time for security review, concurrency bugs, CI, and hosting. If time runs short, reduce decorative charts, extra scenarios, and optional dashboards before removing persistence, authorization, or recovery tests.

Only after V1: consider a read-only AI incident-summary feature with explicit evidence citations and validated structured output; additional asset types; real delayed market data after checking licensing; shared-worker streaming architecture; or a narrowly scoped Spring Boot comparison. Do not start these while the main workflow is unfinished.

## 16. Kickoff prompt for Claude Code

Copy this into Claude Code after adding this document to the project:

```text
Build MarketOps using BUILD_PLAN.md as the implementation specification.

Read the complete plan, repository instructions, and existing code before editing.
This is an implementation task: continue through M0–M6, not just scaffolding or
planning. Use the plan's fixed stack and working vertical slices. You may resolve
routine engineering choices yourself, documenting significant decisions.

First establish docs/progress.md, an actionable milestone checklist, AGENTS.md,
and CLAUDE.md. Then implement and verify each milestone in order. At each gate,
record files changed, exact checks run, results, limitations, and the next step.
Consult official documentation when package APIs or compatibility are uncertain.

Prioritize real PostgreSQL persistence, authenticated role enforcement, reliable
WebSocket recovery, AG Grid Community, D3, the incident workflow, and meaningful
tests. Do not build a static mockup in place of backend functionality. Do not add
microservices, paid feeds, enterprise grid features, or a runtime LLM to V1.

Use AI agents for scoped real engineering work and keep an honest development
log. Record verifiable model/tool choices, corrections, and validation; never
invent human reviews, measurements, credentials, or deployments.

Keep progressing through reversible local implementation and verification.
Do not repeatedly ask approval for ordinary choices. If an unavailable credential,
external publication, paid provisioning, or destructive action blocks a step,
complete independent work and report that specific blocker. Do not publish,
provision paid services, or overwrite unrelated work without authorization.

Before finishing, run the documented quality/test/build gates, verify the main
demo, and produce a concise handoff with setup commands, actual test outcomes,
known limitations, and deployment readiness. Do not claim tests you did not run.
If context gets short, update docs/progress.md with precise continuation steps.
```

## 17. Resume and interview handoff

After implementation, write one project description and two or three resume bullets based only on actual completed work. Use measured numbers only when the benchmark evidence supports them. Prepare explanations of the snapshot race, partial unique index, stale-feed clock, session security, model choice, and one AI-generated mistake you caught if applicable. Being able to explain these decisions matters more than the number of tools in the README.
