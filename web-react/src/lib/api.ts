// Fetch wrapper for the 003 API. Same origin, relative /api URLs, never cached by the browser.

import type {
  AnswerResponse, AskRequest, CreateDraftRequest, DevUser, DraftEdits, GroupWords, Identity, SourceView, WorkOrderDraft,
} from "./types";

/** status 0 means no HTTP response: code is "timeout", "aborted" or "network". */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detail: string | null;

  constructor(status: number, code: string | null, detail: string | null) {
    super(detail || code || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

/** Narrows a caught error to ApiError; anything else thrown (bugs, non-API errors) is false. */
export const isApiError = (err: unknown): err is ApiError => err instanceof ApiError;

const TIMEOUT_MS = 60000;

interface Options {
  body?: unknown;
  headers?: Record<string, string>;
  timeoutMs?: number;
  signal?: AbortSignal;
}

declare global {
  interface Window { __early?: Record<string, Promise<Response> | undefined> }
}

/** A GET started by the inline script in index.html, used once. */
function takeEarly(method: string, path: string): Promise<Response> | undefined {
  if (method !== "GET" || typeof window === "undefined" || !window.__early) return undefined;
  const res = window.__early[path];
  delete window.__early[path];
  return res;
}

/**
 * JSON request to the API with a timeout (60 s by default). Without a `signal`, a GET first takes
 * the early fetch for its path. Throws ApiError: status 0 when no response arrived.
 */
export async function api<T>(method: string, path: string, { body, headers = {}, timeoutMs = TIMEOUT_MS, signal }: Options = {}): Promise<T> {
  const early = signal ? undefined : takeEarly(method, path);
  if (early) {
    let res: Response | undefined;
    try {
      res = await early;
    } catch {
      res = undefined;
    }
    if (res) return parse<T>(res);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const forward = () => controller.abort(signal?.reason);
  if (signal?.aborted) forward();
  signal?.addEventListener("abort", forward);
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    const timedOut = (controller.signal.reason as Error | undefined)?.name === "TimeoutError";
    const aborted = !timedOut && (err as Error | undefined)?.name === "AbortError";
    throw new ApiError(0, timedOut ? "timeout" : aborted ? "aborted" : "network", (err as Error | undefined)?.message ?? null);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forward);
  }
  return parse<T>(res);
}

/** Body as JSON (null for 204 or a body that isn't JSON); a non-2xx throws ApiError with its `error` and `detail`. */
async function parse<T>(res: Response): Promise<T> {
  if (res.status === 204) return null as T;
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = (data ?? {}) as { error?: unknown; detail?: unknown };
    throw new ApiError(res.status, typeof err.error === "string" ? err.error : null, typeof err.detail === "string" ? err.detail : null);
  }
  return data as T;
}

const id = encodeURIComponent;

/** The signed-in user; 401 when there is no session. */
export const getSession = () => api<Identity>("GET", "/api/session");
/** Starts a session for a user ID (development sign-in). */
export const signIn = (userId: string) => api<Identity>("POST", "/api/session", { body: { user_id: userId } });
/** Ends the server session. */
export const signOut = () => api<null>("DELETE", "/api/session");
/** Test users for the sign-in screen; production answers 404. */
export const listDevUsers = () => api<{ users: DevUser[] }>("GET", "/api/dev/users");
/** Plain-words descriptions of the permission groups. */
export const getGroups = () => api<GroupWords>("GET", "/api/groups");
/** Asks a question; `signal` cancels it. */
export const ask = (request: AskRequest, signal?: AbortSignal) => api<AnswerResponse>("POST", "/api/ask", { body: request, signal });
/** One cited passage for the source sheet. */
export const getSource = (passageId: string) => api<SourceView>("GET", `/api/sources/${id(passageId)}`);
/** Creates a work-order draft from an answer's suggestion. Sends nothing to MaintPro or Servio. */
export const createDraft = (body: CreateDraftRequest) => api<WorkOrderDraft>("POST", "/api/work-orders", { body });
/** A work-order draft by ID. */
export const getDraft = (draftId: string) => api<WorkOrderDraft>("GET", `/api/work-orders/${id(draftId)}`);
/** Saves the editable fields of a draft. */
export const patchDraft = (draftId: string, body: DraftEdits) => api<WorkOrderDraft>("PATCH", `/api/work-orders/${id(draftId)}`, { body });
/** Moves a draft through its workflow; "submit" is the only action that sends it to MaintPro or Servio. */
export const draftAction = (draftId: string, action: "request-approval" | "approve" | "reject" | "submit", body: object = {}, headers: Record<string, string> = {}) =>
  api<WorkOrderDraft>("POST", `/api/work-orders/${id(draftId)}/${action}`, { body, headers });

/** Retry only what a retry can fix: no connection (not a cancel) and 503. Never 401, 403, 404 or 422. */
export function shouldRetry(failureCount: number, err: unknown): boolean {
  if (failureCount >= 2 || !isApiError(err)) return false;
  return (err.status === 0 && err.code === "network") || err.status === 503;
}
