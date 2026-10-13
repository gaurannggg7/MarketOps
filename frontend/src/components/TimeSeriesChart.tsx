/**
 * D3-computed, React-rendered time-series chart. D3 supplies scales, ticks, line/area paths and
 * bisection; React owns the SVG DOM (no d3-selection mutations).
 */
import { bisector, extent, max, min } from "d3-array";
import { scaleLinear, scaleTime } from "d3-scale";
import { area, line } from "d3-shape";
import { timeFormat } from "d3-time-format";
import { useMemo, useState, type KeyboardEvent } from "react";
import { useElementWidth } from "./useElementWidth";

export interface SeriesPoint {
  t: Date;
  values: Record<string, number>;
}

export interface SeriesDef {
  key: string;
  label: string;
  color: string;
  dashed?: boolean;
}

interface Props {
  title: string;
  unit: string;
  points: SeriesPoint[];
  series: SeriesDef[];
  /** Optional shaded band between two series keys (e.g. bid/ask). */
  band?: { lower: string; upper: string; label: string; color: string };
  /** Optional horizontal threshold line. */
  threshold?: { value: number; label: string };
  height?: number;
  formatValue: (v: number) => string;
  xDomain?: [Date, Date];
  emptyMessage?: string;
}

const M = { top: 12, right: 16, bottom: 26, left: 64 };
const timeFmt = timeFormat("%H:%M:%S");

