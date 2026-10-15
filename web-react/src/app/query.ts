// TanStack Query client: in memory only (no persister). Queries retry only on no connection and
// 503; mutations never retry on their own (asking and submitting have their own "Try again").
// Any 401 outside the session probe means the session expired.

import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { isApiError, shouldRetry } from "@/lib/api";

type Listener = () => void;
const expiredListeners = new Set<Listener>();

/** Calls `listener` whenever a session expires; returns the unsubscribe. */
export function onSessionExpired(listener: Listener) {
  expiredListeners.add(listener);
  return () => void expiredListeners.delete(listener);
}

/** Tells the expired-session listeners about a 401, unless it came from the session query itself. */
function check(err: unknown, key?: readonly unknown[]) {
  if (isApiError(err) && err.status === 401 && key?.[0] !== "session") {
    for (const l of expiredListeners) l();
  }
}

export const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: (err, query) => check(err, query.queryKey) }),
  mutationCache: new MutationCache({ onError: (err) => check(err) }),
  defaultOptions: {
    queries: {
      retry: shouldRetry,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
    mutations: { retry: false },
  },
});

export const keys = {
  session: ["session"] as const,
  devUsers: ["dev-users"] as const,
  groups: ["groups"] as const,
  source: (id: string) => ["source", id] as const,
  draft: (id: string) => ["draft", id] as const,
};
