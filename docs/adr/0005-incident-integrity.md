# ADR 0005 — Incident integrity in PostgreSQL

Status: accepted (2026-10-13)

## Decision
- `uq_incidents_one_unresolved_per_rule`: partial unique index on `incidents(rule_id) WHERE
  status <> 'RESOLVED'`. Concurrent evaluators that both try to open an incident: one insert
  wins; the loser catches `IntegrityError`, rolls back (including its episode), and reports the
  winner's incident.
- `uq_alert_rules_one_enabled`: partial unique index on `(instrument_id, rule_type) WHERE enabled`.
- `ck_incidents_resolution_requirements`: a RESOLVED row must have a non-blank note, an
  acknowledgment time, a resolution time, and `condition_active = false`.
- Incident mutation + audit row + episode update commit in one transaction (`services/incidents.py`).
- Optimistic concurrency: user actions send `version`; a mismatch returns 409 `VERSION_CONFLICT`
  with `current_version` and leaves no audit row. System condition updates (breach/recovery) do
  not bump `version` because they never overwrite user-editable fields; resolve still re-checks
  `condition_active` under `SELECT … FOR UPDATE`.
- Audit and comment rows never cascade-delete.
