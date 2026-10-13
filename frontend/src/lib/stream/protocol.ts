/** Wire protocol for /ws/market (see docs/architecture.md, "Streaming protocol"). */

export interface WireQuote {
  id: string;
  symbol: string;
  bid: string;
  ask: string;
  mid: string;
  spread_bps: string;
  volume: number;
  source_time: string;
  received_time: string;
}

export interface SnapshotMessage {
  type: "snapshot";
  epoch: string;
  seq: number;
  server_time: string;
  stale_ids: string[];
  quotes: WireQuote[];
}

export interface DeltaMessage {
  type: "delta";
  epoch: string;
  seq: number;
  ts: string;
  quotes: WireQuote[];
}

export interface HeartbeatMessage {
  type: "heartbeat";
  epoch: string;
  seq: number;
  server_time: string;
  stale_ids: string[];
}

export interface ResyncMessage {
  type: "resync";
  reason: string;
  epoch: string;
}

export type ServerMessage = SnapshotMessage | DeltaMessage | HeartbeatMessage | ResyncMessage;

/** Application close codes sent by the server. */
export const CloseCode = {
  RESYNC: 4000,
  SCENARIO_DISCONNECT: 4001,
  LOGGED_OUT: 4002,
  UNAUTHENTICATED: 4401,
  FORBIDDEN_ORIGIN: 4403,
} as const;

export function parseServerMessage(raw: unknown): ServerMessage | null {
  if (typeof raw !== "string") return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object" || !("type" in value)) return null;
  const type = value.type;
  if (type === "snapshot" || type === "delta" || type === "heartbeat" || type === "resync") {
    return value as ServerMessage;
  }
  return null;
}
