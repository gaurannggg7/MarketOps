# Three-minute demo script

Setup (once): `make env db-up install migrate seed`, then `make dev-backend` and
`make dev-frontend` in two terminals; open http://localhost:5173. Passwords for
`operator@marketops.local` / `viewer@marketops.local` are in your local `.env`
(`DEMO_OPERATOR_PASSWORD`, `DEMO_VIEWER_PASSWORD`). Wait ~15 s after backend start (warm-up).

| Time | Action | What to point out |
| --- | --- | --- |
| 0:00 | Sign in as operator. Market monitor. | Synthetic-data badge; "Stream live" (transport) separate from "All quotes fresh" (freshness); ~50 quotes/s; cells flash; sort by Spread — select a row and it stays put while others re-sort. |
| 0:20 | ☆ an instrument, pick "Show: Watchlist", reload. | Membership persisted in PostgreSQL; filters live in the URL. |
| 0:35 | System status → Scenario "Stale symbol" → pick an instrument → Run. | Description text; auto-expiry countdown. Scenarios only touch the local simulator. |
| 0:50 | Watch the monitor: the instrument turns "■ Stale" after ~10 s; nav badge shows 1 incident. | Stream still "live": heartbeats don't freshen a quote; staleness = server receipt age on the server clock. |
| 1:05 | Incidents → open the new incident. | Trigger reason, trigger vs latest evidence, rule version, "Condition active". |
| 1:20 | Click the symbol → instrument detail. | D3 mid/bid–ask and spread charts (5m/15m/1h, tooltips, keyboard arrows), sampled-history caption, events grid (Infinite Row Model, server sort). |
| 1:40 | Back → Acknowledge → add a comment. Try Resolve. | Resolve blocked with an explanation while the condition is active. |
| 2:00 | System status → "Normal recovery" for that instrument. | Incident shows "Condition recovered" but stays ACKNOWLEDGED (no silent resolution). |
| 2:20 | Resolve with a note. | Timeline: opened (system), acknowledged, comment, condition recovered (system), resolved. |
| 2:40 | Optional: "Disconnect my stream". | Pill → Resynchronizing → Live; client panel snapshots +1; sequence continues. |
| 2:50 | Optional: sign in as viewer in a private window. | Read-only UI; the API returns 403 for any write. |
