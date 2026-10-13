import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type SyntheticEvent } from "react";
import { ConnectionStatus } from "../../components/ConnectionStatus";
import { Button, ErrorNotice, Field, Input, Notice, Panel, Pill, Select, Spinner, Stat, type Tone } from "../../components/ui";
import { ApiError, api, call, errorMessage, type Schemas } from "../../lib/api/client";
import { useAuth } from "../../lib/auth";
import { fmtDateTime, fmtInt } from "../../lib/format";
import { useStream } from "../../lib/stream/context";
import { useNow } from "../../lib/useNow";

type Component = Schemas["ComponentStatus"];
type ScenarioKind = "STALE_QUOTES" | "WIDE_SPREAD" | "RECOVERY" | "DISCONNECT_STREAM";

const componentTone: Record<string, Tone> = { ok: "good", degraded: "warn", down: "bad", warming_up: "info", disabled: "neutral" };

export default function SystemPage() {
  const { isOperator } = useAuth();
  const status = useQuery({
    queryKey: ["system", "status"],
    queryFn: () => call(api.GET("/api/v1/system/status")),
    refetchInterval: 2000,
    refetchIntervalInBackground: true, // an ops status page should stay current in a background tab
    retry: false,
  });

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">System status</h1>
        <p className="text-xs text-slate-500">
          Transport (your browser's stream connection) and the server's feed, evaluator, and database health are reported separately.
        </p>
      </div>
      <ClientStream />
      {status.isError ? (
        <>
          <ErrorNotice
            title={status.error instanceof ApiError && status.error.status >= 500 ? "Server status unavailable" : "Could not load status"}
            message={`${errorMessage(status.error)} The live stream may still be working; see Client stream above.`}
            onRetry={() => void status.refetch()}
          />
          <ReadinessFallback />
        </>
      ) : !status.data ? (
        <Spinner label="Loading status…" />
      ) : (
        <ServerStatus data={status.data} />
      )}
      {status.data ? <Scenarios data={status.data} canOperate={isOperator} /> : null}
    </div>
  );
}

function ClientStream() {
  const epoch = useStream((s) => s.epoch);
  const seq = useStream((s) => s.seq);
  const stats = useStream((s) => s.stats);
  const lastMessageAt = useStream((s) => s.lastMessageAt);
  const now = useNow(1000);
  return (
    <Panel title="Client stream (this browser)" actions={<ConnectionStatus />}>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
        <Stat label="Epoch" value={epoch ?? "—"} />
        <Stat label="Sequence" value={fmtInt(seq)} />
        <Stat label="Snapshots" value={fmtInt(stats.snapshots)} hint="Each (re)connection starts from a fresh snapshot" />
        <Stat label="Duplicates ignored" value={fmtInt(stats.duplicates)} />
        <Stat label="Gaps / epoch changes" value={`${stats.gaps} / ${stats.epochChanges}`} tone={stats.gaps ? "warn" : undefined} />
        <Stat label="Last message" value={lastMessageAt ? `${Math.max(0, (now - lastMessageAt) / 1000).toFixed(0)}s ago` : "—"} />
      </div>
    </Panel>
  );
}

