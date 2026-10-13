# ADR 0002 — One backend worker / replica

Status: accepted (2026-10-13)

## Context
The synthetic feed, the stream sequence allocator (`epoch`, `seq`), the latest-quote snapshot,
the WebSocket connection registry, login throttling counters, and demo scenarios all live in
process memory (`backend/app/runtime.py`, `streaming/hub.py`).

## Decision
Run exactly one uvicorn worker and one backend replica. The Dockerfile command has no
`--workers` flag and the deployment docs forbid scaling the backend horizontally.

## Consequences
- Business records (users, sessions, watchlists, rules, incidents, comments, audit, events,
  sampled quotes) are durable in PostgreSQL and survive restarts.
- A restart creates a new stream epoch; clients detect the epoch change and resynchronize from a
  fresh snapshot. Active scenarios and throttle counters are lost on restart (documented).
- Multiple workers would each run their own simulator and evaluator, producing divergent
  streams and racing incident creation (the partial unique index would still prevent duplicate
  unresolved incidents, but streams would be inconsistent). Do not scale out until a shared
  feed/broadcast design (e.g. a single producer + pub/sub fan-out) exists.
