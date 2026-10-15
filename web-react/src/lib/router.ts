// Hash routes: #/signin, #/ask, #/sources/{id}[/page], #/work-orders/new, #/work-orders/{id}.
// history.state.depth counts in-app steps, so "Back" leaves the app's history only when it can.

import { useSyncExternalStore } from "react";

export type Route =
  | { name: "signin" }
  | { name: "ask" }
  | { name: "source"; id: string; focus: "page" | null }
  | { name: "new-draft" }
  | { name: "draft"; id: string };

/** Route for a location hash; anything unrecognised is the ask screen. */
export function parseHash(hash: string): Route {
  const [, name, id, extra] = hash.match(/^#\/([\w-]+)(?:\/([^/]+))?(?:\/([\w-]+))?/) ?? [];
  if (name === "signin") return { name: "signin" };
  if (name === "sources" && id) return { name: "source", id: decodeURIComponent(id), focus: extra === "page" ? "page" : null };
  if (name === "work-orders" && id === "new") return { name: "new-draft" };
  if (name === "work-orders" && id) return { name: "draft", id: decodeURIComponent(id) };
  return { name: "ask" };
}

let depth = 0;

/** Reads the depth from history.state, or stamps a history entry that has none (a typed or followed hash link). */
function syncDepth() {
  const state = history.state as { depth?: number } | null;
  if (typeof state?.depth === "number") depth = state.depth;
  else history.replaceState({ depth: ++depth }, "");
}

/** pushState and replaceState fire no hashchange, so useRoute is told by a synthetic one. */
function notify() {
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

/** New history entry for `hash`, one step deeper. Navigating to the current hash adds no entry. */
export function navigate(hash: string) {
  if (location.hash === hash) return notify();
  history.pushState({ depth: depth + 1 }, "", hash);
  depth += 1;
  notify();
}

/** Swaps the current history entry for `hash`, keeping its depth. */
export function replace(hash: string) {
  history.replaceState({ depth }, "", hash);
  notify();
}

/** Back within the app, or to the ask screen when the page was opened on this route. */
export function goBack() {
  if (depth > 0) history.back();
  else replace("#/ask");
}

/** The API may link to /sources/{id} as a path; the client routes in the hash. */
export function rewritePathRoute() {
  const m = location.pathname.match(/^\/(sources|work-orders)\/([\w-]+)/);
  if (m) history.replaceState({ depth: 0 }, "", `/#/${m[1]}/${m[2]}`);
  else if (typeof (history.state as { depth?: number } | null)?.depth !== "number") history.replaceState({ depth: 0 }, "");
  depth = (history.state as { depth: number }).depth;
}

/** useSyncExternalStore subscription to hashchange; keeps the depth in step before each update. */
function subscribe(cb: () => void) {
  const onChange = () => {
    syncDepth();
    cb();
  };
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/** The current route, re-rendering on every hash change; an empty hash is #/ask. */
export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => location.hash || "#/ask");
  return parseHash(hash);
}
