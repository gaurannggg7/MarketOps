/**
 * Network stub for component tests. openapi-fetch captures `globalThis.fetch` when the API client
 * module is first evaluated, so this module must be imported BEFORE anything that imports
 * `lib/api/client` (keep it the first import in a test file). It installs a stable delegating
 * fetch; each test then configures behaviour through `routes()`.
 */
import { vi } from "vitest";

type Handler = (req: { method: string; path: string; request: Request }) => Response | Promise<Response>;

export const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

globalThis.fetch = (input: RequestInfo | URL) => fetchMock(input as Request);

export function routes(handler: Handler): void {
  fetchMock.mockImplementation(async (request) => {
    const url = new URL(request.url);
    return handler({ method: request.method, path: url.pathname, request });
  });
}

export function resetNetwork(): void {
  fetchMock.mockReset();
  routes(({ method, path }) => new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: `unexpected ${method} ${path}`, details: null, request_id: null } }), { status: 404, headers: { "content-type": "application/json" } }));
}

/** Requests made so far that mutate state (anything but GET). */
export function mutations(): { method: string; path: string }[] {
  return fetchMock.mock.calls
    .map(([r]) => ({ method: r.method, path: new URL(r.url).pathname }))
    .filter((c) => c.method !== "GET");
}
