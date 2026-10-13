# Human review checklist

No human review has been performed on this codebase yet. All review to date is **agent review**
(Claude Code reviewing its own and a subagent's changes). A human reviewer should work through:

## Authentication and sessions
- [ ] Argon2 parameters acceptable; dummy-hash timing equalization in `auth/security.py`.
- [ ] Session cookie flags (`HttpOnly`, `SameSite=Lax`, `Secure` in HTTPS) and expiry math in `auth/deps.py`.
- [ ] CSRF derivation (`derive_csrf_token`) and Origin enforcement for every unsafe method and the WebSocket handshake.
- [ ] No credentials in URLs, logs, or localStorage (grep the frontend for `localStorage`).
- [ ] Every mutating route depends on `require_operator` or owner checks (watchlists).

## Incident concurrency
- [ ] Partial unique index + IntegrityError path in `services/incidents.record_breach`.
- [ ] `SELECT … FOR UPDATE` + version checks for acknowledge/assign/resolve; no audit row on failure.
- [ ] Decision that system condition changes do not bump `version` (ADR 0005).

## Migrations
- [ ] `0001_initial_schema` constraints, partial indexes, no cascades on audit/comments.
- [ ] Downgrade is destructive; confirm it is never run automatically.

## Deployment configuration
- [ ] Single-worker constraint enforced in the image command and docs (ADR 0002).
- [ ] nginx WebSocket upgrade, timeouts, CSP, and header forwarding.
- [ ] `MARKETOPS_ALLOWED_ORIGINS` / `MARKETOPS_COOKIE_SECURE` set correctly for the target origin.

## Measured claims
- [ ] `docs/performance.md` numbers match the JSON under `benchmarks/` and state machine, workload, and duration.
- [ ] README/release notes make no claims beyond `docs/testing.md` evidence.
