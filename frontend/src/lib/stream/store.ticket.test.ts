import { describe, expect, it } from "vitest";
import { snapshot } from "../../test/fixtures";
import { createHarness } from "../../test/streamHarness";

/** Resolve pending promise callbacks (ticket fetches) deterministically. */
const flush = () => new Promise<void>((resolve) => queueMicrotask(resolve));

describe("MarketStream split-origin ticket auth", () => {
  it("fetches a ticket, then sends it as the first message once the socket opens", async () => {
    const tickets = ["t-1"];
    const h = createHarness({ getTicket: () => Promise.resolve(tickets.shift() ?? "none") });
    h.stream.start();
    expect(h.sockets).toHaveLength(0); // no socket until the ticket arrives
    await flush();
    expect(h.sockets).toHaveLength(1);
    h.current().open();
    expect(h.current().sent.map((m) => JSON.parse(m) as unknown)).toEqual([{ type: "auth", ticket: "t-1" }]);
    h.current().emit(snapshot());
    expect(h.stream.getState().status).toBe("live");
  });

  it("uses a fresh ticket for every reconnection", async () => {
    let n = 0;
    const h = createHarness({ getTicket: () => Promise.resolve(`t-${++n}`) });
    h.stream.start();
    await flush();
    h.current().open();
    h.current().emit(snapshot());
    h.current().serverClose(1006);
    h.timers.fireNext();
    await flush();
    expect(h.sockets).toHaveLength(2);
    h.current().open();
    expect(JSON.parse(h.current().sent[0] ?? "{}")).toEqual({ type: "auth", ticket: "t-2" });
  });

  it("backs off and retries when the ticket request fails (backend asleep)", async () => {
    let fail = true;
    const h = createHarness({ getTicket: () => (fail ? Promise.reject(new Error("502")) : Promise.resolve("ok")) });
    h.stream.start();
    await flush();
    expect(h.sockets).toHaveLength(0);
    expect(h.stream.getState().status).toBe("reconnecting");
    expect(h.timers.pending()).toHaveLength(1);
    fail = false;
    h.timers.fireNext();
    await flush();
    expect(h.sockets).toHaveLength(1);
  });

  it("ignores a late ticket after stop() and creates no socket", async () => {
    let release: (t: string) => void = () => undefined;
    const h = createHarness({ getTicket: () => new Promise<string>((resolve) => (release = resolve)) });
    h.stream.start();
    h.stream.stop();
    release("late");
    await flush();
    expect(h.sockets).toHaveLength(0);
    expect(h.stream.getState().status).toBe("idle");
  });
});
