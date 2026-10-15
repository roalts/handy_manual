// Source viewer for GET /api/sources/{passage_id} (specs/contracts/http-api.md), as a sheet. When
// it was opened from a citation that holds several sources, a switcher moves between them; the
// route alone (#/sources/{id}) always opens that one passage.

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { getSource, isApiError } from "@/lib/api";
import { replace } from "@/lib/router";
import { sourceHref } from "@/lib/text";
import { keys } from "@/app/query";
import { AppSheet } from "@/features/AppSheet";
import type { GroupItem } from "@/features/answer/sourceGroup";
import { DOC_TYPE_WORDS, SourceView } from "./SourceView";

interface Props {
  passageId: string;
  focus: "page" | null;
  /** The sources cited together with this one; empty when the sheet was opened on its own. */
  group: GroupItem[];
  onClose: () => void;
}

/** Fetches the passage and shows it, or why it can't be shown (403, 404, other errors); a 401 is left to the expired-session handling. */
export default function SourceSheet({ passageId, focus, group, onClose }: Props) {
  const q = useQuery({ queryKey: keys.source(passageId), queryFn: () => getSource(passageId) });
  const status = isApiError(q.error) ? q.error.status : null;
  const here = group.find((g) => g.passageId === passageId);

  useEffect(() => {
    document.title = q.data ? `${q.data.title} · Handy Manual` : "Source · Handy Manual";
  }, [q.data]);

  const switcher = group.length > 1 ? <Switcher current={passageId} group={group} /> : null;
  const kickerFor = (type?: string) => [here ? `Source ${here.n}` : null, type].filter(Boolean).join(" · ") || null;

  if (q.data) {
    return (
      <AppSheet kicker={kickerFor(DOC_TYPE_WORDS[q.data.doc_type] ?? q.data.doc_type)} onClose={onClose} title={<span id="source-title">{q.data.title}</span>}>
        {switcher}
        <SourceView focus={focus} src={q.data} />
      </AppSheet>
    );
  }
  if (status === 403) {
    return (
      <AppSheet kicker={kickerFor()} onClose={onClose} title={<span id="nv-title">Not visible to you</span>}>
        {switcher}
        <section aria-labelledby="nv-title" className="card not-visible">
          <p className="m-0">This source exists, but your permissions don't include it. Ask your team lead if you need it.</p>
        </section>
      </AppSheet>
    );
  }
  if (status === 404) {
    return (
      <AppSheet kicker={kickerFor()} onClose={onClose} title={<span id="nf-title">Source not found</span>}>
        {switcher}
        <section className="card abstain"><p className="m-0">This passage is not in the current dataset.</p></section>
      </AppSheet>
    );
  }
  if (q.error && status !== 401) {
    return (
      <AppSheet kicker={kickerFor()} onClose={onClose} title={status === 0 ? "No connection" : "Couldn't open the source"}>
        {switcher}
        <section className="card error" role="alert">
          <p className="mt-0">Check your signal and try again.</p>
          <Button onClick={() => void q.refetch()} type="button">Try again</Button>
        </section>
      </AppSheet>
    );
  }
  return (
    <AppSheet kicker={kickerFor()} onClose={onClose} title="Opening source…">
      {switcher}
      <p className="hint" role="status">Opening source…</p>
    </AppSheet>
  );
}

/**
 * One button per source of the tapped citation. Tab reaches each; Left and Right move between them.
 * Switching replaces the route, so Back still closes the sheet. The sheet is modal, so the change
 * is announced from a live region inside it.
 */
function Switcher({ group, current }: { group: GroupItem[]; current: string }) {
  const [said, setSaid] = useState("");
  const index = Math.max(0, group.findIndex((g) => g.passageId === current));
  const go = (k: number, focus: boolean) => {
    const g = group[k];
    if (!g || g.passageId === current) return;
    replace(sourceHref(g.passageId));
    setSaid(`Source ${g.n}, ${k + 1} of ${group.length}: ${g.title}, ${g.locator}`);
    if (focus) requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`[data-source-switch="${CSS.escape(g.passageId)}"]`)?.focus());
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    go((index + (e.key === "ArrowRight" ? 1 : group.length - 1)) % group.length, true);
  };
  return (
    <nav aria-label="Sources cited together" className="source-switch mb-1 flex items-center gap-3" onKeyDown={onKeyDown}>
      <ul className="m-0 flex list-none gap-1 p-0">
        {group.map((g, k) => {
          const on = k === index;
          return (
            <li key={g.passageId}>
              <button
                aria-current={on ? "true" : undefined}
                aria-label={`Source ${g.n}: ${g.title}, ${g.locator}`}
                className={`inline-flex size-tap cursor-pointer items-center justify-center rounded-full text-[15px] font-bold tabular-nums ${on ? "bg-brand text-[var(--brand-ink)]" : "bg-paper-soft text-ink"}`}
                data-source-switch={g.passageId}
                onClick={() => go(k, false)}
                type="button"
              >
                {g.n}
              </button>
            </li>
          );
        })}
      </ul>
      <p aria-hidden className="hint m-0">{index + 1} of {group.length} cited here</p>
      <p aria-live="polite" className="sr-only">{said}</p>
    </nav>
  );
}
