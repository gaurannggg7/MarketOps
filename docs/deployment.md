# Deployment

Status: **not deployed.** No hosting was provisioned or authorized for this build. This document
gives exact steps and the checks that were run locally with the production-style containers.

## Topology
One HTTPS origin: nginx serves the SPA and proxies `/api/` and `/ws/market` (with WebSocket
upgrade) to **one** backend container (ADR 0002), which talks to PostgreSQL 17.

## Images
| Image | Base | Notes |
| --- | --- | --- |
| `marketops-backend:1.0.0` | python:3.13.5-slim | hashed lockfile install, non-root uid 10001, entrypoint runs `alembic upgrade head` then uvicorn (single worker) |
| `marketops-web:1.0.0` | node:24.11-alpine → nginx:1.29.3-alpine | static build + proxy config, port 8080 (8443 with TLS overlay) |

Build: `make images` (`docker compose --profile app build`).

## Configuration (environment)
| Variable | Required | Notes |
| --- | --- | --- |
| `MARKETOPS_DATABASE_URL` | yes | `postgresql+psycopg://user:pass@host:5432/db` |
| `MARKETOPS_ALLOWED_ORIGINS` | yes | JSON list of exact browser origins, e.g. `["https://marketops.example"]` |
| `MARKETOPS_COOKIE_SECURE` | yes (`true`) | `false` only for local HTTP (ADR 0003) |
| `MARKETOPS_ENVIRONMENT` | | `production` disables `seed --reset` |
| `MARKETOPS_SIMULATOR_SEED`, `MARKETOPS_WARMUP_SECONDS`, `MARKETOPS_QUOTE_RETENTION_HOURS` | | tuning |
| `MARKETOPS_SKIP_MIGRATIONS` | | `1` to run migrations as a separate release step |
| `DEMO_*_PASSWORD` | seed only | read by `python -m app.seed`; generate, never commit |

## Steps (any container host)
1. Provision PostgreSQL 17 (managed or container) and a TLS-terminating origin.
2. Set the environment above (secrets via the platform's secret store).
3. Run migrations: `docker run --rm -e MARKETOPS_DATABASE_URL=… marketops-backend:1.0.0 alembic upgrade head`.
4. Seed demo users once: `… marketops-backend:1.0.0 python -m app.seed` with `DEMO_*_PASSWORD` set.
   For a public demo, share only the viewer credentials (operator/scenario controls stay private).
5. Start one backend container and the web container; route the public HTTPS origin to web.
6. Readiness: `GET /api/v1/health/ready` must return 200.
7. Smoke: `MARKETOPS_URL=https://<origin> DEMO_OPERATOR_PASSWORD=… backend/.venv/bin/python scripts/smoke.py`
   (login, catalog, WebSocket upgrade, quote update, watchlist persistence, readiness, one
   incident transition).

## Proxy requirements
- Forward `Upgrade`/`Connection` for `/ws/market`; read timeout ≥ 60 s (heartbeats are 1 s).
- Preserve the browser `Origin` header; the backend validates it on writes and handshakes.
- Do not cache `/api/` or `index.html`; hashed `/assets/` may be cached immutable.

## Local production-style run (verified commands)
```bash
make images
docker compose --profile app up -d --wait
docker compose --profile app exec backend python -m app.seed
MARKETOPS_URL=http://localhost:8080 backend/.venv/bin/python scripts/smoke.py
# HTTPS variant
scripts/make_dev_cert.sh
MARKETOPS_PROXY_COOKIE_SECURE=true docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d --wait
```

## Costs to verify before provisioning
Not estimated here — check current pricing for: a small always-on container (the backend must
not scale to zero mid-demo or autoscale beyond 1), managed PostgreSQL (smallest tier with
backups), TLS/domain, egress (~50 quotes/s per connected browser), and log retention.
