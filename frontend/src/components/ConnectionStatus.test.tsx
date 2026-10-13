import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StreamContext } from "../lib/stream/context";
import { delta, snapshot } from "../test/fixtures";
import { createHarness } from "../test/streamHarness";
import { ConnectionStatus } from "./ConnectionStatus";

function setup() {
  const h = createHarness();
  render(
    <StreamContext.Provider value={h.stream}>
      <ConnectionStatus />
    </StreamContext.Provider>,
  );
  act(() => {
    h.stream.start();
  });
  return h;
}

describe("ConnectionStatus", () => {
  it("shows connecting before the first snapshot", () => {
    setup();
    expect(screen.getByText("Connecting")).toBeInTheDocument();
  });

  it("keeps the transport pill live while an instrument is stale (freshness is separate)", () => {
    const h = setup();
    act(() => {
      h.current().emit(snapshot({ stale_ids: ["a"] }));
    });
    expect(screen.getByText("Stream live")).toBeInTheDocument();
    expect(h.stream.getState().staleIds.has("a")).toBe(true);
    expect(h.stream.getState().status).toBe("live");
    expect(screen.queryByText(/stale/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reconnect now" })).not.toBeInTheDocument();
  });

  it("shows Reconnecting with a reconnect control after an abnormal close", () => {
    const h = setup();
    act(() => {
      h.current().emit(snapshot());
    });
    act(() => {
      h.current().serverClose(1006);
    });
    expect(screen.getByText(/Reconnecting/)).toBeInTheDocument();
    expect(screen.queryByText("Stream live")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect now" })).toBeInTheDocument();
  });

  it("shows Resynchronizing after a gap and returns to live on a new snapshot", () => {
    const h = setup();
    act(() => {
      h.current().emit(snapshot());
      h.current().emit(delta(20));
    });
    expect(screen.getByText("Resynchronizing")).toBeInTheDocument();
    act(() => {
      h.timers.fireNext();
    });
    act(() => {
      h.current().emit(snapshot({ seq: 20 }));
    });
    expect(screen.getByText("Stream live")).toBeInTheDocument();
  });

  it("shows offline after logout close", () => {
    const h = setup();
    act(() => {
      h.current().serverClose(4002);
    });
    expect(screen.getByText("Stream offline")).toBeInTheDocument();
  });
});
