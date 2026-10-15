import { useState, type SyntheticEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { Button, ErrorNotice, Field, Input, SyntheticBadge } from "../../components/ui";
import { errorMessage } from "../../lib/api/client";
import { useAuth } from "../../lib/auth";
import { WakingScreen } from "../../components/WakingScreen";

export function LoginPage() {
  const { user, login, demoAvailable, demoLogin, loading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (user) return <Navigate to={from} replace />;
  if (loading) return <WakingScreen />;

  async function onDemo() {
    setError(null);
    setBusy(true);
    try {
      await demoLogin(); // the signed-in redirect above then lands on the live monitor
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(e: SyntheticEvent) {
    e.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setBusy(true);
    try {
      await login(email.trim(), password);
      void navigate(from, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-full place-items-center p-4">
      <div className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h1 className="text-xl font-semibold tracking-tight">MarketOps</h1>
            <SyntheticBadge />
          </div>
          <p className="text-sm text-slate-600">
            Market-data monitoring and incident management demo. All prices are simulated; no exchange connectivity.
          </p>
        </div>
        {demoAvailable ? (
          <div className="space-y-2 rounded-md border border-teal-200 bg-teal-50 p-3">
            <p className="text-sm text-slate-700">
              <strong>Recruiter / visitor?</strong> Explore the live, read-only demo: no account needed. An automated operator runs
              a market scenario every few minutes so you can watch incidents open and resolve.
            </p>
            <Button variant="primary" className="w-full" busy={busy} onClick={() => void onDemo()}>
              Explore the live demo (read-only)
            </Button>
          </div>
        ) : null}
        <form className="space-y-3" onSubmit={(e) => void onSubmit(e)} noValidate aria-label="Operator sign-in">
          {demoAvailable ? <p className="text-xs font-medium text-slate-500">Team sign-in</p> : null}
          <Field label="Email">
            {({ id, describedBy }) => (
              <Input id={id} aria-describedby={describedBy} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
            )}
          </Field>
          <Field label="Password">
            {({ id, describedBy }) => (
              <Input
                id={id}
                aria-describedby={describedBy}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            )}
          </Field>
          {error ? <ErrorNotice title="Sign-in failed" message={error} /> : null}
          <Button type="submit" variant="primary" busy={busy} className="w-full">
            Sign in
          </Button>
        </form>
        <p className="text-xs text-slate-500">
          {demoAvailable ? "Operator accounts are private to the project owner." : <>Demo accounts are created locally by <code>make seed</code>; see README.</>}
        </p>
      </div>
    </main>
  );
}
