import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router";
import { ConnectionStatus } from "../components/ConnectionStatus";
import { Button, Pill, SyntheticBadge } from "../components/ui";
import { api, call } from "../lib/api/client";
import { useAuth } from "../lib/auth";
import { useStream } from "../lib/stream/context";

const nav = [
  { to: "/", label: "Market monitor", end: true },
  { to: "/incidents", label: "Incidents", end: false },
  { to: "/system", label: "System status", end: false },
  { to: "/guide", label: "How to explore", end: false },
];

function OpenIncidentCount() {
  const q = useQuery({
    queryKey: ["incidents", "active-count"],
    queryFn: () => call(api.GET("/api/v1/incidents", { params: { query: { status: ["OPEN", "ACKNOWLEDGED"], limit: 1 } } })),
    refetchInterval: 5000,
  });
  const n = q.data?.total ?? 0;
  if (!n) return null;
  return (
    <span className="ml-auto rounded-full bg-rose-700 px-1.5 text-xs font-semibold text-white" aria-label={`${n} active incidents`}>
      {n}
    </span>
  );
}

function FreshnessSummary() {
  const total = useStream((s) => s.quotes.size);
  const stale = useStream((s) => s.staleIds.size);
  const suspect = useStream((s) => s.dataSuspect);
  if (!total) return null;
  return (
    <span className="hidden items-center gap-2 text-xs text-slate-600 md:inline-flex">
      <Pill tone={stale ? "bad" : "good"} title="Quote freshness is computed by the server from backend receipt time">
        {stale ? `${stale} stale` : "All quotes fresh"}
      </Pill>
      {suspect ? <Pill tone="warn">Display may be outdated</Pill> : null}
    </span>
  );
}

export function Layout() {
  const { user, logout, publicDemo } = useAuth();
  return (
    <div className="flex min-h-full flex-col md:flex-row">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <nav aria-label="Primary" className="flex shrink-0 flex-row items-center gap-1 overflow-x-auto border-b border-slate-800 bg-slate-900 px-2 py-2 text-slate-200 md:w-52 md:flex-col md:items-stretch md:border-b-0 md:border-r md:px-3 md:py-4">
        <div className="mr-3 flex items-center gap-2 px-2 md:mb-4 md:mr-0">
          <span aria-hidden="true" className="h-5 w-5 rounded bg-teal-600" />
          <span className="font-semibold tracking-tight text-white">MarketOps</span>
        </div>
        {nav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `flex items-center gap-2 whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm ${isActive ? "bg-slate-700 text-white" : "hover:bg-slate-800"}`
            }
          >
            {item.label}
            {item.to === "/incidents" ? <OpenIncidentCount /> : null}
          </NavLink>
        ))}
        <p className="mt-auto hidden px-2 text-[11px] leading-snug text-slate-400 md:block">
          Independent demo. Simulated prices; no exchange connectivity or affiliation.
        </p>
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-slate-200 bg-white px-4 py-2">
          <SyntheticBadge />
          <ConnectionStatus />
          <FreshnessSummary />
          <div className="ml-auto flex items-center gap-2 text-sm">
            {user ? (
              <>
                {publicDemo ? null : <span className="hidden text-slate-600 sm:inline">{user.display_name}</span>}
                <Pill tone={user.role === "OPERATOR" && !publicDemo ? "info" : "neutral"}>
                  {publicDemo ? "Public demo (read-only)" : user.role === "OPERATOR" ? "Operator" : "Viewer (read-only)"}
                </Pill>
                <Button variant="ghost" onClick={() => void logout()}>
                  {publicDemo ? "Exit demo" : "Sign out"}
                </Button>
              </>
            ) : null}
          </div>
        </header>
        {publicDemo ? (
          <div role="note" className="border-b border-teal-200 bg-teal-50 px-4 py-1.5 text-xs text-teal-900">
            Read-only public demo of a <strong>simulated</strong> market-operations console — synthetic prices, no exchange data.
            An automated operator runs a market scenario every few minutes.{" "}
            <NavLink to="/guide" className="font-medium underline">
              How to explore
            </NavLink>
          </div>
        ) : null}
        <main id="main" className="min-w-0 flex-1 p-3 md:p-5">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