/** Public readiness probe; still answers when the database (and therefore sign-in) is down. */
function ReadinessFallback() {
  const ready = useQuery({
    queryKey: ["system", "ready"],
    queryFn: async () => {
      const r = await fetch("/api/v1/health/ready", { credentials: "same-origin" });
      return (await r.json()) as Schemas["HealthOut"];
    },
    refetchInterval: 2000,
  });
  if (!ready.data) return null;
  return (
    <Panel title="Readiness checks (public probe)">
      <ul className="grid gap-2 sm:grid-cols-3">
        {Object.entries(ready.data.checks).map(([name, value]) => (
          <li key={name} className="flex items-center justify-between gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm">
            <span className="font-medium capitalize">{name}</span>
            <Pill tone={value === "ok" ? "good" : "bad"}>{value}</Pill>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function ComponentCard({ name, c }: { name: string; c: Component }) {
  return (
    <div className="rounded-md border border-slate-200 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold">{name}</p>
        <Pill tone={componentTone[c.status] ?? "neutral"}>{c.status.replace("_", " ")}</Pill>
      </div>
      <p className="mt-1 text-xs text-slate-600">{c.detail}</p>
      {c.last_error ? (
        <p className="mt-1 text-xs text-rose-700">
          Last error {c.last_error} at {fmtDateTime(c.last_error_at)}
        </p>
      ) : null}
    </div>
  );
}

function ServerStatus({ data }: { data: Schemas["SystemStatus"] }) {
  return (
    <Panel title="Server">
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
          <Stat label="Feed epoch" value={data.epoch} />
          <Stat label="Server seq" value={fmtInt(data.seq)} />
          <Stat label="Instruments" value={fmtInt(data.instruments)} />
          <Stat label="Quotes/s (observed)" value={data.observed_quotes_per_second.toFixed(1)} hint={`Configured ${data.configured_updates_per_second}/s; 10 s window`} />
          <Stat label="Stale instruments" value={fmtInt(data.stale_count)} tone={data.stale_count ? "bad" : "good"} />
          <Stat label="Active incidents" value={fmtInt(data.active_incidents)} tone={data.active_incidents ? "bad" : undefined} />
          <Stat label="Stream connections" value={fmtInt(data.connections)} />
          <Stat label="Overflow disconnects" value={fmtInt(data.overflow_disconnects)} />
        </div>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          <ComponentCard name="Synthetic feed" c={data.simulator} />
          <ComponentCard name="Rule evaluator" c={data.evaluator} />
          <ComponentCard name="Database" c={data.database} />
          <ComponentCard name="Quote persistence" c={data.persistence} />
        </div>
        <p className="text-xs text-slate-500">
          Started {fmtDateTime(data.started_at)} · uptime {Math.round(data.uptime_seconds)}s · single backend worker (in-process feed and stream; see ADR 0002).
        </p>
      </div>
    </Panel>
  );
}

function Scenarios({ data, canOperate }: { data: Schemas["SystemStatus"]; canOperate: boolean }) {
  const queryClient = useQueryClient();
  const instruments = useQuery({
    queryKey: ["instruments", "catalog"],
    queryFn: () => call(api.GET("/api/v1/instruments", { params: { query: { limit: 1000 } } })),
  });
  const [kind, setKind] = useState<ScenarioKind>("STALE_QUOTES");
  const [instrumentId, setInstrumentId] = useState("");
  const [duration, setDuration] = useState("300");
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetText, setResetText] = useState("");
  const needsInstrument = kind === "STALE_QUOTES" || kind === "WIDE_SPREAD";
  const durationNum = Number(duration);
  const durationError = needsInstrument && (!Number.isInteger(durationNum) || durationNum < 10 || durationNum > 900) ? "Duration must be a whole number between 10 and 900 seconds." : undefined;
  const now = useNow(1000);
  const sortedInstruments = useMemo(() => instruments.data?.items ?? [], [instruments.data]);

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["system"] });
  const start = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/v1/demo/scenarios", {
          body: {
            kind,
            instrument_id: instrumentId || null,
            duration_seconds: needsInstrument ? durationNum : null,
          },
        }),
      ),
    onSuccess: refresh,
  });
  const stop = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/v1/demo/scenarios/{scenario_id}", { params: { path: { scenario_id: id } } })),
    onSuccess: refresh,
  });
  const reset = useMutation({
    mutationFn: () => call(api.POST("/api/v1/demo/reset", { body: { confirm: "RESET" } })),
    onSuccess: () => {
      setConfirmReset(false);
      setResetText("");
      refresh();
    },
  });

  function onSubmit(e: SyntheticEvent) {
    e.preventDefault();
    if (needsInstrument && (!instrumentId || durationError)) return;
    start.mutate();
  }

  return (
    <Panel title="Demo scenarios (operator only)">
      <div className="space-y-4">
        <p className="text-xs text-slate-500">
          Scenarios only change this workspace's local simulator. They never contact external market services and expire automatically.
        </p>
        {canOperate ? (
          <form onSubmit={onSubmit} className="space-y-3" aria-label="Start scenario">
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Scenario">
                {({ id }) => (
                  <Select id={id} value={kind} onChange={(e) => setKind(e.target.value as ScenarioKind)}>
                    <option value="STALE_QUOTES">Stale symbol</option>
                    <option value="WIDE_SPREAD">Wide spread</option>
                    <option value="RECOVERY">Normal recovery</option>
                    <option value="DISCONNECT_STREAM">Disconnect my stream</option>
                  </Select>
                )}
              </Field>
              {kind !== "DISCONNECT_STREAM" ? (
                <Field label={kind === "RECOVERY" ? "Instrument (blank = all)" : "Instrument"} error={start.isError && needsInstrument && !instrumentId ? "Choose an instrument." : undefined}>
                  {({ id, describedBy, invalid }) => (
                    <Select id={id} aria-describedby={describedBy} aria-invalid={invalid} value={instrumentId} onChange={(e) => setInstrumentId(e.target.value)}>
                      <option value="">{kind === "RECOVERY" ? "All instruments" : "Choose…"}</option>
                      {sortedInstruments.map((i) => (
                        <option key={i.id} value={i.id}>
                          {i.symbol} — {i.name}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              ) : null}
              {needsInstrument ? (
                <Field label="Expires after (seconds)" error={durationError}>
                  {({ id, describedBy, invalid }) => (
                    <Input id={id} aria-describedby={describedBy} aria-invalid={invalid} inputMode="numeric" value={duration} onChange={(e) => setDuration(e.target.value)} className="w-24" />
                  )}
                </Field>
              ) : null}
              <Button type="submit" variant="primary" busy={start.isPending} disabled={(needsInstrument && !instrumentId) || Boolean(durationError)}>
                Run scenario
              </Button>
            </div>
            <p className="max-w-3xl text-sm text-slate-700">{data.scenario_catalog[kind]}</p>
            {start.isSuccess ? <Notice tone="good">{start.data.message}</Notice> : null}
            {start.isError ? <Notice tone="bad">{errorMessage(start.error)}</Notice> : null}
          </form>
        ) : (
          <Notice tone="info">Viewers can see scenario state but cannot start or stop scenarios.</Notice>
        )}

        <div>
          <h3 className="mb-2 text-sm font-semibold">Active scenarios</h3>
          {data.scenarios.length === 0 ? (
            <p className="text-sm text-slate-500">None. The feed is running normally.</p>
          ) : (
            <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
              {data.scenarios.map((s) => (
                <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                  <span>
                    <Pill tone="warn">{s.kind}</Pill> <strong>{s.symbol}</strong>{" "}
                    <span className="text-xs text-slate-500">expires in {Math.max(0, Math.round((Date.parse(s.expires_at) - now) / 1000))}s</span>
                  </span>
                  {canOperate ? (
                    <Button busy={stop.isPending && stop.variables === s.id} onClick={() => stop.mutate(s.id)}>
                      Stop
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          {stop.isError ? <Notice tone="bad">{errorMessage(stop.error)}</Notice> : null}
        </div>

        {canOperate ? (
          <div className="rounded-md border border-rose-200 bg-rose-50/40 p-3">
            <h3 className="text-sm font-semibold">Reset demo feed</h3>
            <p className="text-xs text-slate-600">
              Stops all scenarios and restarts the seeded price paths in a new stream epoch (connected clients resynchronize). Incidents, comments, and audit history are kept.
            </p>
            {!confirmReset ? (
              <Button variant="danger" className="mt-2" onClick={() => setConfirmReset(true)}>
                Reset demo feed…
              </Button>
            ) : (
              <form
                className="mt-2 flex flex-wrap items-end gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (resetText === "RESET") reset.mutate();
                }}
              >
                <Field label='Type "RESET" to confirm'>
                  {({ id }) => <Input id={id} value={resetText} onChange={(e) => setResetText(e.target.value)} className="w-28" autoFocus />}
                </Field>
                <Button type="submit" variant="danger" busy={reset.isPending} disabled={resetText !== "RESET"}>
                  Confirm reset
                </Button>
                <Button variant="ghost" onClick={() => setConfirmReset(false)}>
                  Cancel
                </Button>
              </form>
            )}
            {reset.isSuccess ? <Notice tone="good">{reset.data.message}</Notice> : null}
            {reset.isError ? <Notice tone="bad">{errorMessage(reset.error)}</Notice> : null}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
