import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type ColDef,
  type GetRowIdParams,
  type GridApi,
  type GridReadyEvent,
  type ICellRendererParams,
  type IRowNode,
  type PostSortRowsParams,
  type RowDoubleClickedEvent,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useCallback, useEffect, useMemo, useRef, useState, type SyntheticEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { gridTheme } from "../../components/grid";
import { Button, EmptyState, ErrorNotice, Field, Input, Notice, Select, Spinner, Stat } from "../../components/ui";
import { api, call, errorMessage, type Schemas } from "../../lib/api/client";
import { fmtAge, fmtInt, fmtPrice, fmtTime } from "../../lib/format";
import { useMarketStream, useStream } from "../../lib/stream/context";
import type { Quote } from "../../lib/stream/reducer";
import { useNow } from "../../lib/useNow";

export interface MonitorRow {
  id: string;
  symbol: string;
  name: string;
  bid: string | null;
  ask: string | null;
  mid: string | null;
  spreadBps: string | null;
  volume: number | null;
  receivedTime: string | null;
  receivedMs: number | null;
  stale: boolean;
  incidents: number;
  watched: boolean;
}

function mergeQuote(row: MonitorRow, q: Quote | undefined): MonitorRow {
  if (!q) return row;
  return {
    ...row,
    bid: q.bid,
    ask: q.ask,
    mid: q.mid,
    spreadBps: q.spreadBps,
    volume: q.volume,
    receivedTime: q.receivedTime,
    receivedMs: q.receivedMs,
  };
}

const numericCol: Partial<ColDef<MonitorRow>> = {
  type: "rightAligned",
  cellClass: "font-mono tabular-nums",
  enableCellChangeFlash: true,
  filter: "agNumberColumnFilter",
};

function SymbolCell(p: ICellRendererParams<MonitorRow, string>) {
  if (!p.data) return null;
  return (
    <Link className="font-semibold text-teal-800 underline-offset-2 hover:underline" to={`/instruments/${p.data.id}`}>
      {p.value}
    </Link>
  );
}

type Freshness = "fresh" | "stale" | "none";

function freshnessOf(row: MonitorRow | undefined): Freshness {
  if (!row || row.receivedMs === null) return "none";
  return row.stale ? "stale" : "fresh";
}

/** Renders the column's own value so AG Grid refreshes it whenever freshness changes. */
function FreshnessCell(p: ICellRendererParams<MonitorRow, Freshness>) {
  if (p.value === "none") return <span className="text-slate-400">No quote</span>;
  return p.value === "stale" ? (
    <span className="cell-stale" title="Server marked this quote stale (no quote within the STALE rule threshold)">
      ■ Stale
    </span>
  ) : (
    <span className="text-emerald-700">● Fresh</span>
  );
}

