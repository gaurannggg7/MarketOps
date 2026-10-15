import { useEffect, useState, type ReactNode } from "react";
import { StreamContext } from "./context";
import { api, call } from "../api/client";
import { MarketStream, configuredStreamUrl, defaultStreamUrl } from "./store";

/** Cross-origin stream host: authenticate each socket with a single-use ticket (ADR 0006). */
async function fetchStreamTicket(): Promise<string> {
  const { ticket } = await call(api.POST("/api/v1/stream/ticket"));
  return ticket;
}

/** Owns one MarketStream for the signed-in session; stops it on unmount/logout. */
export function StreamProvider({ children, stream }: { children: ReactNode; stream?: MarketStream }) {
  const [instance] = useState(
    () =>
      stream ??
      new MarketStream({ url: defaultStreamUrl, ...(configuredStreamUrl ? { getTicket: fetchStreamTicket } : {}) }),
  );
  useEffect(() => {
    instance.start();
    return () => instance.stop();
  }, [instance]);
  return <StreamContext.Provider value={instance}>{children}</StreamContext.Provider>;
}
