import { createContext, useContext, useSyncExternalStore } from "react";
import type { StreamState } from "./reducer";
import type { MarketStream } from "./store";

export const StreamContext = createContext<MarketStream | null>(null);

export function useMarketStream(): MarketStream {
  const stream = useContext(StreamContext);
  if (!stream) throw new Error("useMarketStream must be used inside <StreamProvider>");
  return stream;
}

/** Subscribe to a slice of stream state. Selectors must return stable values/references. */
export function useStream<T>(selector: (state: StreamState) => T): T {
  const stream = useMarketStream();
  return useSyncExternalStore(stream.subscribe, () => selector(stream.getState()));
}
