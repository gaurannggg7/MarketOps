import { useMarketStream, useStream } from "../lib/stream/context";
import type { TransportStatus } from "../lib/stream/reducer";
import { useNow } from "../lib/useNow";
import { Button, Pill, type Tone } from "./ui";

const LABELS: Record<TransportStatus, [string, Tone]> = {
  idle: ["Stream idle", "neutral"],
  connecting: ["Connecting", "info"],
  live: ["Stream live", "good"],
  resyncing: ["Resynchronizing", "warn"],
  reconnecting: ["Reconnecting", "warn"],
  offline: ["Stream offline", "bad"],
};

/** Transport health only. Quote freshness is reported separately (stale counts / cells). */
export function ConnectionStatus({ compact = false }: { compact?: boolean }) {
  const stream = useMarketStream();
  const status = useStream((s) => s.status);
  const reason = useStream((s) => s.resyncReason);
  const now = useNow(500);
  const [label, tone] = LABELS[status];
  const retryIn = stream.nextRetryAt && status !== "live" ? Math.max(0, Math.ceil((stream.nextRetryAt - now) / 1000)) : null;
  return (
    <span className="inline-flex items-center gap-2" aria-live="polite">
      <Pill tone={tone} title={reason ? `Last resync reason: ${reason}` : undefined}>
        {label}
        {retryIn !== null && status === "reconnecting" ? ` in ${retryIn}s` : ""}
      </Pill>
      {!compact && (status === "reconnecting" || status === "offline") ? (
        <Button variant="ghost" className="px-2 py-0.5 text-xs" onClick={() => (stream.isRunning ? stream.resyncNow() : stream.start())}>
          Reconnect now
        </Button>
      ) : null}
    </span>
  );
}
