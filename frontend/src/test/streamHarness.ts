import { MarketStream, type StreamOptions } from "../lib/stream/store";
import { createFakeTimers, FakeSocket } from "./fakeSocket";

export function createHarness(overrides: Partial<StreamOptions> = {}) {
  const sockets: FakeSocket[] = [];
  const timers = createFakeTimers();
  const clock = { now: 1_000_000 };
  const stream = new MarketStream({
    url: () => "ws://test/ws/market",
    createSocket: (url) => {
      const s = new FakeSocket(url);
      sockets.push(s);
      return s;
    },
    random: () => 0,
    now: () => clock.now,
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    ...overrides,
  });
  const current = (): FakeSocket => {
    const s = sockets.at(-1);
    if (!s) throw new Error("no socket created");
    return s;
  };
  return { stream, sockets, timers, clock, current };
}
