/**
 * Regression test for the deployed Vercel config: the CSP must allow the WebSocket to reach the
 * same Render host that /api is rewritten to (they drifted once: rewrite updated, CSP not), and
 * must not be loosened with wildcards or extra origins.
 */
import { describe, expect, it } from "vitest";
import vercel from "../../vercel.json";

interface Rewrite {
  source: string;
  destination: string;
}
interface HeaderRule {
  source: string;
  headers: { key: string; value: string }[];
}

const rewrites = vercel.rewrites as Rewrite[];
const headerRules = vercel.headers as HeaderRule[];

function apiBackendHost(): string {
  const rule = rewrites.find((r) => r.source === "/api/:path*");
  if (!rule) throw new Error("missing /api rewrite");
  const url = new URL(rule.destination.replace("/:path*", "/"));
  expect(url.protocol).toBe("https:");
  return url.host;
}

function cspDirectives(): Map<string, string[]> {
  const csp = headerRules
    .find((h) => h.source === "/(.*)")
    ?.headers.find((h) => h.key === "Content-Security-Policy")?.value;
  if (!csp) throw new Error("missing Content-Security-Policy");
  return new Map(
    csp
      .split(";")
      .map((d) => d.trim().split(/\s+/))
      .filter((parts) => parts[0])
      .map(([name = "", ...values]) => [name, values]),
  );
}

describe("vercel.json security policy", () => {
  it("lets the stream connect to the same backend host the API is proxied to", () => {
    const host = apiBackendHost();
    expect(host).toMatch(/\.onrender\.com$/);
    expect(cspDirectives().get("connect-src")).toEqual(["'self'", `wss://${host}`]);
  });

  it("keeps the rest of the policy strict", () => {
    const csp = cspDirectives();
    expect(csp.get("default-src")).toEqual(["'self'"]);
    expect(csp.get("img-src")).toEqual(["'self'", "data:"]);
    expect(csp.get("frame-ancestors")).toEqual(["'none'"]);
    for (const [directive, values] of csp) {
      expect(values.some((v) => v.includes("*")), `${directive} must not use wildcards`).toBe(false);
      expect(values, `${directive} must not allow unsafe-eval`).not.toContain("'unsafe-eval'");
    }
    expect(csp.get("script-src")).toBeUndefined(); // falls back to default-src 'self'
  });
});
