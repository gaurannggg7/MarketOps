# AGENTS.md — shared engineering instructions

These rules apply to every AI agent (Claude Code, Codex, or others) and every human contributor
working in this repository. `BUILD_PLAN.md` is the product/architecture specification;
`docs/progress.md` is the live status and continuation log.

## Before you change anything

1. Read `BUILD_PLAN.md` and `docs/progress.md`. Respect existing code, ADRs in `docs/adr/`, and
   repository instructions.
2. Keep changes scoped to the task. Preserve unrelated work; never overwrite or delete files you
   did not create for the task without the owner's authorization.
3. Do not push, publish, deploy, or provision paid services without explicit owner permission.

## Engineering rules

- **Authorization and validation live on the backend.** Every mutation checks the session, role,
  CSRF token/Origin, and ownership server-side. Never accept actor identity, role, calculated
  spread, or incident status from the client.
- **Secrets stay out of source and logs.** No committed credentials; demo passwords come from
  `.env` (gitignored) or are generated locally. Never log cookies, passwords, tokens, or whole
  environment values.
- **Schema changes go through Alembic.** Explain every migration in the PR/progress entry, prefer
  backward-compatible migrations, and add tests for database invariants (partial unique indexes,
  foreign keys, optimistic versions). Backend tests run against PostgreSQL, not SQLite.
- **Money math uses `Decimal`.** Prices are NUMERIC in the database and decimal strings in the API.
  Spread/mid rounding is defined only in `backend/app/services/market_math.py`.
- **API contract.** OpenAPI is the contract. After changing schemas or routes run
  `make api-types` and commit the regenerated `frontend/src/lib/api/schema.d.ts`; CI fails on drift.
- **Streaming.** Keep the snapshot/sequence protocol in `docs/architecture.md` intact. One backend
  worker only (ADR 0002) until a shared broadcast design exists.

## Verification

- Run the relevant checks for what you touched, then the milestone gate (`make check` runs lint,
  type checks, backend tests, frontend tests, and builds; `make e2e` runs Playwright).
- Record failures accurately in `docs/progress.md`. Do not disable tests or type checks, add broad
  `except`/`# type: ignore`/`eslint-disable`, or hide exceptions to obtain a green result.
- Do not claim performance numbers, production readiness, tool/model use, or human review without
  evidence. Agent self-review is "agent review", never "human review".

## Records

- Keep `docs/progress.md` current: what changed, exact commands, results, limitations, next step,
  blockers.
- Log AI-assisted tasks in `docs/ai-development-log.md` with verifiable details only; write
  "unknown" when a model, cost, or latency is not observable.
