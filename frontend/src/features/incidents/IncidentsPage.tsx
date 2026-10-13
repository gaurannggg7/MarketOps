import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { Button, EmptyState, ErrorNotice, Field, Input, Pill, Select, Spinner } from "../../components/ui";
import { api, call, errorMessage } from "../../lib/api/client";
import { fmtDateTime } from "../../lib/format";
import { severityTone, statusTone, typeLabel } from "./status";

const PAGE = 25;
type Status = "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
type Severity = "HIGH" | "MEDIUM" | "LOW";
type IncidentType = "STALE" | "WIDE_SPREAD";

export default function IncidentsPage() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "active";
  const severity = params.get("severity") ?? "";
  const type = params.get("type") ?? "";
  const symbol = params.get("symbol") ?? "";
  const page = Math.max(0, Number(params.get("page") ?? 0) || 0);

  const statuses: Status[] | undefined =
    status === "active" ? ["OPEN", "ACKNOWLEDGED"] : status === "all" ? undefined : [status as Status];

  const list = useQuery({
    queryKey: ["incidents", "list", status, severity, type, symbol, page],
    queryFn: () =>
      call(
        api.GET("/api/v1/incidents", {
          params: {
            query: {
              ...(statuses ? { status: statuses } : {}),
              ...(severity ? { severity: [severity as Severity] } : {}),
              ...(type ? { type: type as IncidentType } : {}),
              ...(symbol.trim() ? { symbol: symbol.trim() } : {}),
              offset: page * PAGE,
              limit: PAGE,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
    refetchInterval: 4000,
  });

  const set = (key: string, value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        if (key !== "page") next.delete("page");
        return next;
      },
      { replace: true },
    );

  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <div className="space-y-3">
      <div>
        <h1 className="text-lg font-semibold">Incidents</h1>
        <p className="text-xs text-slate-500">Opened automatically by server-side rule evaluation. Lifecycle: OPEN → ACKNOWLEDGED → RESOLVED.</p>
      </div>
      <form className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2" onSubmit={(e) => e.preventDefault()} aria-label="Incident filters">
        <Field label="Status">
          {({ id }) => (
            <Select id={id} value={status} onChange={(e) => set("status", e.target.value === "active" ? "" : e.target.value)}>
              <option value="active">Active (open + acknowledged)</option>
              <option value="OPEN">Open</option>
              <option value="ACKNOWLEDGED">Acknowledged</option>
              <option value="RESOLVED">Resolved</option>
              <option value="all">All</option>
            </Select>
          )}
        </Field>
        <Field label="Severity">
          {({ id }) => (
            <Select id={id} value={severity} onChange={(e) => set("severity", e.target.value)}>
              <option value="">Any</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
            </Select>
          )}
        </Field>
        <Field label="Type">
          {({ id }) => (
            <Select id={id} value={type} onChange={(e) => set("type", e.target.value)}>
              <option value="">Any</option>
              <option value="STALE">Stale quotes</option>
              <option value="WIDE_SPREAD">Wide spread</option>
            </Select>
          )}
        </Field>
        <Field label="Symbol">
          {({ id }) => <Input id={id} value={symbol} maxLength={16} placeholder="e.g. BAMT" onChange={(e) => set("symbol", e.target.value.toUpperCase())} className="w-28" />}
        </Field>
      </form>

      {list.isError ? (
        <ErrorNotice title="Could not load incidents" message={errorMessage(list.error)} onRetry={() => void list.refetch()} />
      ) : !list.data ? (
        <Spinner label="Loading incidents…" />
      ) : list.data.items.length === 0 ? (
        <EmptyState title="No incidents match these filters">
          Start a stale-quote scenario on the <Link className="underline" to="/system">System status</Link> page to generate one.
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full min-w-[720px] text-left text-sm">
            <caption className="sr-only">Incidents, newest first</caption>
            <thead className="bg-slate-50 text-xs text-slate-600">
              <tr>
                <th scope="col" className="px-3 py-2">#</th>
                <th scope="col" className="px-3 py-2">Symbol</th>
                <th scope="col" className="px-3 py-2">Type</th>
                <th scope="col" className="px-3 py-2">Severity</th>
                <th scope="col" className="px-3 py-2">Status</th>
                <th scope="col" className="px-3 py-2">Condition</th>
                <th scope="col" className="px-3 py-2">Assignee</th>
                <th scope="col" className="px-3 py-2">Opened</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {list.data.items.map((i) => (
                <tr key={i.id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono">
                    <Link className="font-semibold text-teal-800 underline" to={`/incidents/${i.id}`}>
                      #{i.number}
                    </Link>
                  </td>
                  <td className="px-3 py-2 font-semibold">{i.symbol}</td>
                  <td className="px-3 py-2">{typeLabel[i.incident_type]}</td>
                  <td className="px-3 py-2"><Pill tone={severityTone[i.severity]}>{i.severity}</Pill></td>
                  <td className="px-3 py-2"><Pill tone={statusTone[i.status]}>{i.status}</Pill></td>
                  <td className="px-3 py-2">
                    {i.status === "RESOLVED" ? <span className="text-slate-400">—</span> : <Pill tone={i.condition_active ? "bad" : "good"}>{i.condition_active ? "Active" : "Recovered"}</Pill>}
                  </td>
                  <td className="px-3 py-2">{i.assignee?.display_name ?? <span className="text-slate-400">Unassigned</span>}</td>
                  <td className="px-3 py-2 font-mono text-xs">{fmtDateTime(i.opened_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.data && total > PAGE ? (
        <nav className="flex items-center justify-between text-sm" aria-label="Pagination">
          <span className="text-slate-600">
            Page {page + 1} of {pages} · {total} incidents
          </span>
          <span className="flex gap-2">
            <Button disabled={page === 0} onClick={() => set("page", String(page - 1))}>Previous</Button>
            <Button disabled={page + 1 >= pages} onClick={() => set("page", String(page + 1))}>Next</Button>
          </span>
        </nav>
      ) : null}
    </div>
  );
}
