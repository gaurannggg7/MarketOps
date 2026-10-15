import { useState } from "react";
import { useNow } from "../lib/useNow";
import { Spinner } from "./ui";

/** Shown while the session probe is pending; explains free-tier cold starts after a few seconds. */
export function WakingScreen() {
  const [started] = useState(() => Date.now());
  const now = useNow(1000);
  const seconds = Math.round((now - started) / 1000);
  return (
    <div className="grid h-full place-items-center p-4">
      <div className="max-w-md space-y-2 text-center">
        <Spinner label={seconds < 4 ? "Checking session…" : `Waking up the demo backend… ${seconds}s`} />
        {seconds >= 4 ? (
          <p className="text-sm text-slate-600">
            This demo runs on free hosting that sleeps after 15 minutes without visitors. The first request after a nap takes
            about a minute while the server and database start; the page continues automatically.
          </p>
        ) : null}
      </div>
    </div>
  );
}