export function TimeSeriesChart({ title, unit, points, series, band, threshold, height = 220, formatValue, xDomain, emptyMessage }: Props) {
  const { ref, width } = useElementWidth<HTMLDivElement>();
  const [cursor, setCursor] = useState<number | null>(null);
  const innerW = Math.max(10, width - M.left - M.right);
  const innerH = height - M.top - M.bottom;

  const { x, y, paths, bandPath } = useMemo(() => {
    const keys = [...series.map((s) => s.key), ...(band ? [band.lower, band.upper] : [])];
    const allValues = points.flatMap((p) => keys.map((k) => p.values[k]).filter((v): v is number => v !== undefined && Number.isFinite(v)));
    if (threshold) allValues.push(threshold.value);
    let lo = min(allValues) ?? 0;
    let hi = max(allValues) ?? 1;
    if (lo === hi) {
      lo -= Math.abs(lo) * 0.001 || 1;
      hi += Math.abs(hi) * 0.001 || 1;
    }
    const pad = (hi - lo) * 0.08;
    const [t0, t1] = xDomain ?? (extent(points, (p) => p.t) as [Date | undefined, Date | undefined]);
    const xs = scaleTime()
      .domain([t0 ?? new Date(0), t1 ?? new Date(1)])
      .range([0, innerW]);
    const ys = scaleLinear().domain([lo - pad, hi + pad]).range([innerH, 0]).nice();
    const built = series.map((s) => ({
      def: s,
      d:
        line<SeriesPoint>()
          .defined((p) => Number.isFinite(p.values[s.key]))
          .x((p) => xs(p.t))
          .y((p) => ys(p.values[s.key] ?? 0))(points) ?? "",
    }));
    const bp = band
      ? (area<SeriesPoint>()
          .defined((p) => Number.isFinite(p.values[band.lower]) && Number.isFinite(p.values[band.upper]))
          .x((p) => xs(p.t))
          .y0((p) => ys(p.values[band.lower] ?? 0))
          .y1((p) => ys(p.values[band.upper] ?? 0))(points) ?? "")
      : "";
    return { x: xs, y: ys, paths: built, bandPath: bp };
  }, [points, series, band, threshold, innerW, innerH, xDomain]);

  const bisect = useMemo(() => {
    const b = bisector<SeriesPoint, Date>((p) => p.t);
    return (arr: SeriesPoint[], t: Date) => b.center(arr, t);
  }, []);
  const active = cursor !== null ? points[cursor] : undefined;

  function onMove(clientX: number, rect: DOMRect) {
    if (!points.length) return;
    const t = x.invert(clientX - rect.left - M.left);
    setCursor(Math.min(points.length - 1, Math.max(0, bisect(points, t))));
  }

  function onKey(e: KeyboardEvent<SVGSVGElement>) {
    if (!points.length) return;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const step = e.key === "ArrowLeft" ? -1 : 1;
      setCursor((c) => Math.min(points.length - 1, Math.max(0, (c ?? points.length - 1) + step)));
    } else if (e.key === "Escape") {
      setCursor(null);
    }
  }

  const first = points[0];
  const last = points[points.length - 1];
  const summary = first && last ? `${title}: ${points.length} points from ${timeFmt(first.t)} to ${timeFmt(last.t)}.` : `${title}: no data.`;

  return (
    <figure className="space-y-1">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600">
        <span className="font-medium text-slate-800">
          {title} <span className="font-normal text-slate-500">({unit})</span>
        </span>
        <span className="flex flex-wrap items-center gap-3" aria-label="Legend">
          {series.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1">
              <svg width="18" height="6" aria-hidden="true">
                <line x1="0" x2="18" y1="3" y2="3" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? "4 3" : undefined} />
              </svg>
              {s.label}
            </span>
          ))}
          {band ? (
            <span className="inline-flex items-center gap-1">
              <span aria-hidden="true" className="inline-block h-2.5 w-4 rounded-sm" style={{ background: band.color }} />
              {band.label}
            </span>
          ) : null}
          {threshold ? (
            <span className="inline-flex items-center gap-1">
              <svg width="18" height="6" aria-hidden="true">
                <line x1="0" x2="18" y1="3" y2="3" stroke="#be123c" strokeWidth="1.5" strokeDasharray="2 2" />
              </svg>
              {threshold.label}
            </span>
          ) : null}
        </span>
      </figcaption>
      <div ref={ref} className="relative w-full">
        {points.length === 0 ? (
          <div className="grid place-items-center rounded border border-dashed border-slate-300 text-sm text-slate-500" style={{ height }}>
            {emptyMessage ?? "No data for this range yet."}
          </div>
        ) : (
          <svg
            width={width}
            height={height}
            role="img"
            aria-label={summary}
            tabIndex={0}
            onKeyDown={onKey}
            onMouseMove={(e) => onMove(e.clientX, e.currentTarget.getBoundingClientRect())}
            onMouseLeave={() => setCursor(null)}
            onBlur={() => setCursor(null)}
            className="rounded focus-visible:outline-2 focus-visible:outline-teal-600"
          >
            <g transform={`translate(${M.left},${M.top})`}>
              {y.ticks(5).map((v) => (
                <g key={v} transform={`translate(0,${y(v)})`}>
                  <line x2={innerW} stroke="#e2e8f0" />
                  <text x={-8} dy="0.32em" textAnchor="end" className="fill-slate-500 font-mono text-[10px]">
                    {formatValue(v)}
                  </text>
                </g>
              ))}
              {x.ticks(Math.max(2, Math.floor(innerW / 110))).map((t) => (
                <g key={t.getTime()} transform={`translate(${x(t)},${innerH})`}>
                  <line y2={4} stroke="#94a3b8" />
                  <text y={16} textAnchor="middle" className="fill-slate-500 font-mono text-[10px]">
                    {timeFmt(t)}
                  </text>
                </g>
              ))}
              <line y1={innerH} y2={innerH} x2={innerW} stroke="#94a3b8" />
              {bandPath && band ? <path d={bandPath} fill={band.color} stroke="none" /> : null}
              {threshold ? (
                <line x1={0} x2={innerW} y1={y(threshold.value)} y2={y(threshold.value)} stroke="#be123c" strokeWidth={1.5} strokeDasharray="2 2" />
              ) : null}
              {paths.map(({ def, d }) => (
                <path key={def.key} d={d} fill="none" stroke={def.color} strokeWidth={1.6} strokeDasharray={def.dashed ? "4 3" : undefined} />
              ))}
              {active ? (
                <g>
                  <line x1={x(active.t)} x2={x(active.t)} y1={0} y2={innerH} stroke="#475569" strokeDasharray="3 3" />
                  {series.map((s) => {
                    const v = active.values[s.key];
                    return v !== undefined && Number.isFinite(v) ? <circle key={s.key} cx={x(active.t)} cy={y(v)} r={3} fill={s.color} /> : null;
                  })}
                </g>
              ) : null}
            </g>
          </svg>
        )}
        {active ? (
          <div
            role="status"
            className="pointer-events-none absolute top-1 rounded border border-slate-300 bg-white/95 px-2 py-1 text-xs shadow"
            style={{ left: Math.min(Math.max(M.left + x(active.t) + 10, 0), Math.max(0, width - 190)) }}
          >
            <div className="font-mono text-slate-500">{timeFmt(active.t)} (local)</div>
            {[...series.map((s) => ({ key: s.key, label: s.label })), ...(band ? [{ key: band.upper, label: "Ask" }, { key: band.lower, label: "Bid" }] : [])].map((s) => {
              const v = active.values[s.key];
              return v !== undefined && Number.isFinite(v) ? (
                <div key={s.key} className="flex justify-between gap-3 font-mono">
                  <span className="text-slate-600">{s.label}</span>
                  <span>{formatValue(v)}</span>
                </div>
              ) : null;
            })}
          </div>
        ) : null}
      </div>
    </figure>
  );
}
