import { describe, expect, it, vi } from "vitest";
import { delta, heartbeat, snapshot } from "../../test/fixtures";
import { createHarness } from "../../test/streamHarness";
import { CloseCode } from "./protocol";
import type { Quote } from "./reducer";

describe("MarketStream", () => {
  it("start() creates exactly one socket and repeated start() does not duplicate", () => {
    const h = createHarness();
    h.stream.start();
    h.stream.start();
    h.stream.start();
    expect(h.sockets).toHaveLength(1);
    expect(h.stream.socketsCreated).toBe(1);
    expect(h.stream.getState().status).toBe("connecting");
    expect(h.sockets[0]?.url).toBe("ws://test/ws/market");
  });

  it("goes live on snapshot and notifies quote listeners", () => {
    const h = createHarness();
    const received: { ids: string[]; kind: string }[] = [];
    h.stream.onQuotes((changed: readonly Quote[], kind) => received.push({ ids: changed.map((q) => q.id), kind }));
    h.stream.start();
    h.current().emit(snapshot());
    expect(h.stream.getState().status).toBe("live");
    expect(h.stream.getState().dataSuspect).toBe(false);
    expect(received).toEqual([{ ids: ["a", "b"], kind: "snapshot" }]);
    h.current().emit(delta(11));
    expect(received.at(-1)).toEqual({ ids: ["a"], kind: "delta" });
  });

  it("ignores malformed payloads", () => {
    const h = createHarness();
    h.stream.start();
    h.current().onmessage?.({ data: "not json" });
    h.current().onmessage?.({ data: 42 });
    expect(h.stream.getState().status).toBe("connecting");
  });

  it("subscribe notifies on state change and unsubscribe stops it", () => {
    const h = createHarness();
    const listener = vi.fn();
    const unsub = h.stream.subscribe(listener);
    h.stream.start();
    const afterStart = listener.mock.calls.length;
    expect(afterStart).toBeGreaterThan(0);
    unsub();
    h.current().emit(snapshot());
    expect(listener).toHaveBeenCalledTimes(afterStart);
  });

  it("onQuotes unsubscribe works", () => {
    const h = createHarness();
    const listener = vi.fn();
    const off = h.stream.onQuotes(listener);
    h.stream.start();
    off();
    h.current().emit(snapshot());
    expect(listener).not.toHaveBeenCalled();
  });

  it("a gap delta detaches and closes the old socket and schedules exactly one reconnect", () => {
    const h = createHarness();
    h.stream.start();
    const first = h.current();
    first.emit(snapshot());
    first.emit(delta(15));
    expect(first.detached).toBe(true);
    expect(first.close).toHaveBeenCalledTimes(1);
    expect(h.stream.getState().status).toBe("resyncing");
    expect(h.stream.getState().dataSuspect).toBe(true);
    expect(h.timers.pending()).toHaveLength(1);
    expect(h.sockets).toHaveLength(1);
    h.timers.fireNext();
    expect(h.sockets).toHaveLength(2);
    expect(h.timers.pending()).toHaveLength(0);
  });

  it("ignores messages from a replaced socket", () => {
    const h = createHarness();
    h.stream.start();
    const first = h.current();
    first.emit(snapshot());
    const staleHandler = first.onmessage;
    first.emit(delta(15));
    h.timers.fireNext();
    const second = h.current();
    expect(second).not.toBe(first);
    staleHandler?.({ data: JSON.stringify(snapshot({ epoch: "OLD", seq: 99 })) });
    expect(h.stream.getState().epoch).toBe("e1");
    expect(h.stream.getState().status).not.toBe("live");
    second.emit(snapshot({ epoch: "e2", seq: 1 }));
    expect(h.stream.getState().epoch).toBe("e2");
  });

  it("heartbeat gap and server resync also reconnect via a single timer", () => {
    const h = createHarness();
    h.stream.start();
    h.current().emit(snapshot());
    h.current().emit(heartbeat({ seq: 50 }));
    expect(h.timers.pending()).toHaveLength(1);
    h.timers.fireNext();
    h.current().emit(snapshot());
    h.current().emit({ type: "resync", reason: "x", epoch: "e1" });
    expect(h.timers.pending()).toHaveLength(1);
  });

  describe("backoff", () => {
    it("with random=0 returns the jitter floor; with random=1 the exponential ceiling, capped", () => {
      const lo = createHarness({ random: () => 0, baseDelayMs: 500, maxDelayMs: 15_000 }).stream;
      const hi = createHarness({ random: () => 1, baseDelayMs: 500, maxDelayMs: 15_000 }).stream;
      for (const attempt of [1, 2, 3, 4, 5, 6, 10, 50]) {
        expect(lo.backoffDelay(attempt)).toBe(250);
      }
      expect([1, 2, 3, 4, 5, 6, 7, 50].map((a) => hi.backoffDelay(a))).toEqual([500, 1000, 2000, 4000, 8000, 15_000, 15_000, 15_000]);
    });

    it("stays within [base/2, max] for arbitrary jitter", () => {
      for (const r of [0, 0.25, 0.5, 0.99, 1]) {
        const s = createHarness({ random: () => r, baseDelayMs: 100, maxDelayMs: 1000 }).stream;
        for (let a = 1; a <= 12; a++) {
          const d = s.backoffDelay(a);
          expect(d).toBeGreaterThanOrEqual(50);
          expect(d).toBeLessThanOrEqual(1000);
        }
      }
    });

    it("abnormal close (1006) schedules one reconnect with growing delays", () => {
      const h = createHarness({ random: () => 1, baseDelayMs: 500, maxDelayMs: 4000 });
      h.stream.start();
      const delays: number[] = [];
      for (let i = 0; i < 5; i++) {
        h.current().serverClose(1006);
        expect(h.stream.getState().status).toBe("reconnecting");
        const pending = h.timers.pending();
        expect(pending).toHaveLength(1);
        delays.push(pending[0]?.ms ?? -1);
        h.timers.fireNext();
      }
      expect(delays).toEqual([500, 1000, 2000, 4000, 4000]);
      expect(h.sockets).toHaveLength(6);
    });

    it("sets nextRetryAt from the injected clock", () => {
      const h = createHarness({ random: () => 1 });
      h.stream.start();
      h.current().serverClose(1006);
      expect(h.stream.nextRetryAt).toBe(h.clock.now + 500);
    });

    it("a successful snapshot resets the attempt counter", () => {
      const h = createHarness({ random: () => 1, baseDelayMs: 500, maxDelayMs: 15_000 });
      h.stream.start();
      h.current().serverClose(1006);
      h.timers.fireNext();
      h.current().serverClose(1006);
      expect(h.timers.pending()[0]?.ms).toBe(1000);
      h.timers.fireNext();
      h.current().emit(snapshot());
      h.current().serverClose(1006);
      expect(h.timers.pending()[0]?.ms).toBe(500);
    });
  });

  it("uses the quick resync delay for RESYNC and SCENARIO_DISCONNECT closes", () => {
    for (const code of [CloseCode.RESYNC, CloseCode.SCENARIO_DISCONNECT]) {
      const h = createHarness({ resyncDelayMs: 150 });
      h.stream.start();
      h.current().serverClose(code);
      expect(h.stream.getState().status).toBe("resyncing");
      expect(h.timers.pending().map((t) => t.ms)).toEqual([150]);
    }
  });

  it("stop() clears timers, detaches/closes the socket, goes idle and never reconnects", () => {
    const h = createHarness();
    h.stream.start();
    const sock = h.current();
    sock.emit(snapshot());
    sock.serverClose(1006);
    expect(h.timers.pending()).toHaveLength(1);
    h.stream.stop();
    expect(h.timers.pending()).toHaveLength(0);
    expect(h.stream.getState().status).toBe("idle");
    expect(h.stream.isRunning).toBe(false);
    expect(h.stream.nextRetryAt).toBeNull();
    expect(h.sockets).toHaveLength(1);

    // stop with a live socket
    const h2 = createHarness();
    h2.stream.start();
    const s2 = h2.current();
    s2.emit(snapshot());
    h2.stream.stop();
    expect(s2.detached).toBe(true);
    expect(s2.close).toHaveBeenCalledTimes(1);
    expect(h2.stream.getState().status).toBe("idle");
    expect(h2.timers.pending()).toHaveLength(0);
    expect(h2.sockets).toHaveLength(1);
    h2.stream.stop();
  });

  it("close code 4002 (logged out) stops reconnecting and goes offline", () => {
    const h = createHarness();
    h.stream.start();
    h.current().emit(snapshot());
    h.current().serverClose(CloseCode.LOGGED_OUT);
    const s = h.stream.getState();
    expect(s.status).toBe("offline");
    expect(s.dataSuspect).toBe(true);
    expect(s.resyncReason).toBe("logged_out");
    expect(h.timers.pending()).toHaveLength(0);
    expect(h.stream.isRunning).toBe(false);
    expect(h.sockets).toHaveLength(1);
  });

  it("close code 4401 also goes offline without reconnecting", () => {
    const h = createHarness();
    h.stream.start();
    h.current().serverClose(CloseCode.UNAUTHENTICATED);
    expect(h.stream.getState().status).toBe("offline");
    expect(h.timers.pending()).toHaveLength(0);
  });

  it("start() after stop() creates a fresh socket", () => {
    const h = createHarness();
    h.stream.start();
    h.stream.stop();
    h.stream.start();
    expect(h.sockets).toHaveLength(2);
    expect(h.sockets[0]?.detached).toBe(true);
  });

  it("resyncNow() replaces the socket without leaving timers behind", () => {
    const h = createHarness();
    h.stream.start();
    const first = h.current();
    first.emit(snapshot());
    h.stream.resyncNow();
    expect(first.detached).toBe(true);
    expect(h.sockets).toHaveLength(2);
    expect(h.timers.pending()).toHaveLength(0);
    expect(h.stream.getState().status).toBe("resyncing");
  });
});
