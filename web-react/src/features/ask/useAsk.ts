// The thread (every turn, in memory only), the pending request and the last error. Only the last
// turn is sent as `previous`; earlier turns are for display.

import { useMutation } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { ask, isApiError } from "@/lib/api";
import type { AnswerResponse, AskRequest, Turn } from "@/lib/types";

export interface AskError {
  title: string;
  text: string;
  retry: boolean;
  question?: string;
}

const RESET = "reset";

export interface Pending {
  request: AskRequest;
  startedAt: number;
}

/** What to say when an ask fails. Only a 422 drops the retry and the echoed question. */
export function describeAskError(err: unknown, request: AskRequest): AskError {
  const status = isApiError(err) ? err.status : -1;
  if (status === 503) {
    return { title: "Assistant unavailable", text: "The assistant is unavailable, nothing was answered. Try again in a moment.", retry: true, question: request.question };
  }
  if (status === 0) {
    const text = isApiError(err) && err.code === "timeout"
      ? "No answer arrived in time. Nothing was answered. Your question is kept."
      : "Couldn't reach the assistant. Check your signal. Your question is kept.";
    return { title: "No connection", text, retry: true, question: request.question };
  }
  if (status === 422) {
    return { title: "Check your question", text: "A question needs between 1 and 2000 characters.", retry: false };
  }
  return { title: "Something went wrong", text: "Nothing was answered. Try again.", retry: true, question: request.question };
}

/** How a request ended: "reset" is sign-out or an expired session aborting it, "expired" its own 401. */
export type AskOutcome = "answered" | "failed" | "cancelled" | "expired" | "reset" | "busy";

/**
 * The ask thread, one request at a time: a second send while one is pending is "busy". A 401
 * sets no error, since the expired-session handler takes over.
 */
export function useAsk(onAnswered: (turn: Turn) => void) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const current = turns[turns.length - 1] ?? null;
  const [error, setError] = useState<AskError | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [lastRequest, setLastRequest] = useState<AskRequest | null>(null);
  const controller = useRef<AbortController | null>(null);

  const mutation = useMutation<AnswerResponse, unknown, { request: AskRequest; signal: AbortSignal }>({
    mutationFn: ({ request, signal }) => ask(request, signal),
  });
  const { mutateAsync } = mutation;

  const send = useCallback(async (request: AskRequest): Promise<AskOutcome> => {
    if (controller.current) return "busy";
    const c = new AbortController();
    controller.current = c;
    setLastRequest(request);
    setError(null);
    setPending({ request, startedAt: Date.now() });
    try {
      const response = await mutateAsync({ request, signal: c.signal });
      const turn = { request, response };
      setTurns((t) => [...t, turn]);
      onAnswered(turn);
      return "answered";
    } catch (err) {
      if (isApiError(err) && err.status === 401) return "expired";
      if (c.signal.aborted) return c.signal.reason === RESET ? "reset" : "cancelled";
      setError(describeAskError(err, request));
      return "failed";
    } finally {
      controller.current = null;
      setPending(null);
    }
  }, [mutateAsync, onAnswered]);

  const cancel = useCallback(() => controller.current?.abort(), []);

  /** "New question": drop the thread, so the next message has no `previous`. */
  const clear = useCallback(() => {
    setTurns([]);
    setError(null);
  }, []);

  /** Sign-out and expired sessions. */
  const reset = useCallback(() => {
    controller.current?.abort(RESET);
    setTurns([]);
    setError(null);
    setLastRequest(null);
  }, []);

  return { turns, current, pending, error, lastRequest, send, cancel, clear, reset };
}
