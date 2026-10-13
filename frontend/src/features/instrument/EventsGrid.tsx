import type { ColDef, GridApi, GridReadyEvent, IDatasource, IGetRowsParams } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { Field, Notice, Select } from "../../components/ui";
import { api, call, errorMessage, type Schemas } from "../../lib/api/client";
import { fmtDateTime } from "../../lib/format";
import { gridTheme } from "../../components/grid";

type EventRow = Schemas["EventOut"];
type SortKey = "observed_at" | "-observed_at" | "event_type" | "-event_type" | "symbol" | "-symbol";

const EVENT_TYPES = [
  "STALE_BREACH",
  "STALE_RECOVERY",
  "SPREAD_BREACH",
  "SPREAD_RECOVERY",
  "SCENARIO_STARTED",
  "SCENARIO_ENDED",
  "FEED_EPOCH_STARTED",
  "SIM_PRICE_JUMP",
  "SIM_VOLUME_SPIKE",
  "SIM_SPREAD_SAMPLE",
  "SIM_QUOTE_GAP",
];

const SORTABLE: Record<string, string> = { observed_at: "observed_at", event_type: "event_type", symbol: "symbol" };

/** Server-backed historical events using AG Grid Community's Infinite Row Model. */
export function EventsGrid({ instrumentId }: { instrumentId?: string }) {
  const [params, setParams] = useSearchParams();
  const eventType = params.get("event") ?? "";
  const gridApi = useRef<GridApi<EventRow> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);

  const datasource = useMemo<IDatasource>(
    () => ({
      getRows: (p: IGetRowsParams) => {
        const sortModel = p.sortModel[0];
        const field = sortModel ? SORTABLE[sortModel.colId] : undefined;
        const sort = (field ? `${sortModel?.sort === "desc" ? "-" : ""}${field}` : "-observed_at") as SortKey;
        call(
          api.GET("/api/v1/events", {
            params: {
              query: {
                offset: p.startRow,
                limit: p.endRow - p.startRow,
                sort,
                ...(instrumentId ? { instrument_id: instrumentId } : {}),
                ...(eventType ? { event_type: eventType } : {}),
              },
            },
          }),
        )
          .then((page) => {
            setError(null);
            setTotal(page.total);
            p.successCallback(page.items, page.total);
          })
          .catch((err: unknown) => {
            setError(errorMessage(err));
            p.failCallback();
          });
      },
    }),
    [instrumentId, eventType],
  );

  useEffect(() => {
    gridApi.current?.setGridOption("datasource", datasource);
  }, [datasource]);

  const columnDefs = useMemo<ColDef<EventRow>[]>(
    () => [
      { field: "observed_at", headerName: "Observed (local)", width: 175, sort: "desc", valueFormatter: (p) => fmtDateTime(p.value as string), cellClass: "font-mono" },
      { field: "event_type", headerName: "Event", width: 180 },
      { field: "symbol", headerName: "Symbol", width: 95 },
      {
        colId: "evidence",
        headerName: "Evidence",
        flex: 1,
        minWidth: 240,
        sortable: false,
        valueGetter: (p) => (p.data ? JSON.stringify(p.data.evidence) : ""),
        cellClass: "font-mono text-[11px] text-slate-600",
        tooltipValueGetter: (p) => (p.data ? JSON.stringify(p.data.evidence, null, 2) : ""),
      },
      { field: "id", headerName: "ID", width: 90, sortable: false, cellClass: "font-mono text-slate-500" },
    ],
    [],
  );

  const onGridReady = useCallback(
    (e: GridReadyEvent<EventRow>) => {
      gridApi.current = e.api;
      e.api.setGridOption("datasource", datasource);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- later datasource changes handled by effect
    [],
  );

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Event type">
          {({ id }) => (
            <Select
              id={id}
              value={eventType}
              onChange={(e) =>
                setParams(
                  (prev) => {
                    const next = new URLSearchParams(prev);
                    if (e.target.value) next.set("event", e.target.value);
                    else next.delete("event");
                    return next;
                  },
                  { replace: true },
                )
              }
            >
              <option value="">All types</option>
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <p className="pb-1.5 text-xs text-slate-500">
          {total === null ? "Loading…" : `${total.toLocaleString()} persisted events`} · loaded in blocks of 100 from PostgreSQL · sort by clicking headers
        </p>
      </div>
      {error ? <Notice tone="bad">Could not load events: {error}</Notice> : null}
      <div className="h-[360px] overflow-hidden rounded-md border border-slate-200">
        <AgGridReact<EventRow>
          theme={gridTheme}
          rowModelType="infinite"
          cacheBlockSize={100}
          maxBlocksInCache={20}
          columnDefs={columnDefs}
          defaultColDef={{ sortable: true, resizable: true }}
          getRowId={(p) => String(p.data.id)}
          onGridReady={onGridReady}
          tooltipShowDelay={400}
        />
      </div>
    </div>
  );
}
