import { vi } from "vitest";
import type { SocketLike } from "../lib/stream/store";

export class FakeSocket implements SocketLike {
  onopen: SocketLike["onopen"] = null;
  onmessage: SocketLike["onmessage"] = null;
  onclose: SocketLike["onclose"] = null;
  onerror: SocketLike["onerror"] = null;
  close = vi.fn<(code?: number, reason?: string) => void>();
  readonly sent: string[] = [];
  constructor(readonly url: string) {}

  send(data: string): void {
    this.sent.push(data);
  }

  /** Simulate the connection opening. */
  open(): void {
    this.onopen?.({});
  }

  /** Deliver a server message through the currently attached handler (no-op if detached). */
  emit(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  /** Simulate the server/network closing the socket. */
  serverClose(code: number): void {
    this.onclose?.({ code });
  }

  get detached(): boolean {
    return this.onmessage === null && this.onclose === null && this.onopen === null && this.onerror === null;
  }
}

export interface FakeTimers {
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
  /** Pending (not cleared, not fired) timers. */
  pending: () => { id: number; ms: number }[];
  /** Fire the oldest pending timer. */
  fireNext: () => void;
}

export function createFakeTimers(): FakeTimers {
  let nextId = 1;
  const timers = new Map<number, { fn: () => void; ms: number }>();
  return {
    setTimer: (fn, ms) => {
      const id = nextId++;
      timers.set(id, { fn, ms });
      return id;
    },
    clearTimer: (handle) => {
      timers.delete(handle as number);
    },
    pending: () => [...timers.entries()].map(([id, t]) => ({ id, ms: t.ms })),
    fireNext: () => {
      const first = timers.entries().next();
      if (first.done) throw new Error("no pending timer");
      const [id, t] = first.value;
      timers.delete(id);
      t.fn();
    },
  };
}
