# ADR 0004 — Snapshot + ordered delta stream with epoch/sequence

Status: accepted (2026-10-13)

## Decision
- One lifespan-managed producer updates in-memory quotes every 100 ms and publishes one coalesced
  `delta` batch (`epoch`, consecutive `seq`, `ts`, quotes) to every connection's bounded queue.
- On connect the server, **under the same lock used to publish**, registers the connection queue
  and captures a snapshot with its `seq` watermark. It sends the snapshot first and then only
  queued batches with `seq > watermark`. This removes the REST-snapshot/subscription race.
- Heartbeats (1 s) carry `server_time`, the current `seq` (never advanced), and the server's
  stale-instrument set. Clients compute displayed quote age with the server clock offset.
- Clients ignore `seq <= current`, and treat a gap or epoch change as "resynchronizing": they
  close the socket and reconnect for a fresh snapshot rather than continuing on incomplete data.
- Slow consumers: queue overflow (default 256 batches) drops the backlog, sends `resync`, and
  closes with code 4000. No unbounded buffering.
- Reconnect: exponential backoff with jitter, 0.5 s base, 15 s ceiling; immediate (~150 ms) after
  a deliberate resync.

## Consequences
Every client receives the same ordered batches and filters locally. Bandwidth is proportional to
all updates (~50 quotes/s, ~10 batches/s); per-client subscriptions are out of V1 scope.
