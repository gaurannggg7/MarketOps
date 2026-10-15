import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";
import { ErrorNotice, Spinner } from "../components/ui";
import { WakingScreen } from "../components/WakingScreen";
import { ApiError, errorMessage } from "../lib/api/client";
import { LoginPage } from "../features/auth/LoginPage";
import { useAuth } from "../lib/auth";
import { StreamProvider } from "../lib/stream/StreamProvider";
import { Layout } from "./Layout";

const MonitorPage = lazy(() => import("../features/monitor/MonitorPage"));
const InstrumentPage = lazy(() => import("../features/instrument/InstrumentPage"));
const IncidentsPage = lazy(() => import("../features/incidents/IncidentsPage"));
const IncidentDetailPage = lazy(() => import("../features/incidents/IncidentDetailPage"));
const SystemPage = lazy(() => import("../features/system/SystemPage"));
const GuidePage = lazy(() => import("../features/guide/GuidePage"));

function Authenticated() {
  const { user, loading, error, retry } = useAuth();
  const location = useLocation();
  if (loading) return <WakingScreen />;
  if (error && !user) {
    return (
      <div className="mx-auto mt-16 max-w-lg p-4">
        <ErrorNotice
          title={error instanceof ApiError && error.code === "PERSISTENCE_UNAVAILABLE" ? "Database unavailable" : "Cannot reach MarketOps"}
          message={`${errorMessage(error)} Your session was not checked; retry once the server is available.`} onRetry={retry} />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  // The stream lives exactly as long as the authenticated session view (keyed by user).
  return (
    <StreamProvider key={user.id}>
      <Layout />
    </StreamProvider>
  );
}

function PageFallback() {
  return <Spinner label="Loading…" />;
}

export function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<Authenticated />}>
          <Route index element={<MonitorPage />} />
          <Route path="instruments/:instrumentId" element={<InstrumentPage />} />
          <Route path="incidents" element={<IncidentsPage />} />
          <Route path="incidents/:incidentId" element={<IncidentDetailPage />} />
          <Route path="system" element={<SystemPage />} />
          <Route path="guide" element={<GuidePage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

function NotFound() {
  return (
    <div className="space-y-2">
      <h1 className="text-lg font-semibold">Page not found</h1>
      <a className="text-teal-700 underline" href="/">
        Back to the market monitor
      </a>
    </div>
  );
}
