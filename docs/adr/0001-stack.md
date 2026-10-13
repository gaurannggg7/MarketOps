# ADR 0001 — Fixed stack

Status: accepted (2026-10-13)

## Context
BUILD_PLAN.md §3 fixes the stack. Versions were chosen at setup from the npm/PyPI registries on
2026-10-13 and pinned (backend: `requirements*.lock` with hashes via pip-tools; frontend:
`package-lock.json`, exact versions).

## Decision
- Backend: Python 3.13, FastAPI 0.143, Starlette 1.8, Pydantic 2.14, SQLAlchemy 2.1 (async) with
  psycopg 3.3, Alembic 1.20, argon2-cffi, uvicorn. PostgreSQL 17.11 (Docker image).
- Frontend: React 19.3, React Router 8.4, Vite 8.3, Tailwind 4.3, TanStack Query 5.104,
  AG Grid Community 36.2, D3 modules (scale/shape/array/time-format), openapi-fetch +
  openapi-typescript.
- Tests/quality: pytest 9 + pytest-asyncio, Vitest 5 + RTL, Playwright 1.64, Ruff, mypy (strict),
  ESLint 10 + typescript-eslint (strictTypeChecked).

## Consequences / compatibility notes found during setup
- **TypeScript is pinned to 5.9.3, not the latest 7.0.** typescript-eslint 8.71 declares
  `typescript >=4.8.4 <6.1.0` and openapi-typescript 7.13 declares `typescript ^5.x`.
- Starlette 1.x requires lifespan handlers (no `on_startup`); the app uses a lifespan context.
- SQLAlchemy 2.1 deprecates `Row.tuple()`; rows are unpacked directly.
- AG Grid: only `AllCommunityModule` is registered — no Enterprise modules or license keys.
  The grid chunk is ~1.1 MB minified (~320 kB gzip); registering individual modules is a
  possible later optimization.
