import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { TimeSeriesChart, type SeriesPoint } from "../../components/TimeSeriesChart";
import { ErrorNotice, Panel, Pill, Spinner, Stat } from "../../components/ui";
import { ApiError, api, call, errorMessage } from "../../lib/api/client";
import { fmtAge, fmtBps, fmtInt, fmtPrice, fmtTime } from "../../lib/format";
import { useStream } from "../../lib/stream/context";
import { quoteAgeSeconds } from "../../lib/stream/reducer";
import { useAuth } from "../../lib/auth";
import { useNow } from "../../lib/useNow";
import { EventsGrid } from "./EventsGrid";
import { RuleEditor } from "./RuleEditor";

const RANGES = ["5m", "15m", "1h"] as const;
type Range = (typeof RANGES)[number];

export default function InstrumentPage() {
  const { instrumentId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const range: Range = (RANGES as readonly string[]).includes(params.get("range") ?? "") ? (params.get("range") as Range) : "15m";
  const { isOperator } = useAuth();

  const detail = useQuery({
    queryKey: ["instrument", instrumentId],
    queryFn: () => call(api.GET("/api/v1/instruments/{instrument_id}", { params: { path: { instrument_id: instrumentId } } })),
    refetchInterval: 5000,
  });
  const history = useQuery({
    queryKey: ["history", instrumentId, range],
    queryFn: () => call(api.GET("/api/v1/instruments/{instrument_id}/history", { params: { path: { instrument_id: instrumentId }, query: { range } } })),
    refetchInterval: 5000,
  });
  const incidents = useQuery({
    queryKey: ["incidents", "instrument", instrumentId],
    queryFn: () => call(api.GET("/api/v1/incidents", { params: { query: { instrument_id: instrumentId, limit: 10 } } })),
    refetchInterval: 5000,
  });

  const points = useMemo<SeriesPoint[]>(
    () =>
      (history.data?.points ?? []).map((p) => ({
        t: new Date(p.t),
        values: { bid: Number(p.bid), ask: Number(p.ask), mid: Number(p.mid), spread: Number(p.spread_bps) },
      })),
    [history.data],
  );
  const xDomain = useMemo<[Date, Date] | undefined>(
    () => (history.data ? [new Date(history.data.start), new Date(history.data.end)] : undefined),
    [history.data],
  );

  if (detail.isError) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <ErrorNotice
        title={notFound ? "Instrument not found" : "Could not load instrument"}
        message={notFound ? "It may have been removed. Return to the market monitor." : errorMessage(detail.error)}
        onRetry={notFound ? undefined : () => void detail.refetch()}
      />
    );
  }
  if (!detail.data) return <Spinner label="Loading instrument…" />;
  const inst = detail.data;
  const spreadRule = inst.rules.find((r) => r.rule_type === "WIDE_SPREAD" && r.enabled);

  return (
    <div className="space-y-4">
      <nav aria-label="Breadcrumb" className="text-xs text-slate-500">
        <Link className="underline" to="/">
          Market monitor
        </Link>{" "}
        / {inst.symbol}
      </nav>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">
            {inst.symbol} <span className="font-normal text-slate-600">{inst.name}</span>
          </h1>
          <p className="text-xs text-slate-500">{inst.asset_label} · fictional instrument · simulated prices</p>
        </div>
        <LiveQuote instrumentId={inst.id} />
      </div>

      <Panel
        title="Price & spread history"
        actions={
          <div role="group" aria-label="History range" className="inline-flex overflow-hidden rounded-md border border-slate-300">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                aria-pressed={r === range}
                onClick={() => setParams((prev) => { const n = new URLSearchParams(prev); n.set("range", r); return n; }, { replace: true })}
                className={`px-3 py-1 text-xs ${r === range ? "bg-teal-700 text-white" : "bg-white hover:bg-slate-50"}`}
              >
                {r}
              </button>
            ))}
          </div>
        }
      >
        {history.isError ? (
          <ErrorNotice title="History unavailable" message={errorMessage(history.error)} onRetry={() => void history.refetch()} />
        ) : (
          <div className="space-y-4">
            <p className="text-xs text-slate-500">
              Persisted samples (at most one per instrument per second), averaged into{" "}
              <strong>{history.data?.resolution_seconds ?? "…"}-second buckets</strong>; refreshed every 5 s. This is sampled history, not a
              tick archive; the live quote above comes from the stream.
            </p>
            <TimeSeriesChart
              title="Mid price"
              unit="synthetic price units"
              points={points}
              xDomain={xDomain}
              series={[{ key: "mid", label: "Mid", color: "#0f766e" }]}
              band={{ lower: "bid", upper: "ask", label: "Bid–ask range", color: "rgba(13,148,136,0.15)" }}
              formatValue={(v) => v.toFixed(2)}
              emptyMessage={history.isPending ? "Loading history…" : "No persisted samples in this range yet (the sampler writes once per second)."}
            />
            <TimeSeriesChart
              title="Spread"
              unit="basis points"
              points={points}
              xDomain={xDomain}
              height={170}
              series={[{ key: "spread", label: "Spread", color: "#7c3aed" }]}
              threshold={spreadRule ? { value: Number(spreadRule.threshold), label: `Rule threshold ${spreadRule.threshold} bps` } : undefined}
              formatValue={(v) => v.toFixed(1)}
              emptyMessage={history.isPending ? "Loading history…" : "No persisted samples in this range yet."}
            />
          </div>
        )}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Alert rules">
          <div className="space-y-3">
            {inst.rules.length === 0 ? <p className="text-sm text-slate-500">No rules configured.</p> : null}
            {inst.rules.map((r) => (
              <RuleEditor key={r.id} rule={r} canEdit={isOperator} />
            ))}
          </div>
        </Panel>
        <Panel title="Incidents for this instrument" actions={<Link className="text-xs text-teal-800 underline" to={`/incidents?symbol=${inst.symbol}`}>All incidents for {inst.symbol}</Link>}>
          {incidents.isError ? (
            <ErrorNotice message={errorMessage(incidents.error)} />
          ) : !incidents.data ? (
            <Spinner label="Loading…" />
          ) : incidents.data.items.length === 0 ? (
            <p className="text-sm text-slate-500">No incidents recorded for {inst.symbol}.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {incidents.data.items.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <Link className="font-medium text-teal-800 underline" to={`/incidents/${i.id}`}>
                    #{i.number} {i.incident_type === "STALE" ? "Stale quotes" : "Wide spread"}
                  </Link>
                  <span className="flex gap-2">
                    <Pill tone={i.status === "RESOLVED" ? "neutral" : i.status === "OPEN" ? "bad" : "warn"}>{i.status}</Pill>
                    {i.status !== "RESOLVED" ? <Pill tone={i.condition_active ? "bad" : "good"}>{i.condition_active ? "Condition active" : "Recovered"}</Pill> : null}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel title="Historical events">
        <EventsGrid instrumentId={inst.id} />
      </Panel>
    </div>
  );
}

function LiveQuote({ instrumentId }: { instrumentId: string }) {
  const quote = useStream((s) => s.quotes.get(instrumentId));
  const stale = useStream((s) => s.staleIds.has(instrumentId));
  const offset = useStream((s) => s.serverOffsetMs);
  const suspect = useStream((s) => s.dataSuspect);
  const now = useNow(1000);
  const age = quoteAgeSeconds(quote, offset, now);
  return (
    <div className="space-y-1">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Stat label="Bid" value={fmtPrice(quote?.bid)} />
        <Stat label="Ask" value={fmtPrice(quote?.ask)} />
        <Stat label="Mid" value={fmtPrice(quote?.mid)} />
        <Stat label="Spread" value={fmtBps(quote?.spreadBps)} tone={quote && Number(quote.spreadBps) > 50 ? "warn" : undefined} />
        <Stat label="Volume (synthetic)" value={fmtInt(quote?.volume)} />
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
        <Pill tone={stale ? "bad" : "good"}>{stale ? "Stale" : "Fresh"}</Pill>
        <span>
          Last quote {fmtTime(quote?.receivedTime)} · age {fmtAge(age)} (backend receipt, server clock)
        </span>
        {suspect ? <Pill tone="warn">Stream resynchronizing — values may be outdated</Pill> : null}
      </div>
    </div>
  );
}
