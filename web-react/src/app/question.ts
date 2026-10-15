// The typed question is the only thing kept across a reload or an expired session, and only in
// sessionStorage. Answers, sources and drafts stay in memory.

const KEY = "copilot.question";

/** The kept question, or "" when there is none or sessionStorage is unavailable. */
export function storedQuestion(): string {
  try {
    return sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

/** Keeps `q` in sessionStorage; an empty string removes it. */
export function storeQuestion(q: string) {
  try {
    if (q) sessionStorage.setItem(KEY, q);
    else sessionStorage.removeItem(KEY);
  } catch {
    // Private mode without storage: the question just isn't kept.
  }
}
