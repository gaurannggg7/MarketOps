import { describe, expect, it } from "vitest";
import { delta, heartbeat, snapshot, wireQuote } from "../../test/fixtures";
import { applyMessage, initialStreamState, quoteAgeSeconds, toQuote, type StreamState } from "./reducer";

const NOW = Date.parse("2026-01-01T00:00:00.000Z");

function live(): StreamState {
  return applyMessage(initialStreamState(), snapshot(), NOW).state;
}

describe("applyMessage: snapshot", () => {
  it("sets epoch, seq, quotes, stale ids and clears dataSuspect", () => {
    const initial = initialStreamState();
    expect(initial.dataSuspect).toBe(true);
    const { state, outcome } = applyMessage(initial, snapshot({ stale_ids: ["b"] }), NOW);
    expect(state.status).toBe("live");
    expect(state.epoch).toBe("e1");
    expect(state.seq).toBe(10);
    expect([...state.quotes.keys()].sort()).toEqual(["a", "b"]);
    expect([...state.staleIds]).toEqual(["b"]);
    expect(state.dataSuspect).toBe(false);
    expect(state.stats.snapshots).toBe(1);
    expect(outcome.kind).toBe("snapshot");
  });

  it("replaces previous quotes and counts an epoch change", () => {
    const { state } = applyMessage(live(), snapshot({ epoch: "e2", seq: 1, quotes: [wireQuote("c")] }), NOW);
    expect([...state.quotes.keys()]).toEqual(["c"]);
    expect(state.stats.epochChanges).toBe(1);
  });

  it("clears suspect state after a resync", () => {
    const resynced = applyMessage(live(), delta(12), NOW).state;
    expect(resynced.dataSuspect).toBe(true);
    const fresh = applyMessage(resynced, snapshot({ seq: 12 }), NOW).state;
    expect(fresh.dataSuspect).toBe(false);
    expect(fresh.resyncReason).toBeNull();
  });
});

describe("applyMessage: delta", () => {
  it("applies the consecutive delta and reports changed quotes", () => {
    const { state, outcome } = applyMessage(live(), delta(11, [wireQuote("a", { bid: "101.00" })]), NOW);
    expect(state.seq).toBe(11);
    expect(state.quotes.get("a")?.bid).toBe("101.00");
    expect(state.quotes.get("b")?.bid).toBe("100.00");
    expect(outcome.kind).toBe("applied");
    if (outcome.kind === "applied") expect(outcome.changed.map((q) => q.id)).toEqual(["a"]);
    expect(state.stats.batches).toBe(1);
    expect(state.stats.quotes).toBe(1);
  });

  it("ignores duplicate and older deltas", () => {
    const before = live();
    for (const seq of [10, 9]) {
      const { state, outcome } = applyMessage(before, delta(seq, [wireQuote("a", { bid: "999" })]), NOW);
      expect(outcome.kind).toBe("duplicate");
      expect(state.seq).toBe(10);
      expect(state.quotes.get("a")?.bid).toBe("100.00");
      expect(state.stats.duplicates).toBe(before.stats.duplicates + 1);
      expect(state.dataSuspect).toBe(false);
    }
  });

  it("treats a gap as a resync and does not apply the delta quotes", () => {
    const before = live();
    const { state, outcome } = applyMessage(before, delta(12, [wireQuote("a", { bid: "999" })]), NOW);
    expect(outcome).toEqual({ kind: "resync", reason: "gap" });
    expect(state.status).toBe("resyncing");
    expect(state.dataSuspect).toBe(true);
    expect(state.seq).toBe(10);
    expect(state.quotes.get("a")?.bid).toBe("100.00");
    expect(state.stats.gaps).toBe(1);
    expect(state.stats.resyncs).toBe(1);
  });

  it("resyncs on an epoch mismatch", () => {
    const { state, outcome } = applyMessage(live(), delta(11, [wireQuote("a", { bid: "999" })], "other"), NOW);
    expect(outcome).toEqual({ kind: "resync", reason: "epoch_changed" });
    expect(state.status).toBe("resyncing");
    expect(state.quotes.get("a")?.bid).toBe("100.00");
    expect(state.stats.epochChanges).toBe(1);
  });

  it("resyncs when a delta arrives before any snapshot", () => {
    const { state, outcome } = applyMessage(initialStreamState(), delta(1), NOW);
    expect(outcome.kind).toBe("resync");
    expect(state.status).toBe("resyncing");
    expect(state.quotes.size).toBe(0);
  });
});

