# ADR 0006 — $0 hosting: Vercel (frontend) + Render Free (API/stream) + Neon Free (PostgreSQL)

Status: accepted (2026-10-15), pending deployment authorization.

## Context
The owner wants a public demo with no recurring hosting charge. Vercel Hobby serves static
frontends; Render Free runs one Docker web service (0.1 CPU, 512 MB, spins down after 15 min
without inbound traffic, ~1 min spin-up); Neon Free hosts PostgreSQL (scale-to-zero after 5 min,
100 CU-hours/month, 1 GB). The frontend (`*.vercel.app`) and API (`*.onrender.com`) are
different sites, so an API-host cookie would be a third-party cookie that browsers block.
Vercel documents external rewrites (reverse proxy) but does not document WebSocket upgrades
through them, so we do not rely on that.

## Decision
- **REST is same-origin**: `frontend/vercel.json` rewrites `/api/*` to the Render service.
  The `HttpOnly; Secure; SameSite=Lax` session cookie, CSRF token, and Origin allow-list work
  exactly as before (ADR 0003). No CORS is enabled on the API.
- **WebSocket is direct** to `wss://<service>.onrender.com/ws/market`. The browser cannot send
  the session cookie there, so it first calls `POST /api/v1/stream/ticket` (cookie + CSRF +
  Origin checked, through the Vercel proxy) and sends `{"type":"auth","ticket":…}` as the first
  socket message. Tickets are 256-bit random, single use, valid 30 s, stored only as SHA-256
  digests in memory; redemption re-validates the session (revocation/expiry). The socket's
  `Origin` must still be allow-listed; unauthenticated sockets are closed after 5 s.
  Credentials never appear in URLs.
- Enabled by `MARKETOPS_STREAM_TICKET_AUTH_ENABLED=true` (backend) and `VITE_STREAM_URL`
  (frontend build). Same-origin deployments (Compose, nginx) keep cookie-only sockets.
- **Cold starts**: migrations + idempotent seed run inside the app process
  (`MARKETOPS_STARTUP_BOOTSTRAP=1`), measured at 51 s first boot / 34 s wake-up under a
  0.1-CPU Docker limit (vs 101–102 s with three processes). The UI explains the wait and retries.
- Socket fan-out is bounded (200 total, 4 per session).

## Consequences
- Every reconnect costs one extra REST call; reconnects already back off.
- Single worker constraint (ADR 0002) still holds: tickets live in process memory.
- Vercel preview deployments have different origins and are deliberately not allow-listed.
- Per-IP throttles rely on `X-Forwarded-For`; requests sent straight to the Render URL can spoof
  it. Login also throttles per email; a direct-to-origin secret header is a possible follow-up.
