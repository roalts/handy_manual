// Citations numbered by first use, one control per sentence, and the unverified-value placeholder
// (FR-002: withheld values never displayed: only "value unverified, see scanned page N" is ever
// rendered).

import { createContext, useContext } from "react";
import { passageIdFromViewerUrl, sourceFlags, sourceHref, unverifiedLabel, type Flag, type SentencePart } from "@/lib/text";
import type { AnswerResponse } from "@/lib/types";
import { useOpenSourceGroup, type GroupItem } from "./sourceGroup";

export interface CitationContextValue {
  resp: AnswerResponse;
  order: string[];
}

export const CitationContext = createContext<CitationContextValue | null>(null);

/** The answer being rendered and its citation order; throws outside CitationContext. */
export function useCitations() {
  const ctx = useContext(CitationContext);
  if (!ctx) throw new Error("Citations must be inside CitationContext");
  return ctx;
}

/**
 * One control for all the sources of a sentence (or side, notice, bulletin). Its accessible name
 * lists every source; tapping it opens the first, and the sheet switches between the others.
 */
export function Cite({ ids }: { ids: readonly string[] | null | undefined }) {
  const { resp, order } = useCitations();
  const openGroup = useOpenSourceGroup();
  if (!ids?.length) return null;
  const items = ids.flatMap((id) => {
    const c = resp.citations?.[id];
    return c ? [{ id, c, n: order.indexOf(id) + 1, flags: sourceFlags(c) }] : [];
  });
  if (!items.length) {
    return <span className="chips"><span className="chip cite missing" title="Source missing from the response"><span className="cite-face">?</span></span></span>;
  }
  const describe = ({ n, c, flags }: (typeof items)[number]) => [`${n}: ${c.title}, ${c.locator}`, ...flags.map((f) => f.text)].join(", ");
  const label = items.length === 1 ? `Source ${describe(items[0]!)}` : `Sources ${items.map(describe).join("; ")}`;
  const warn = items.some((it) => it.flags.some((f) => f.kind === "superseded" || f.kind === "stale"));
  const group: GroupItem[] = items.map(({ id, c, n }) => ({ passageId: passageIdFromViewerUrl(c.viewer_url) ?? id, n, title: c.title, locator: c.locator }));
  return (
    <span className="chips">
      {" "}
      <a aria-label={label} className={`chip cite${warn ? " chip-warn" : ""}`} href={sourceHref(group[0]!.passageId)} onClick={() => openGroup(group)}>
        <span className="cite-face">{items.map((it) => it.n).join(",")}{warn && <span aria-hidden>!</span>}</span>
      </a>
    </span>
  );
}

/** Placeholder for a withheld value; links to the page image when there is a passage to open. */
export function UnverifiedValue({ page, passageId }: { page: number | null; passageId: string | null }) {
  const label = unverifiedLabel(page);
  if (!passageId) return <span className="unverified">{label}</span>;
  return <a className="unverified" href={sourceHref(passageId, "page")}>{label}</a>;
}

/** A sentence's text with its unverified values as placeholders. */
export function Parts({ parts }: { parts: SentencePart[] }) {
  return parts.map((p, i) =>
    p.kind === "unverified" ? <UnverifiedValue key={i} page={p.page} passageId={p.passageId} /> : <span key={i}>{p.text}</span>);
}

/** Source labels (superseded, possibly stale, scanned, machine-translated); nothing when there are none. */
export function Flags({ flags }: { flags: Flag[] }) {
  if (!flags.length) return null;
  return (
    <span className="flags my-1 flex flex-wrap gap-1.5">
      {flags.map((f) => <span className={`flag flag-${f.kind}`} key={f.kind}>{f.text}</span>)}
    </span>
  );
}