export default function MonitorPage() {
  const stream = useMarketStream();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const search = params.get("q") ?? "";
  const view = params.get("view") ?? "all";
  const staleOnly = params.get("stale") === "1";
  const gridRef = useRef<GridApi<MonitorRow> | null>(null);
  const rowsRef = useRef(new Map<string, MonitorRow>());
  const selectedIndexRef = useRef<number | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const serverOffsetRef = useRef(0);

  const instruments = useQuery({
    queryKey: ["instruments", "catalog"],
    queryFn: () => call(api.GET("/api/v1/instruments", { params: { query: { limit: 1000 } } })),
    refetchInterval: 5000,
  });
  const watchlists = useQuery({
    queryKey: ["watchlists"],
    queryFn: () => call(api.GET("/api/v1/watchlists")),
  });

  // Star target: the watchlist being viewed, else the explicit "adds to" choice, else the first.
  const targetParam = params.get("target");
  const activeWatchlist: Schemas["WatchlistOut"] | undefined = useMemo(() => {
    const lists = watchlists.data ?? [];
    return lists.find((w) => w.id === view) ?? lists.find((w) => w.id === targetParam) ?? lists[0];
  }, [watchlists.data, view, targetParam]);
  const memberIds = useMemo(() => new Set(activeWatchlist?.instrument_ids ?? []), [activeWatchlist]);
  const viewingWatchlist = view !== "all" && activeWatchlist?.id === view;
  const staleOnlyRef = useRef(staleOnly);
  const viewRef = useRef({ viewingWatchlist, memberIds });

  // ---- build/refresh rows from REST (catalog, incident counts, membership) -------------------
  const [initialRows, setInitialRows] = useState<MonitorRow[] | null>(null);
  useEffect(() => {
    if (!instruments.data) return;
    const state = stream.getState();
    const next = new Map<string, MonitorRow>();
    for (const inst of instruments.data.items) {
      const prev = rowsRef.current.get(inst.id);
      const base: MonitorRow = prev ?? {
        id: inst.id,
        symbol: inst.symbol,
        name: inst.name,
        bid: null,
        ask: null,
        mid: null,
        spreadBps: null,
        volume: null,
        receivedTime: null,
        receivedMs: null,
        stale: false,
        incidents: 0,
        watched: false,
      };
      next.set(
        inst.id,
        mergeQuote(
          { ...base, incidents: inst.active_incident_count, watched: memberIds.has(inst.id), stale: state.staleIds.has(inst.id) },
          state.quotes.get(inst.id),
        ),
      );
    }
    const api = gridRef.current;
    if (!api || rowsRef.current.size === 0) {
      rowsRef.current = next;
      setInitialRows([...next.values()]);
    } else {
      const changed = [...next.values()].filter((r) => {
        const old = rowsRef.current.get(r.id);
        return !old || old.incidents !== r.incidents || old.watched !== r.watched;
      });
      rowsRef.current = next;
      if (changed.length) api.applyTransactionAsync({ update: changed });
      api.onFilterChanged();
    }
  }, [instruments.data, memberIds, stream]);

  // ---- live quotes: AG Grid transactions, no React re-render per tick ----------------------
  useEffect(() => {
    const apply = (changed: readonly Quote[]) => {
      const api = gridRef.current;
      const updates: MonitorRow[] = [];
      for (const q of changed) {
        const row = rowsRef.current.get(q.id);
        if (!row) continue;
        const merged = mergeQuote(row, q);
        rowsRef.current.set(q.id, merged);
        updates.push(merged);
      }
      if (api && updates.length) api.applyTransactionAsync({ update: updates });
    };
    const unsubscribeQuotes = stream.onQuotes(apply);
    let lastStale = stream.getState().staleIds;
    const unsubscribeState = stream.subscribe(() => {
      const s = stream.getState();
      serverOffsetRef.current = s.serverOffsetMs;
      if (s.staleIds === lastStale) return;
      lastStale = s.staleIds;
      const updates: MonitorRow[] = [];
      for (const row of rowsRef.current.values()) {
        const stale = s.staleIds.has(row.id);
        if (row.stale !== stale) {
          const next = { ...row, stale };
          rowsRef.current.set(row.id, next);
          updates.push(next);
        }
      }
      if (updates.length) gridRef.current?.applyTransactionAsync({ update: updates });
      if (staleOnlyRef.current) gridRef.current?.onFilterChanged();
    });
    return () => {
      unsubscribeQuotes();
      unsubscribeState();
    };
  }, [stream]);

  // Age column ticks on the server clock estimate.
  useEffect(() => {
    const id = setInterval(() => gridRef.current?.refreshCells({ columns: ["age"], suppressFlash: true }), 1000);
    return () => clearInterval(id);
  }, []);

  // ---- filters (URL is the source of truth) --------------------------------------------------
  useEffect(() => {
    staleOnlyRef.current = staleOnly;
    viewRef.current = { viewingWatchlist, memberIds };
    gridRef.current?.onFilterChanged();
  }, [staleOnly, viewingWatchlist, memberIds]);
  useEffect(() => {
    gridRef.current?.setGridOption("quickFilterText", search);
  }, [search]);

  const setParam = useCallback(
    (key: string, value: string | null) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value === null || value === "") next.delete(key);
          else next.set(key, value);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  // ---- watchlist membership (persisted via REST/PostgreSQL) ---------------------------------
  const toggleMember = useMutation({
    mutationFn: async ({ instrumentId, add }: { instrumentId: string; add: boolean }) => {
      if (!activeWatchlist) throw new Error("Create a watchlist first.");
      const path = { watchlist_id: activeWatchlist.id, instrument_id: instrumentId };
      return add
        ? call(api.POST("/api/v1/watchlists/{watchlist_id}/items/{instrument_id}", { params: { path } }))
        : call(api.DELETE("/api/v1/watchlists/{watchlist_id}/items/{instrument_id}", { params: { path } }));
    },
    onSuccess: (updated) => {
      queryClient.setQueryData<Schemas["WatchlistOut"][]>(["watchlists"], (old) => old?.map((w) => (w.id === updated.id ? updated : w)));
    },
  });

  const WatchCell = useCallback(
    (p: ICellRendererParams<MonitorRow>) => {
      if (!p.data) return null;
      const row = p.data;
      const label = row.watched ? `Remove ${row.symbol} from ${activeWatchlist?.name ?? "watchlist"}` : `Add ${row.symbol} to ${activeWatchlist?.name ?? "watchlist"}`;
      return (
        <button
          type="button"
          aria-pressed={row.watched}
          aria-label={label}
          title={label}
          disabled={!activeWatchlist || toggleMember.isPending}
          onClick={(e) => {
            e.stopPropagation();
            toggleMember.mutate({ instrumentId: row.id, add: !row.watched });
          }}
          className={`text-base leading-none ${row.watched ? "text-amber-500" : "text-slate-300 hover:text-slate-500"}`}
        >
          {row.watched ? "★" : "☆"}
        </button>
      );
    },
    [activeWatchlist, toggleMember],
  );

  const columnDefs = useMemo<ColDef<MonitorRow>[]>(
    () => [
      { colId: "watch", headerName: "", width: 44, cellRenderer: WatchCell, sortable: false, filter: false, resizable: false, headerTooltip: "Watchlist membership" },
      { field: "symbol", headerName: "Symbol", width: 100, cellRenderer: SymbolCell, filter: "agTextColumnFilter", pinned: "left" },
      { field: "name", headerName: "Name", flex: 1, minWidth: 180, filter: "agTextColumnFilter" },
      { field: "bid", headerName: "Bid", width: 110, ...numericCol, valueFormatter: (p) => fmtPrice(p.value as string | null), comparator: numCompare },
      { field: "ask", headerName: "Ask", width: 110, ...numericCol, valueFormatter: (p) => fmtPrice(p.value as string | null), comparator: numCompare },
      { field: "mid", headerName: "Mid", width: 115, ...numericCol, valueFormatter: (p) => fmtPrice(p.value as string | null, 4), comparator: numCompare },
      {
        field: "spreadBps",
        headerName: "Spread (bps)",
        width: 115,
        ...numericCol,
        valueFormatter: (p) => (p.value ? Number(p.value).toFixed(2) : "—"),
        comparator: numCompare,
        cellClassRules: { "text-rose-700 font-semibold": (p) => Number(p.value) > 50 },
      },
      { field: "volume", headerName: "Volume (synthetic)", width: 150, ...numericCol, valueFormatter: (p) => fmtInt(p.value as number | null) },
      { field: "receivedTime", headerName: "Last quote", width: 105, valueFormatter: (p) => fmtTime(p.value as string | null), cellClass: "font-mono tabular-nums" },
      {
        colId: "age",
        headerName: "Age",
        width: 80,
        type: "rightAligned",
        cellClass: "font-mono tabular-nums",
        valueGetter: (p) =>
          p.data?.receivedMs == null ? null : (Date.now() + serverOffsetRef.current - p.data.receivedMs) / 1000,
        valueFormatter: (p) => fmtAge(p.value as number | null),
        headerTooltip: "Seconds since the backend received the last quote (server clock estimate)",
      },
      { colId: "freshness", headerName: "Freshness", width: 105, valueGetter: (p) => freshnessOf(p.data), cellRenderer: FreshnessCell },
      {
        field: "incidents",
        headerName: "Active incidents",
        width: 130,
        type: "rightAligned",
        cellClass: "font-mono tabular-nums",
        cellClassRules: { "text-rose-700 font-semibold": (p) => Number(p.value) > 0 },
      },
    ],
    [WatchCell],
  );

  const defaultColDef = useMemo<ColDef<MonitorRow>>(() => ({ sortable: true, resizable: true, suppressHeaderMenuButton: false }), []);

  const onGridReady = useCallback((e: GridReadyEvent<MonitorRow>) => {
    gridRef.current = e.api;
    e.api.setGridOption("quickFilterText", search);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial quick filter only
  }, []);

  // Keep the user's selected row at its index while live updates re-sort other rows.
  const postSortRows = useCallback((p: PostSortRowsParams<MonitorRow>) => {
    const nodes = p.nodes;
    const idx = nodes.findIndex((n) => n.isSelected());
    const target = selectedIndexRef.current;
    if (idx < 0 || target === null || target === idx || target >= nodes.length) return;
    const [node] = nodes.splice(idx, 1);
    if (node) nodes.splice(target, 0, node);
  }, []);

  const onSelectionChanged = useCallback(() => {
    const api = gridRef.current;
    const node = api?.getSelectedNodes()[0];
    selectedIndexRef.current = node?.rowIndex ?? null;
    setSelectedId(node?.data?.id ?? null);
  }, []);

  const onSortChanged = useCallback(() => {
    // A user-initiated sort change releases the pinned selection position.
    const node = gridRef.current?.getSelectedNodes()[0];
    selectedIndexRef.current = null;
    if (node) requestAnimationFrame(() => (selectedIndexRef.current = node.rowIndex));
  }, []);

  const isExternalFilterPresent = useCallback(() => staleOnlyRef.current || viewRef.current.viewingWatchlist, []);
  const doesExternalFilterPass = useCallback((node: IRowNode<MonitorRow>) => {
    if (!node.data) return false;
    if (staleOnlyRef.current && !node.data.stale) return false;
    if (viewRef.current.viewingWatchlist && !viewRef.current.memberIds.has(node.data.id)) return false;
    return true;
  }, []);

  if (instruments.isError) {
    return <ErrorNotice title="Could not load instruments" message={errorMessage(instruments.error)} onRetry={() => void instruments.refetch()} />;
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Market monitor</h1>
          <p className="text-xs text-slate-500">Synthetic quotes from the local simulator. Click a symbol for charts, events, and rules.</p>
        </div>
        <SummaryStats instrumentsData={instruments.data} />
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2">
        <Field label="Search symbol or name">
          {({ id }) => <Input id={id} type="search" value={search} placeholder="e.g. BAMT" onChange={(e) => setParam("q", e.target.value)} className="w-48" />}
        </Field>
        <Field label="Show">
          {({ id }) => (
            <Select id={id} value={viewingWatchlist ? view : "all"} onChange={(e) => setParam("view", e.target.value === "all" ? null : e.target.value)}>
              <option value="all">All instruments</option>
              {(watchlists.data ?? []).map((w) => (
                <option key={w.id} value={w.id}>
                  Watchlist: {w.name} ({w.instrument_ids.length})
                </option>
              ))}
            </Select>
          )}
        </Field>
        <label className="flex items-center gap-2 pb-1.5 text-sm">
          <input type="checkbox" checked={staleOnly} onChange={(e) => setParam("stale", e.target.checked ? "1" : null)} className="h-4 w-4 accent-teal-700" />
          Stale only
        </label>
        <NewWatchlist onCreated={(id) => setParam("target", id)} />
        <div className="ml-auto flex items-end gap-2">
          <Field label="☆ adds to">
            {({ id }) => (
              <Select id={id} value={activeWatchlist?.id ?? ""} disabled={viewingWatchlist || !watchlists.data?.length} onChange={(e) => setParam("target", e.target.value)}>
                {(watchlists.data ?? []).map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Button disabled={!selectedId} onClick={() => selectedId && void navigate(`/instruments/${selectedId}`)}>
            Open selected
          </Button>
        </div>
      </div>
      {toggleMember.isError ? <Notice tone="bad">Watchlist change failed: {errorMessage(toggleMember.error)}</Notice> : null}

      <div className="h-[70vh] min-h-[420px] overflow-hidden rounded-lg border border-slate-200 bg-white md:h-auto md:flex-1">
        {initialRows === null ? (
          <div className="p-6">
            <Spinner label="Loading instruments…" />
          </div>
        ) : initialRows.length === 0 ? (
          <div className="p-6">
            <EmptyState title="No instruments">Run <code>make seed</code> to create the synthetic catalog.</EmptyState>
          </div>
        ) : (
          <AgGridReact<MonitorRow>
            theme={gridTheme}
            rowData={initialRows}
            columnDefs={columnDefs}
            defaultColDef={defaultColDef}
            getRowId={(p: GetRowIdParams<MonitorRow>) => p.data.id}
            onGridReady={onGridReady}
            rowSelection={{ mode: "singleRow", checkboxes: false, enableClickSelection: true }}
            onSelectionChanged={onSelectionChanged}
            onSortChanged={onSortChanged}
            postSortRows={postSortRows}
            isExternalFilterPresent={isExternalFilterPresent}
            doesExternalFilterPass={doesExternalFilterPass}
            onRowDoubleClicked={(e: RowDoubleClickedEvent<MonitorRow>) => e.data && void navigate(`/instruments/${e.data.id}`)}
            asyncTransactionWaitMillis={100}
            animateRows={false}
            overlayNoRowsTemplate="<span>No instruments match these filters.</span>"
          />
        )}
      </div>
    </div>
  );
}

function numCompare(a: string | null, b: string | null): number {
  return (a === null ? -Infinity : Number(a)) - (b === null ? -Infinity : Number(b));
}

function SummaryStats({ instrumentsData }: { instrumentsData: Schemas["InstrumentList"] | undefined }) {
  const total = useStream((s) => s.quotes.size);
  const stale = useStream((s) => s.staleIds.size);
  const quotesReceived = useStream((s) => s.stats.quotes);
  const now = useNow(1000);
  const samples = useRef<{ t: number; n: number }[]>([]);
  const [rate, setRate] = useState<number | null>(null);
  useEffect(() => {
    const list = samples.current;
    list.push({ t: now, n: quotesReceived });
    while (list.length > 11) list.shift();
    const first = list[0];
    const last = list[list.length - 1];
    if (first && last && last.t > first.t) setRate(((last.n - first.n) * 1000) / (last.t - first.t));
  }, [now, quotesReceived]);
  const activeIncidents = instrumentsData?.items.reduce((acc, i) => acc + i.active_incident_count, 0) ?? 0;
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <Stat label="Fresh instruments" value={total ? fmtInt(total - stale) : "—"} tone="good" />
      <Stat label="Stale instruments" value={total ? fmtInt(stale) : "—"} tone={stale ? "bad" : undefined} />
      <Stat label="Active incidents" value={fmtInt(activeIncidents)} tone={activeIncidents ? "bad" : undefined} />
      <Stat label="Observed quotes/s" value={rate === null ? "—" : rate.toFixed(1)} hint="Quote updates received by this browser over the last ~10 s" />
    </div>
  );
}

function NewWatchlist({ onCreated }: { onCreated: (id: string) => void }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: (n: string) => call(api.POST("/api/v1/watchlists", { body: { name: n } })),
    onSuccess: async (wl) => {
      await queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      setOpen(false);
      setName("");
      onCreated(wl.id);
    },
  });
  if (!open) {
    return (
      <Button variant="ghost" onClick={() => setOpen(true)}>
        + New watchlist
      </Button>
    );
  }
  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    if (name.trim()) create.mutate(name.trim());
  };
  return (
    <form onSubmit={submit} className="flex items-end gap-2">
      <Field label="Watchlist name" error={create.isError ? errorMessage(create.error) : undefined}>
        {({ id, describedBy, invalid }) => (
          <Input id={id} aria-describedby={describedBy} aria-invalid={invalid} value={name} maxLength={80} autoFocus onChange={(e) => setName(e.target.value)} />
        )}
      </Field>
      <Button type="submit" variant="primary" busy={create.isPending} disabled={!name.trim()}>
        Create
      </Button>
      <Button variant="ghost" onClick={() => setOpen(false)}>
        Cancel
      </Button>
    </form>
  );
}

