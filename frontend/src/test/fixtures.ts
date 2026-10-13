import type { Schemas } from "../lib/api/client";
import type { DeltaMessage, HeartbeatMessage, SnapshotMessage, WireQuote } from "../lib/stream/protocol";

export const T0 = "2026-01-01T00:00:00.000Z";

export function wireQuote(id: string, overrides: Partial<WireQuote> = {}): WireQuote {
  return {
    id,
    symbol: `SYM-${id}`,
    bid: "100.00",
    ask: "100.10",
    mid: "100.05",
    spread_bps: "10.00",
    volume: 100,
    source_time: T0,
    received_time: T0,
    ...overrides,
  };
}

export function snapshot(overrides: Partial<SnapshotMessage> = {}): SnapshotMessage {
  return { type: "snapshot", epoch: "e1", seq: 10, server_time: T0, stale_ids: [], quotes: [wireQuote("a"), wireQuote("b")], ...overrides };
}

export function delta(seq: number, quotes: WireQuote[] = [wireQuote("a", { bid: "101.00" })], epoch = "e1"): DeltaMessage {
  return { type: "delta", epoch, seq, ts: T0, quotes };
}

export function heartbeat(overrides: Partial<HeartbeatMessage> = {}): HeartbeatMessage {
  return { type: "heartbeat", epoch: "e1", seq: 10, server_time: T0, stale_ids: [], ...overrides };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

export function errorResponse(status: number, code: string, message: string): Response {
  return jsonResponse({ error: { code, message, details: null, request_id: "req-1" } }, status);
}

export function ruleFixture(overrides: Partial<Schemas["RuleOut"]> = {}): Schemas["RuleOut"] {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    instrument_id: "22222222-2222-4222-8222-222222222222",
    symbol: "AAA",
    rule_type: "STALE",
    threshold: "30",
    unit: "SECONDS",
    enabled: true,
    version: 3,
    updated_at: T0,
    ...overrides,
  };
}

export function incidentFixture(overrides: Partial<Schemas["IncidentDetail"]> = {}): Schemas["IncidentDetail"] {
  const rule = ruleFixture();
  return {
    id: "33333333-3333-4333-8333-333333333333",
    number: 7,
    incident_type: "STALE",
    instrument_id: rule.instrument_id,
    symbol: "AAA",
    rule_id: rule.id,
    rule_version: rule.version,
    rule,
    severity: "HIGH",
    status: "OPEN",
    condition_active: true,
    condition_changed_at: T0,
    breach_count: 1,
    trigger_reason: "No quote for 45s",
    trigger_evidence: {},
    latest_evidence: {},
    opened_at: T0,
    acknowledged_at: null,
    acknowledged_by: null,
    assignee: null,
    resolved_at: null,
    resolved_by: null,
    resolution_note: null,
    updated_at: T0,
    version: 1,
    ...overrides,
  };
}

export function userFixture(role: Schemas["UserOut"]["role"]): Schemas["UserOut"] {
  return { id: "44444444-4444-4444-8444-444444444444", email: "u@example.com", display_name: "Test User", role };
}
