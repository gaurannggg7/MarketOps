# API conventions

The OpenAPI document is the contract: `GET /api/v1/openapi.json` (interactive docs at
`/api/v1/docs` on the backend). The committed copy lives at `frontend/src/lib/api/openapi.json`
and TypeScript types at `frontend/src/lib/api/schema.d.ts`.

## Generating and checking types
```bash
make api-types   # export OpenAPI from the backend code, regenerate schema.d.ts
make api-check   # regenerate and fail if git shows a diff (used in CI)
```
Export does not need a database (`python -m app.export_openapi`).

## Errors
Every error uses one shape and echoes the request ID (also in the `X-Request-ID` header; clients
may send their own matching `[A-Za-z0-9._-]{1,64}`):
```json
{"error": {"code": "VERSION_CONFLICT", "message": "…what to do next…", "details": {"current_version": 4}, "request_id": "…"}}
```
| Status | Codes |
| --- | --- |
| 401 | `UNAUTHENTICATED`, `INVALID_CREDENTIALS` |
| 403 | `FORBIDDEN` (role), `CSRF_REJECTED`, `ORIGIN_REJECTED` |
| 404 | `NOT_FOUND` (also used for other users' watchlists) |
| 409 | `VERSION_CONFLICT`, `INVALID_TRANSITION`, `CONDITION_ACTIVE`, `RULE_ALREADY_ENABLED`, `DUPLICATE_NAME`, `SCENARIO_CONFLICT`, `LIMIT_REACHED` |
| 422 | `VALIDATION_ERROR` (details = field list), `INVALID_THRESHOLD`, `RESOLUTION_NOTE_REQUIRED`, `EMPTY_COMMENT`, `INVALID_ASSIGNEE`, `INVALID_RANGE`, `NO_CHANGES` |
| 429 | `TOO_MANY_ATTEMPTS` (details.retry_after_seconds) |
| 503 | `PERSISTENCE_UNAVAILABLE` |

## Conventions
- Prices, mids and spreads are **decimal strings**; server math uses `Decimal`
  (`services/market_math.py`). Spread bps = ((ask − bid) / mid) × 10 000, rounded half-even to
  0.01; a WIDE_SPREAD breach is strictly greater than the threshold.
- Timestamps are ISO 8601 UTC.
- Optimistic concurrency: rule PATCH and incident acknowledge/assignment/resolve require the
  `version` the client last saw.
- Pagination: `offset`/`limit` with bounded `limit` (events ≤ 500, incidents ≤ 100); responses
  include `total`. Sorts are allow-listed and always end with a stable `id`/number tie-breaker.
- History: `range` ∈ {5m, 15m, 1h} → buckets of 1/3/10 s, at most 600 points.
- Writes need the session cookie, `X-CSRF-Token`, and an allowed `Origin`.

## Versioning
All routes are under `/api/v1`. Additive changes (new optional fields/endpoints) stay in v1;
breaking changes would introduce `/api/v2` alongside v1. The WebSocket protocol is versioned by
its message shapes (ADR 0004); a breaking change would use a new path.
