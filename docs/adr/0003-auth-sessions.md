# ADR 0003 — Server-side opaque sessions, CSRF, and Origin checks

Status: accepted (2026-10-13)

## Decision
- Login verifies Argon2id hashes (argon2-cffi defaults). Unknown emails are verified against a
  dummy hash to equalize timing; the error message is identical for unknown user / wrong password.
- A random 256-bit token is set in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` when
  `MARKETOPS_COOKIE_SECURE=true`). Only its SHA-256 digest is stored in `sessions.token_hash`.
- Expiry: idle 30 min (sliding, `last_seen_at` refreshed at most once a minute) and absolute
  12 h. Logout sets `revoked_at` and closes that session's WebSocket(s).
- CSRF: the token is `sha256("marketops-csrf:" + session_token)`, returned in login and
  `/auth/me` / `/auth/session` bodies and held only in browser memory. Every POST/PUT/PATCH/DELETE
  requires `X-CSRF-Token` matching the stored digest **and** an `Origin` in
  `MARKETOPS_ALLOWED_ORIGINS`. Login itself requires an allowed Origin (login-CSRF).
- WebSocket handshakes require an allowed `Origin` and a valid session cookie; otherwise the
  socket is closed before `accept` (HTTP 403). Credentials never appear in URLs or localStorage.
- Login throttling: 5 failures per (email, client address) per 5 minutes, in-process (ADR 0002).
- Roles are read from the database per request; the client never supplies role or actor identity.

## Local HTTP exception
`MARKETOPS_COOKIE_SECURE=false` is permitted only for local development over `http://localhost`.
Any deployment behind HTTPS must set it to `true`.

## Consequences
- A deterministic per-session CSRF token lets multiple tabs share a session without token
  rotation conflicts. Rotation happens naturally with each new login.
- Throttling is per-process and resets on restart; a shared store would be needed for multiple
  replicas.
