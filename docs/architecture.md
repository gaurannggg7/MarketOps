# Architecture

MarketOps is a single-origin web app: a React SPA and a FastAPI backend behind one reverse proxy
(nginx in containers, Vite's proxy in development), with PostgreSQL for all durable records.
All market data is synthetic and generated in-process.

```mermaid
flowchart LR
  subgraph Browser
    UI[React SPA<br/>TanStack Query · AG Grid · D3]
    MS[MarketStream store<br/>reducer + reconnect]
  end
  subgraph Origin["Single HTTPS origin (nginx / Vite proxy)"]
    P[/"/ → static, /api → backend, /ws → backend (Upgrade)"/]
  end
  subgraph Backend["FastAPI — ONE worker (ADR 0002)"]
    API[REST /api/v1]
    WS[/ws/market]
    RT[Runtime]
    SIM[Simulator<br/>seeded random walk]
    HUB[StreamHub<br/>epoch · seq · bounded queues]
    EV[RuleEvaluator<br/>1 s clock loop]
    SMP[Sampler<br/>≤1 sample/instrument/s]
  end
  DB[(PostgreSQL 17)]
  UI -- cookie + CSRF --> P --> API
  MS -- cookie, Origin --> P --> WS
  RT --- SIM & HUB & EV & SMP
  SIM -- quotes --> HUB -- snapshot/delta/heartbeat --> WS
  HUB -- latest quotes --> EV
  EV -- incidents, episodes, audit (1 txn) --> DB
  SMP -- batched inserts --> DB
  API <--> DB
```

## Components (backend/app)
| Module | Responsibility |
| --- | --- |
| `main.py` | App factory, lifespan (start/stop one `Runtime`), request-ID middleware, routers |
| `runtime.py` | Owns simulator, hub, scenarios, evaluator; supervised background tasks (producer 100 ms, heartbeat 1 s, sampler 1 s, evaluator 1 s, retention 10 min); component health |
| `streaming/simulator.py` | Deterministic seeded quotes; shuffled update cycle so each instrument updates ~every 4 s at 200 instruments × 50 updates/s; honors pause/widen scenarios |
| `streaming/hub.py` | Authoritative latest quotes, epoch/seq allocation, lock-protected register+snapshot, coalesced deltas, bounded per-connection queues, overflow → resync |
| `streaming/evaluator.py` | Clock-driven STALE / WIDE_SPREAD evaluation, warm-up grace, rebuilds condition state from PostgreSQL |
| `services/incidents.py` | Incident state machine, atomic audit + episode updates, duplicate-race handling |
| `services/market_math.py` | Decimal mid/spread math and rounding rules (single source) |
| `auth/` | Argon2 hashing, opaque sessions, CSRF/Origin checks, role guards, login throttle |
| `api/` | REST routers and the WebSocket endpoint |

## Frontend (frontend/src)
| Area | Notes |
| --- | --- |
| `lib/api` | Generated OpenAPI types (`schema.d.ts`), typed `openapi-fetch` client, `ApiError`, in-memory CSRF token |
| `lib/stream` | Pure `reducer.ts` (snapshot/delta/heartbeat/resync rules), `store.ts` (`MarketStream`: one socket at a time, backoff+jitter, timer cleanup), selector hook via `useSyncExternalStore` |
| `features/monitor` | AG Grid client-side model; live updates via `applyTransactionAsync` (no React render per tick), stable row IDs, cell flash, selected row kept in place via `postSortRows`, URL-persisted filters |
| `features/instrument` | D3 charts (scales/shapes/bisector computed by D3, SVG rendered by React), rule editor, events grid on the Infinite Row Model |
| `features/incidents` | Filtered list (URL state), detail with evidence, controls, timeline |
| `features/system` | Client vs server health, scenarios, reset with typed confirmation |

## Streaming protocol and the snapshot race
See ADR 0004. The race being prevented: a client that fetches a REST snapshot and then subscribes
can miss updates published in between, or apply them twice. Here registration and snapshot
capture happen atomically under the hub lock that also guards publication, so the connection's
queue holds exactly the batches after its snapshot watermark. The client still validates
`seq` continuity and resyncs on any gap (defense in depth; e.g. after an overflow).

Message types: `snapshot{epoch, seq, server_time, stale_ids, quotes[]}`,
`delta{epoch, seq, ts, quotes[]}`, `heartbeat{epoch, seq, server_time, stale_ids}`,
`resync{reason, epoch}`. Close codes: 4000 resync, 4001 scenario disconnect, 4002 logged out,
4401 unauthenticated, 4403 forbidden origin (the last two before accept → HTTP 403 handshake).

## Freshness vs transport
- Transport: the browser's socket state (`connecting/live/resyncing/reconnecting/offline`).
- Freshness: server-computed. An instrument is stale when *backend receipt time* of its last quote
  is older than its STALE rule threshold (default 10 s), evaluated on the server clock.
  Heartbeats never refresh a quote. The UI shows age using the server clock offset learned from
  heartbeats, so a skewed browser clock does not change staleness.

## Persistence boundaries
| Durable (PostgreSQL) | In memory (lost on restart) |
| --- | --- |
| users, sessions, instruments, watchlists, rules, alert episodes, incidents, comments, audit, market events, sampled quotes (24 h retention) | latest quote per instrument, stream epoch/seq, connection queues, active scenarios, login throttle counters |

Quote persistence is **sampled** (≤1 row per instrument per second, batched); it is not a tick
archive. Retention: rows older than `MARKETOPS_QUOTE_RETENTION_HOURS` (24) are pruned every
10 minutes and by `make prune`.

## Restart behavior
1. New process → new epoch; seq restarts at 0; clients see the epoch change and resync.
2. Runtime loads instruments and rules, and rebuilds `condition_active` from unresolved incidents.
3. Warm-up grace (`MARKETOPS_WARMUP_SECONDS`, 15 s) suppresses STALE evaluation so a restart does
   not open spurious incidents; unresolved incidents are preserved and only marked recovered when
   fresh quotes actually satisfy the rule.
