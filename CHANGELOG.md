# Changelog

## 1.0.0 — 2026-10-13 (local release candidate; not deployed)

### Added
- FastAPI backend: server-side sessions (Argon2, HttpOnly cookie, CSRF + Origin checks, idle and
  absolute expiry, login throttling), VIEWER/OPERATOR roles enforced server-side.
- PostgreSQL schema via Alembic `0001`: partial unique indexes for one enabled rule per
  instrument/type and one unresolved incident per rule; resolution check constraint; audit table.
- Seeded synthetic simulator (200 instruments, ~50 updates/s), lifespan-managed tasks,
  epoch/sequence WebSocket protocol with atomic snapshot registration, bounded queues, heartbeats
  with server-side stale sets, sampled quote persistence with 24 h retention.
- Clock-driven STALE / WIDE_SPREAD evaluator with warm-up and restart recovery; incident workflow
  with optimistic concurrency, comments, assignment, transactional audit, timeline.
- REST API under `/api/v1` with consistent error payloads, request IDs, generated TypeScript types.
- React frontend: market monitor (AG Grid Community, live transactions), instrument detail (D3
  charts, Infinite Row Model events grid, rule editor), incident workspace, system status with
  scenarios; resilient stream client with backoff + jitter and resync on gaps/epoch changes.
- Docker images (backend, nginx web), Compose stack, HTTPS overlay, smoke script, benchmark,
  CI workflow, documentation set.

### Known limitations
See README "Known limitations" and docs/testing.md.
