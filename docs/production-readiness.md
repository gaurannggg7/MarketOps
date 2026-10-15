# Production readiness (public portfolio demo)

Scope: a public, read-only portfolio demo of simulated market data. Not a trading venue and not a
production service with an SLA. Status: ready for deployment pending authorization; nothing below
has been verified in the cloud yet (see `cloud-cicd-evidence.md`).

## Security
| Control | State |
| --- | --- |
| Session cookies | Opaque 256-bit tokens, SHA-256 at rest; `HttpOnly`, `SameSite=Lax`, `Secure` (`MARKETOPS_COOKIE_SECURE=true`); idle 30 min / absolute 12 h; public-demo sessions 2 h |
| CSRF | Per-session token + allow-listed `Origin` on every write, including login and demo entry |
| CORS | Not enabled; REST is same-origin through the Vercel rewrite |
| WebSocket auth | Cookie (same-origin) or single-use 30 s ticket as first message (split-origin); Origin allow-list; unauthenticated sockets closed in 5 s; 200 total / 4 per-session caps |
| Roles | VIEWER / OPERATOR enforced by the API; public-demo sessions rejected for every write (`PUBLIC_DEMO_READ_ONLY`) except logout and stream tickets |
| Credentials | None committed (secret scan in CI). Demo passwords come from the host's secret store; public visitors use the passwordless read-only entry; operator credentials stay private |
| Abuse limits | Login: 5 failures / 5 min per email+IP; demo entry: 30 / 10 min per IP; nginx (Compose deployments): 30 req/s API, 10 req/min auth, 10 WS per IP |
| Debug surface | `/api/v1/docs` disabled in production; errors carry request IDs, not stack traces |
| Frontend bundle | Contains only the public stream URL; no secrets |

## Data
- PostgreSQL (Neon Free in the $0 plan): TLS required, forward-only migrations applied at startup,
  idempotent seed that never re-hashes existing passwords, no public DB port in Compose.
- Retention: quote samples 3 h in production (history charts need ≤ 1 h). Incidents, comments,
  and audit history are kept.
- Backups: Neon Free provides a 6 h point-in-time window; Compose fallback has `deploy/backup.sh`
  (daily pg_dump, keep 7) and `deploy/restore.sh`.

## Reliability and resources
- One backend worker by design (ADR 0002); restarts start a new epoch and clients resync.
- Bounded queues, socket caps, and chart point limits; memory ≈120 MB under load at 0.1 CPU.
- Free-tier behavior: spin-down after 15 min idle, ~1–2 min cold start; UI explains and retries.
- Compose fallback: memory/CPU limits per container, json-file log rotation (10 MB × 3), health checks.

## Known gaps before calling this "production"
- No human security review (see `review-checklist.md`).
- Rate limiting is in-process and per-IP; IPs can be spoofed on requests sent directly to the
  Render origin (the Vercel path sets the visitor IP). A shared-secret header from Vercel to the
  origin is a possible follow-up.
- No alerting/paging, no external uptime monitor, no log retention beyond the platforms' defaults.
- Single region, single instance; no horizontal scaling (by design for V1).