describe("applyMessage: heartbeat", () => {
  it("does not change seq, updates stale ids and server offset", () => {
    const { state, outcome } = applyMessage(
      live(),
      heartbeat({ stale_ids: ["a"], server_time: "2026-01-01T00:00:05.000Z" }),
      NOW,
    );
    expect(state.seq).toBe(10);
    expect([...state.staleIds]).toEqual(["a"]);
    expect(state.serverOffsetMs).toBe(5000);
    expect(outcome).toEqual({ kind: "heartbeat", staleChanged: true });
  });

  it("reports staleChanged false (and keeps the same set) when stale ids are unchanged", () => {
    const first = applyMessage(live(), heartbeat({ stale_ids: ["a"] }), NOW).state;
    const { state, outcome } = applyMessage(first, heartbeat({ stale_ids: ["a"] }), NOW);
    expect(outcome).toEqual({ kind: "heartbeat", staleChanged: false });
    expect(state.staleIds).toBe(first.staleIds);
  });

  it("reports staleChanged when an instrument recovers", () => {
    const first = applyMessage(live(), heartbeat({ stale_ids: ["a"] }), NOW).state;
    const { state, outcome } = applyMessage(first, heartbeat({ stale_ids: [] }), NOW);
    expect(outcome).toEqual({ kind: "heartbeat", staleChanged: true });
    expect(state.staleIds.size).toBe(0);
  });

  it("resyncs with gap when the heartbeat seq is ahead of the client", () => {
    const { state, outcome } = applyMessage(live(), heartbeat({ seq: 11 }), NOW);
    expect(outcome).toEqual({ kind: "resync", reason: "gap" });
    expect(state.status).toBe("resyncing");
    expect(state.seq).toBe(10);
  });

  it("resyncs on epoch change in heartbeat", () => {
    const { outcome } = applyMessage(live(), heartbeat({ epoch: "zzz" }), NOW);
    expect(outcome).toEqual({ kind: "resync", reason: "epoch_changed" });
  });
});

describe("applyMessage: server resync", () => {
  it("maps to server_requested and marks data suspect", () => {
    const { state, outcome } = applyMessage(live(), { type: "resync", reason: "restart", epoch: "e1" }, NOW);
    expect(outcome).toEqual({ kind: "resync", reason: "server_requested" });
    expect(state.status).toBe("resyncing");
    expect(state.dataSuspect).toBe(true);
    expect(state.resyncReason).toBe("server_requested");
  });
});

describe("quoteAgeSeconds", () => {
  const quote = toQuote(wireQuote("a", { received_time: "2026-01-01T00:00:00.000Z" }));

  it("uses the server clock offset rather than raw client time", () => {
    // Client clock is 100s behind the server: raw client age would be -90s.
    const clientNow = quote.receivedMs - 100_000 + 10_000;
    expect(quoteAgeSeconds(quote, 100_000, clientNow)).toBe(10);
    expect(quoteAgeSeconds(quote, 0, clientNow)).toBe(-90);
  });

  it("returns null for a missing quote or unparsable timestamp", () => {
    expect(quoteAgeSeconds(undefined, 0, NOW)).toBeNull();
    expect(quoteAgeSeconds(toQuote(wireQuote("a", { received_time: "garbage" })), 0, NOW)).toBeNull();
  });

  it("derives the offset from a snapshot", () => {
    const state = applyMessage(initialStreamState(), snapshot({ server_time: "2026-01-01T00:01:00.000Z" }), NOW - 30_000).state;
    expect(state.serverOffsetMs).toBe(90_000);
    const q = state.quotes.get("a");
    expect(quoteAgeSeconds(q, state.serverOffsetMs, NOW - 30_000)).toBe(60);
  });
});
