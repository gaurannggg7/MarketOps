import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SyntheticEvent } from "react";
import { Link, useParams } from "react-router";
import { Button, ErrorNotice, Field, Notice, Panel, Pill, Select, Spinner, TextArea } from "../../components/ui";
import { ApiError, api, call, errorMessage, type Schemas } from "../../lib/api/client";
import { useAuth } from "../../lib/auth";
import { fmtDateTime, humanize } from "../../lib/format";
import { severityTone, statusTone, typeLabel } from "./status";

type Incident = Schemas["IncidentDetail"];

export default function IncidentDetailPage() {
  const { incidentId = "" } = useParams();
  const detail = useQuery({
    queryKey: ["incident", incidentId],
    queryFn: () => call(api.GET("/api/v1/incidents/{incident_id}", { params: { path: { incident_id: incidentId } } })),
    refetchInterval: 3000,
  });
  const timeline = useQuery({
    queryKey: ["incident", incidentId, "timeline"],
    queryFn: () => call(api.GET("/api/v1/incidents/{incident_id}/timeline", { params: { path: { incident_id: incidentId } } })),
    refetchInterval: 3000,
  });

  if (detail.isError) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return <ErrorNotice title={notFound ? "Incident not found" : "Could not load incident"} message={errorMessage(detail.error)} onRetry={() => void detail.refetch()} />;
  }
  if (!detail.data) return <Spinner label="Loading incident…" />;
  const inc = detail.data;

  return (
    <div className="space-y-4">
      <nav aria-label="Breadcrumb" className="text-xs text-slate-500">
        <Link className="underline" to="/incidents">
          Incidents
        </Link>{" "}
        / #{inc.number}
      </nav>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">
            #{inc.number} · {typeLabel[inc.incident_type]} ·{" "}
            <Link className="text-teal-800 underline" to={`/instruments/${inc.instrument_id}`}>
              {inc.symbol}
            </Link>
          </h1>
          <p className="text-sm text-slate-700">{inc.trigger_reason}</p>
        </div>
        <div className="flex flex-wrap gap-2" aria-label="Incident state">
          <Pill tone={statusTone[inc.status]}>Status: {inc.status}</Pill>
          <Pill tone={severityTone[inc.severity]}>Severity: {inc.severity}</Pill>
          {inc.status !== "RESOLVED" ? (
            <Pill tone={inc.condition_active ? "bad" : "good"}>{inc.condition_active ? "Condition active" : "Condition recovered"}</Pill>
          ) : null}
        </div>
      </header>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
        <div className="space-y-4">
          <Panel title="Summary">
            <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              <Item label="Opened">{fmtDateTime(inc.opened_at)}</Item>
              <Item label="Rule">
                {inc.rule.rule_type} &gt; {inc.rule.threshold} {inc.rule.unit === "SECONDS" ? "s" : "bps"} (triggered on v{inc.rule_version}; current v{inc.rule.version}
                {inc.rule.enabled ? "" : ", disabled"})
              </Item>
              <Item label="Assignee">{inc.assignee?.display_name ?? "Unassigned"}</Item>
              <Item label="Breaches in this incident">{inc.breach_count}</Item>
              <Item label="Acknowledged">{inc.acknowledged_at ? `${fmtDateTime(inc.acknowledged_at)} by ${inc.acknowledged_by?.display_name ?? "?"}` : "—"}</Item>
              <Item label="Condition last changed">{fmtDateTime(inc.condition_changed_at)}</Item>
              <Item label="Resolved">{inc.resolved_at ? `${fmtDateTime(inc.resolved_at)} by ${inc.resolved_by?.display_name ?? "?"}` : "—"}</Item>
              <Item label="Record version">v{inc.version}</Item>
            </dl>
            {inc.resolution_note ? (
              <div className="mt-3 rounded-md bg-slate-50 p-3 text-sm">
                <p className="text-xs font-medium text-slate-500">Resolution note</p>
                <p className="whitespace-pre-wrap">{inc.resolution_note}</p>
              </div>
            ) : null}
          </Panel>
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Trigger evidence (snapshot at breach)">
              <Evidence data={inc.trigger_evidence} />
            </Panel>
            <Panel title="Latest condition evidence">
              <Evidence data={inc.latest_evidence} />
            </Panel>
          </div>
          <Panel title="Timeline">
            {timeline.isError ? (
              <ErrorNotice message={errorMessage(timeline.error)} />
            ) : !timeline.data ? (
              <Spinner label="Loading timeline…" />
            ) : (
              <ol className="relative space-y-3 border-l border-slate-200 pl-4">
                {timeline.data.entries.map((e) => (
                  <li key={`${e.kind}-${e.id}`} className="text-sm">
                    <span aria-hidden="true" className={`absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ${e.kind === "COMMENT" ? "bg-sky-500" : e.actor_kind === "SYSTEM" ? "bg-slate-400" : "bg-teal-600"}`} />
                    <p className="flex flex-wrap items-baseline gap-x-2">
                      <span className="font-medium">{e.kind === "COMMENT" ? "Comment" : humanize(e.action)}</span>
                      <span className="text-xs text-slate-500">
                        {fmtDateTime(e.at)} · {e.actor?.display_name ?? "System"}
                      </span>
                    </p>
                    {e.body ? <p className="mt-0.5 whitespace-pre-wrap rounded bg-sky-50 px-2 py-1">{e.body}</p> : null}
                    {e.kind === "AUDIT" && e.after ? <AuditDetail action={e.action} after={e.after} /> : null}
                  </li>
                ))}
              </ol>
            )}
          </Panel>
        </div>
        <IncidentActions incident={inc} />
      </div>
    </div>
  );
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Evidence({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data);
  if (!entries.length) return <p className="text-sm text-slate-500">No evidence recorded.</p>;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{humanize(k)}</dt>
          <dd className="break-all font-mono">{typeof v === "string" && /^\d{4}-\d\d-\d\dT/.test(v) ? fmtDateTime(v) : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function AuditDetail({ action, after }: { action: string; after: Record<string, unknown> }) {
  if (action === "INCIDENT_RESOLVED" && typeof after.resolution_note === "string") {
    return <p className="mt-0.5 text-xs text-slate-600">Note: {after.resolution_note}</p>;
  }
  if (action.startsWith("CONDITION_")) {
    const age = after.age_seconds;
    const spread = after.spread_bps;
    const detail = typeof age === "number" ? `age ${age}s` : typeof spread === "string" ? `spread ${spread} bps` : null;
    return detail ? <p className="mt-0.5 text-xs text-slate-600">{detail}</p> : null;
  }
  return null;
}

function useIncidentMutation<TVars>(incident: Incident, fn: (vars: TVars) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["incident", incident.id] });
      await queryClient.invalidateQueries({ queryKey: ["incidents"] });
    },
  });
}

