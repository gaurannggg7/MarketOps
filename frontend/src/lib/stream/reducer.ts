/**
 * Pure stream reducer. Given the current state and one server message, returns the next state
 * and an outcome telling the connection manager what to do.
 *
 * Rules:
 * - A snapshot replaces all quotes and sets the (epoch, seq) watermark.
 * - A delta with the same epoch and seq === watermark + 1 is applied.
 * - seq <= watermark is a duplicate/out-of-order batch and is ignored.
 * - seq > watermark + 1 is a gap; an epoch mismatch is a restart/reset. Both require resync:
 *   displayed data is marked as resynchronizing and the connection is re-established to obtain
 *   a fresh snapshot. We never continue applying an incomplete stream.
 * - Heartbeats carry server time (for freshness display) and the server's stale set; they do not
 *   advance the sequence, but a heartbeat watermark ahead of ours also reveals a gap.
 */
import type { ServerMessage, WireQuote } from "./protocol";

export type TransportStatus =
  | "idle"
  | "connecting"
  | "live"
  | "resyncing"
  | "reconnecting"
  | "offline";

export interface Quote {
  id: string;
  symbol: string;
  bid: string;
  ask: string;
  mid: string;
  spreadBps: string;
  volume: number;
  sourceTime: string;
  receivedTime: string;
  /** Server receipt time in epoch ms, for age computations against server-clock estimates. */
  receivedMs: number;
}

export interface StreamStats {
  batches: number;
  quotes: number;
  duplicates: number;
  gaps: number;
  epochChanges: number;
  resyncs: number;
  snapshots: number;
}

export interface StreamState {
  status: TransportStatus;
  epoch: string | null;
  seq: number;
  quotes: ReadonlyMap<string, Quote>;
  staleIds: ReadonlySet<string>;
  /** serverTime - clientTime, in ms, estimated from the latest snapshot/heartbeat. */
  serverOffsetMs: number;
  lastMessageAt: number | null;
  /** True when the displayed quotes may be outdated (resyncing, reconnecting, offline). */
  dataSuspect: boolean;
  resyncReason: string | null;
  stats: StreamStats;
}

export type Outcome =
  | { kind: "snapshot"; changed: Quote[] }
  | { kind: "applied"; changed: Quote[] }
  | { kind: "heartbeat"; staleChanged: boolean }
  | { kind: "duplicate" }
  | { kind: "resync"; reason: "gap" | "epoch_changed" | "server_requested" };

export const initialStats: StreamStats = {
  batches: 0,
  quotes: 0,
  duplicates: 0,
  gaps: 0,
  epochChanges: 0,
  resyncs: 0,
  snapshots: 0,
};

export function initialStreamState(): StreamState {
  return {
    status: "idle",
    epoch: null,
    seq: 0,
    quotes: new Map(),
    staleIds: new Set(),
    serverOffsetMs: 0,
    lastMessageAt: null,
    dataSuspect: true,
    resyncReason: null,
    stats: { ...initialStats },
  };
}

export function toQuote(w: WireQuote): Quote {
  return {
    id: w.id,
    symbol: w.symbol,
    bid: w.bid,
    ask: w.ask,
    mid: w.mid,
    spreadBps: w.spread_bps,
    volume: w.volume,
    sourceTime: w.source_time,
    receivedTime: w.received_time,
    receivedMs: Date.parse(w.received_time),
  };
}

function sameSet(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  if (a.size !== b.size) return false;
  for (const v of a) if (!b.has(v)) return false;
  return true;
}

export function markSuspect(state: StreamState, status: TransportStatus, reason: string | null): StreamState {
  return { ...state, status, dataSuspect: true, resyncReason: reason ?? state.resyncReason };
}

export function applyMessage(
  state: StreamState,
  msg: ServerMessage,
  nowMs: number,
): { state: StreamState; outcome: Outcome } {
  switch (msg.type) {
    case "snapshot": {
      const quotes = new Map<string, Quote>();
      for (const w of msg.quotes) quotes.set(w.id, toQuote(w));
      const epochChanged = state.epoch !== null && state.epoch !== msg.epoch;
      return {
        state: {
          ...state,
          status: "live",
          epoch: msg.epoch,
          seq: msg.seq,
          quotes,
          staleIds: new Set(msg.stale_ids),
          serverOffsetMs: Date.parse(msg.server_time) - nowMs,
          lastMessageAt: nowMs,
          dataSuspect: false,
          resyncReason: null,
          stats: {
            ...state.stats,
            snapshots: state.stats.snapshots + 1,
            epochChanges: state.stats.epochChanges + (epochChanged ? 1 : 0),
          },
        },
        outcome: { kind: "snapshot", changed: [...quotes.values()] },
      };
    }
    case "delta": {
      if (state.epoch === null) {
        return resync(state, "gap", nowMs);
      }
      if (msg.epoch !== state.epoch) {
        return resync(state, "epoch_changed", nowMs);
      }
      if (msg.seq <= state.seq) {
        return {
          state: { ...state, lastMessageAt: nowMs, stats: { ...state.stats, duplicates: state.stats.duplicates + 1 } },
          outcome: { kind: "duplicate" },
        };
      }
      if (msg.seq !== state.seq + 1) {
        return resync(state, "gap", nowMs);
      }
      const quotes = new Map(state.quotes);
      const changed: Quote[] = [];
      for (const w of msg.quotes) {
        const q = toQuote(w);
        quotes.set(q.id, q);
        changed.push(q);
      }
      return {
        state: {
          ...state,
          seq: msg.seq,
          quotes,
          lastMessageAt: nowMs,
          stats: { ...state.stats, batches: state.stats.batches + 1, quotes: state.stats.quotes + changed.length },
        },
        outcome: { kind: "applied", changed },
      };
    }
    case "heartbeat": {
      if (state.epoch !== null && msg.epoch !== state.epoch) {
        return resync(state, "epoch_changed", nowMs);
      }
      if (state.epoch !== null && msg.seq > state.seq) {
        return resync(state, "gap", nowMs);
      }
      const staleIds = new Set(msg.stale_ids);
      const staleChanged = !sameSet(staleIds, state.staleIds);
      return {
        state: {
          ...state,
          staleIds: staleChanged ? staleIds : state.staleIds,
          serverOffsetMs: Date.parse(msg.server_time) - nowMs,
          lastMessageAt: nowMs,
        },
        outcome: { kind: "heartbeat", staleChanged },
      };
    }
    case "resync":
      return resync(state, "server_requested", nowMs);
  }
}

function resync(
  state: StreamState,
  reason: "gap" | "epoch_changed" | "server_requested",
  nowMs: number,
): { state: StreamState; outcome: Outcome } {
  return {
    state: {
      ...markSuspect(state, "resyncing", reason),
      lastMessageAt: nowMs,
      stats: {
        ...state.stats,
        resyncs: state.stats.resyncs + 1,
        gaps: state.stats.gaps + (reason === "gap" ? 1 : 0),
        epochChanges: state.stats.epochChanges + (reason === "epoch_changed" ? 1 : 0),
      },
    },
    outcome: { kind: "resync", reason },
  };
}

/** Quote age in seconds measured on the server clock estimate (never the raw browser clock). */
export function quoteAgeSeconds(quote: Quote | undefined, serverOffsetMs: number, nowMs: number): number | null {
  if (!quote || !Number.isFinite(quote.receivedMs)) return null;
  return (nowMs + serverOffsetMs - quote.receivedMs) / 1000;
}
