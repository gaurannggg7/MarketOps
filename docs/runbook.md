# Operations runbook

Scope: the MarketOps demo stack (single backend worker, PostgreSQL, nginx). This runbook shows
operational preparedness for the project; it does not describe a staffed on-call rotation.

Quick health: `curl -s localhost:8080/api/v1/health/ready` → `{"status":"ok","checks":{database,migrations,simulator}}`.
System status page (`/system`) separates client transport, synthetic feed, evaluator, database,
and quote persistence.

## Stale feed (one or more instruments stale)
Symptoms: monitor "N stale", stale incidents opening, stream pill still "Stream live".
1. System status → *Active scenarios*: a STALE_QUOTES scenario explains it; stop it or wait for
   expiry (scenarios expire automatically, max 15 min).
2. If no scenario: check *Synthetic feed* card and `server seq` advancing. If seq is frozen, the
   producer task died → readiness reports `simulator: background task failure`; restart the
   backend (see Restart).
3. Incidents are **not** auto-resolved when quotes recover: acknowledge, confirm the condition is
   recovered, then resolve with a note.

## Database unavailable
Symptoms: System status *Database: down* and *Quote persistence: degraded*; writes fail with
503 `PERSISTENCE_UNAVAILABLE`; readiness 503 (`database: down`). Live quotes keep streaming
(in-memory) and the UI marks data/persistence separately.
1. `docker compose ps db` / `docker compose logs db --tail 100`.
2. Restore PostgreSQL (`docker compose up -d db`). The backend reconnects automatically
   (`pool_pre_ping`); sampled quotes for the outage window are not backfilled (documented gap);
   the evaluator retries every second and reloads rules.
3. Verify readiness returns 200 and *Quote persistence* returns to ok.

## Dropped sockets / clients stuck "Reconnecting"
1. Client panel on System status: snapshots, gaps/epoch changes, last message.
2. Server: `connections`, `overflow disconnects` (slow consumers exceeding the 256-batch queue).
3. Proxy: WebSocket upgrades require `Upgrade`/`Connection` headers and a long read timeout
   (`frontend/nginx/default.conf`). A 403 on `/ws/market` means bad Origin or expired session —
   check `MARKETOPS_ALLOWED_ORIGINS` matches the browser origin exactly (scheme, host, port).
4. Clients reconnect with backoff (≤15 s) and always resync from a snapshot.

## Unhealthy deployment
- `/api/v1/health/live` 200 but `/ready` 503: read `checks`. `migrations: at X, expected Y` →
  run migrations; `simulator: not started` → startup failed, see logs; `database: down` → above.
- Container restart loop: `docker compose logs backend --tail 200`. Common causes: DB not
  reachable, migration failure (the entrypoint runs `alembic upgrade head` before uvicorn).

## Restart
`docker compose restart backend` (or `make dev-backend` locally). Effects: new epoch (clients
resync), active scenarios and login throttle counters cleared, unresolved incidents preserved,
15 s warm-up before stale evaluation. Never run more than one backend worker/replica (ADR 0002).

## Rollback
Two different operations — do not conflate them:
1. **Application image rollback** (normal): redeploy the previous image tags
   (`marketops-backend:<prev>`, `marketops-web:<prev>`). Safe when the schema is unchanged or
   migrations were backward compatible (the policy for this project).
2. **Migration reversal** (exceptional): `alembic downgrade <rev>` can drop data. It is never run
   automatically. Take a backup first (`pg_dump`), review the downgrade code, run in a
   maintenance window, then deploy the matching older image. The initial migration's downgrade
   drops every table.

## Data maintenance
- Retention: `make prune` (also every 10 min in-process) deletes quote samples older than 24 h.
- Demo reset (operator, typed confirmation in UI): restarts seeded price paths in a new epoch;
  incidents and audit history are kept. Full local wipe: `make seed-reset` (refuses in production).