function ActionError({ error, onReload }: { error: unknown; onReload: () => void }) {
  if (!error) return null;
  if (error instanceof ApiError && error.code === "VERSION_CONFLICT") {
    return (
      <Notice tone="warn">
        <p className="font-semibold">This incident changed while you were viewing it.</p>
        <p>{error.message}</p>
        <Button className="mt-2" onClick={onReload}>
          Reload incident
        </Button>
      </Notice>
    );
  }
  return <Notice tone="bad">{errorMessage(error)}</Notice>;
}

export function IncidentActions({ incident }: { incident: Incident }) {
  const { isOperator } = useAuth();
  const queryClient = useQueryClient();
  const reload = () => void queryClient.invalidateQueries({ queryKey: ["incident", incident.id] });
  const path = { incident_id: incident.id };
  const [comment, setComment] = useState("");
  const [note, setNote] = useState("");
  const [noteTouched, setNoteTouched] = useState(false);
  const [assignee, setAssignee] = useState<string>(incident.assignee?.id ?? "");

  const operators = useQuery({
    queryKey: ["operators"],
    queryFn: () => call(api.GET("/api/v1/auth/operators")),
    enabled: isOperator,
    staleTime: 60_000,
  });

  const ack = useIncidentMutation(incident, () => call(api.POST("/api/v1/incidents/{incident_id}/acknowledge", { params: { path }, body: { version: incident.version } })));
  const assign = useIncidentMutation(incident, (id: string) =>
    call(api.PATCH("/api/v1/incidents/{incident_id}/assignment", { params: { path }, body: { version: incident.version, assignee_id: id || null } })),
  );
  const addComment = useIncidentMutation(incident, (body: string) => call(api.POST("/api/v1/incidents/{incident_id}/comments", { params: { path }, body: { body } })));
  const resolve = useIncidentMutation(incident, (resolution_note: string) =>
    call(api.POST("/api/v1/incidents/{incident_id}/resolve", { params: { path }, body: { version: incident.version, resolution_note } })),
  );

  if (!isOperator) {
    return (
      <Panel title="Actions">
        <p className="text-sm text-slate-600">You are signed in as a viewer (read-only). Operators can acknowledge, assign, comment on, and resolve incidents.</p>
      </Panel>
    );
  }

  const resolved = incident.status === "RESOLVED";
  const resolveBlocker =
    incident.status === "OPEN"
      ? "Acknowledge the incident before resolving it."
      : incident.condition_active
        ? "The market condition is still active. Resolve after the feed recovers (e.g. run the recovery scenario)."
        : null;
  const noteError = noteTouched && !note.trim() ? "Describe the resolution before resolving." : undefined;

  function submitComment(e: SyntheticEvent) {
    e.preventDefault();
    if (!comment.trim()) return;
    addComment.mutate(comment.trim(), { onSuccess: () => setComment("") });
  }

  function submitResolve(e: SyntheticEvent) {
    e.preventDefault();
    setNoteTouched(true);
    if (!note.trim() || resolveBlocker) return;
    resolve.mutate(note.trim());
  }

  return (
    <div className="space-y-4">
      <Panel title="Lifecycle">
        <ol className="mb-3 flex items-center gap-2 text-xs" aria-label="Lifecycle progress">
          {(["OPEN", "ACKNOWLEDGED", "RESOLVED"] as const).map((s, idx) => (
            <li key={s} className="flex items-center gap-2">
              {idx > 0 ? <span aria-hidden="true">→</span> : null}
              <span className={incident.status === s ? "font-semibold text-slate-900" : "text-slate-400"} aria-current={incident.status === s ? "step" : undefined}>
                {s}
              </span>
            </li>
          ))}
        </ol>
        <div className="space-y-3">
          <Button variant="primary" disabled={incident.status !== "OPEN"} busy={ack.isPending} onClick={() => ack.mutate(undefined)}>
            Acknowledge
          </Button>
          {incident.status !== "OPEN" && !resolved ? <p className="text-xs text-slate-500">Acknowledged; continue below.</p> : null}
          <ActionError error={ack.error} onReload={reload} />
        </div>
      </Panel>

      {!resolved ? (
        <Panel title="Assignment">
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              assign.mutate(assignee);
            }}
          >
            <Field label="Assign to operator">
              {({ id }) => (
                <Select id={id} value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                  <option value="">Unassigned</option>
                  {(operators.data ?? []).map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.display_name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Button type="submit" busy={assign.isPending} disabled={assignee === (incident.assignee?.id ?? "")}>
              Save assignment
            </Button>
          </form>
          <div className="mt-2">
            <ActionError error={assign.error} onReload={reload} />
          </div>
        </Panel>
      ) : null}

      <Panel title="Add comment">
        <form className="space-y-2" onSubmit={submitComment}>
          <Field label="Comment" hint="Visible to everyone in the incident timeline.">
            {({ id, describedBy }) => <TextArea id={id} aria-describedby={describedBy} rows={3} maxLength={4000} value={comment} onChange={(e) => setComment(e.target.value)} />}
          </Field>
          <Button type="submit" busy={addComment.isPending} disabled={!comment.trim()}>
            Post comment
          </Button>
          <ActionError error={addComment.error} onReload={reload} />
        </form>
      </Panel>

      {!resolved ? (
        <Panel title="Resolve">
          <form className="space-y-2" onSubmit={submitResolve} noValidate>
            {resolveBlocker ? <Notice tone="info">{resolveBlocker}</Notice> : null}
            <Field label="Resolution note (required)" error={noteError}>
              {({ id, describedBy, invalid }) => (
                <TextArea
                  id={id}
                  aria-describedby={describedBy}
                  aria-invalid={invalid}
                  rows={3}
                  maxLength={4000}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  onBlur={() => setNoteTouched(true)}
                />
              )}
            </Field>
            <Button type="submit" variant="primary" busy={resolve.isPending} disabled={Boolean(resolveBlocker)}>
              Resolve incident
            </Button>
            <ActionError error={resolve.error} onReload={reload} />
          </form>
        </Panel>
      ) : (
        <Notice tone="good">Resolved. A later breach of this rule will open a new incident.</Notice>
      )}
    </div>
  );
}
