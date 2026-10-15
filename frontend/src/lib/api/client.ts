import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

/**
 * The CSRF token lives only in memory (never localStorage). After a reload it is re-fetched from
 * GET /auth/me, which is authenticated by the HttpOnly session cookie.
 */
let csrfToken: string | null = null;
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, details: unknown, requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  /** Field-level messages from a 422 VALIDATION_ERROR payload, keyed by the last loc segment. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    if (Array.isArray(this.details)) {
      for (const item of this.details as { loc?: unknown[]; msg?: string }[]) {
        const key = item.loc?.at(-1);
        if (typeof key === "string" && item.msg) out[key] = item.msg;
      }
    } else if (this.details && typeof this.details === "object" && "field" in this.details) {
      const field = (this.details).field;
      if (typeof field === "string") out[field] = this.message;
    }
    return out;
  }
}

const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    if (UNSAFE.has(request.method) && csrfToken) request.headers.set("X-CSRF-Token", csrfToken);
    return request;
  },
};

const baseUrl = typeof window === "undefined" ? "http://localhost" : window.location.origin;
export const api = createClient<paths>({ baseUrl, credentials: "same-origin" });
api.use(csrfMiddleware);

let unauthorizedHandler: (() => void) | null = null;
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

export async function toApiError(response: Response, error: unknown): Promise<ApiError> {
  let body = error;
  if (body === undefined) {
    try {
      body = await response.clone().json();
    } catch {
      body = undefined;
    }
  }
  const payload = (body as { error?: { code?: string; message?: string; details?: unknown; request_id?: string } } | undefined)?.error;
  return new ApiError(
    response.status,
    payload?.code ?? `HTTP_${response.status}`,
    payload?.message ?? (response.status >= 500 ? "The server is unavailable. Retry shortly." : `Request failed (${response.status}).`),
    payload?.details,
    payload?.request_id ?? response.headers.get("x-request-id"),
  );
}

/** Unwrap an openapi-fetch result, throwing ApiError for non-2xx responses. */
export async function call<T>(request: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await request;
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach MarketOps. Check your connection and retry.", null, null);
  }
  const { data, error, response } = result;
  if (!response.ok) {
    const apiError = await toApiError(response, error);
    if (apiError.status === 401) unauthorizedHandler?.();
    throw apiError;
  }
  return data as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

/** A sleeping/starting backend (free-tier cold start) rather than a real failure. */
export function isWaking(error: unknown): boolean {
  return error instanceof ApiError && [0, 502, 503, 504].includes(error.status) && error.code !== "PERSISTENCE_UNAVAILABLE";
}
