import { useEffect, useState, type ReactNode } from "react";
import { StreamContext } from "./context";
import { MarketStream, defaultStreamUrl } from "./store";

/** Owns one MarketStream for the signed-in session; stops it on unmount/logout. */
export function StreamProvider({ children, stream }: { children: ReactNode; stream?: MarketStream }) {
  const [instance] = useState(() => stream ?? new MarketStream({ url: defaultStreamUrl }));
  useEffect(() => {
    instance.start();
    return () => instance.stop();
  }, [instance]);
  return <StreamContext.Provider value={instance}>{children}</StreamContext.Provider>;
}
