// Pure helpers with no DOM access, ported from web/js/text.js and tested with Vitest.

import type {
  AnswerResponse, AskRequest, Citation, ClarifyOption, DevUser, GroupWords, PreviousTurn, Segment, Sentence, SourceView, Turn,
} from "./types";

const MARKER = /\[\[unverified:([^\]|]*)(?:\|page=(\d+))?[^\]]*\]\]/g;
const OPEN_MARKER = /\[\[unverified[^]*$/;

export type SourcePart =
  | { kind: "text"; text: string }
  | { kind: "unverified"; reviewItemId: string | null; page: number | null };

/**
 * Split source text into text and unverified parts. An unverified part never carries the
 * withheld value, only its review item ID and page. An unclosed marker hides everything after it.
 */
export function parseSourceText(text: string | null | undefined): SourcePart[] {
  const all = String(text ?? "");
  const parts: SourcePart[] = [];
  let last = 0;
  for (const m of all.matchAll(MARKER)) {
    if (m.index > last) parts.push({ kind: "text", text: all.slice(last, m.index) });
    parts.push({ kind: "unverified", reviewItemId: m[1] || null, page: m[2] ? Number(m[2]) : null });
    last = m.index + m[0].length;
  }
  let rest = all.slice(last);
  const open = rest.match(OPEN_MARKER);
  if (open) {
    if (open.index && open.index > 0) parts.push({ kind: "text", text: rest.slice(0, open.index) });
    parts.push({ kind: "unverified", reviewItemId: null, page: null });
    rest = "";
  }
  if (rest) parts.push({ kind: "text", text: rest });
  return parts;
}

/** The words shown in place of a withheld value, naming the page when it is known. */
export function unverifiedLabel(page: number | null | undefined): string {
  return page ? `value unverified, see scanned page ${page}` : "value unverified, see the scanned page";
}

export type SentencePart =
  | { kind: "text"; text: string }
  | { kind: "unverified"; page: number | null; passageId: string | null };

/**
 * Segments of an answer sentence as display parts. Unverified segments drop any text the
 * producer may have put in them.
 */
export function sentenceParts(segments: Segment[] | null | undefined): SentencePart[] {
  return (segments ?? []).map((seg) =>
    seg.kind === "unverified"
      ? { kind: "unverified", page: seg.page ?? null, passageId: seg.page_image_passage_id ?? null }
      : { kind: "text", text: seg.text ?? "" });
}

/** Citation numbers in order of first use across sentences, conflicts, notices, bulletins and restricted. */
export function citationOrder(resp: AnswerResponse): string[] {
  const order: string[] = [];
  const add = (ids: readonly string[] | null | undefined) => {
    for (const id of ids ?? []) if (!order.includes(id)) order.push(id);
  };
  for (const s of resp.sentences ?? []) add(s.citations);
  for (const c of resp.conflicts ?? []) for (const side of c.sides ?? []) add(side.citations);
  for (const n of resp.notices ?? []) add(n.citations);
  for (const b of resp.asset?.bulletins ?? []) add(b.citations);
  add(resp.restricted?.citations);
  add(resp.work_order_suggestion?.citations);
  return order;
}

export type SentenceBlock =
  | { kind: "steps"; items: Sentence[] }
  | { kind: "statement" | "warning"; items: [Sentence] };

/** Group sentences into runs so consecutive steps become one ordered list. */
export function groupSentences(sentences: Sentence[] | null | undefined): SentenceBlock[] {
  const blocks: SentenceBlock[] = [];
  for (const s of sentences ?? []) {
    const lastBlock = blocks[blocks.length - 1];
    if (s.kind === "step" && lastBlock?.kind === "steps") lastBlock.items.push(s);
    else if (s.kind === "step") blocks.push({ kind: "steps", items: [s] });
    else blocks.push({ kind: s.kind, items: [s] });
  }
  return blocks;
}

/** Offline fallback only; GET /api/groups replaces these via setGroupWords. */
export const GROUP_WORDS: GroupWords = {
  "region-na": "North America region",
  "region-eu": "Europe region",
  "family-pumps": "Halden HCP pump training",
  "family-compressors": "Vastra VRS compressor training",
  "family-chillers": "Nordkyl NK chiller training",
  "family-conveyors": "Belton BX conveyor training",
  "cert-hv": "high-voltage certification",
  "cert-refrigerant": "refrigerant handling certification",
  "cert-confined-space": "confined space entry certification",
  "role-lead": "field team lead role",
};

let serverGroupWords: GroupWords = {};

/** Replaces the server's group descriptions; anything that isn't an object clears them. */
export function setGroupWords(map: GroupWords | null | undefined): void {
  serverGroupWords = map && typeof map === "object" ? { ...map } : {};
}

/** Plain words for a permission group: the server's, then GROUP_WORDS, else the group ID itself. */
export function groupWords(group: string): string {
  return serverGroupWords[group] ?? GROUP_WORDS[group] ?? group;
}

/** "Kenji Watanabe (u08)" when the name is known, else the ID. */
export function personLabel(userId: string, users: readonly Pick<DevUser, "user_id" | "name">[] | null | undefined): string {
  const u = (users ?? []).find((x) => x.user_id === userId);
  return u ? `${u.name} (${userId})` : userId;
}

export const ABSTAIN_WORDS: Record<string, string> = {
  no_permitted_source: "Your sources don't cover this.",
  not_visible: "Sources about this exist, but they are not visible to you.",
  unknown_asset: "That machine isn't in the asset records. Check the asset ID on the nameplate.",
  out_of_scope: "This is outside what the assistant covers.",
};

export const BULLETIN_STATUS_WORDS: Record<string, string> = {
  affected: "Applies to this machine",
  in_campaign: "In campaign",
  not_affected: "Does not apply",
  check_on_site: "Check on site",
};

export const NOTICE_TITLES: Record<string, string> = {
  superseded: "Superseded revision",
  possibly_stale: "Possibly out of date",
  bulletin: "Bulletin",
  check_on_site: "Check on site",
  unverified_value: "Unverified value",
  not_visible: "Not visible to you",
  no_answer: "Why there's no answer",
  translated: "Machine-translated",
  history: "Service history used",
};

/**
 * Title for a notice. The engine labelled every abstain notice not_visible before `no_answer`
 * existed, so "not visible" is only said when that is the abstain reason.
 */
export function noticeTitle(kind: string, resp: Pick<AnswerResponse, "status" | "abstain_reason">): string {
  if (kind === "not_visible" && resp.status === "abstain" && resp.abstain_reason !== "not_visible") {
    return NOTICE_TITLES.no_answer!;
  }
  return NOTICE_TITLES[kind] ?? "Note";
}

export const SYSTEM_NAMES: Record<string, string> = { maintpro: "MaintPro", servio: "Servio" };
export const REGION_BY_SYSTEM: Record<string, string> = { maintpro: "North America", servio: "Europe" };

export const DRAFT_STATUS_WORDS: Record<string, string> = {
  draft: "Draft",
  pending_approval: "Waiting for approval",
  approved: "Approved",
  rejected: "Rejected",
  submitted: "Submitted",
};

export const APPROVAL_REASON_WORDS: Record<string, string> = {
  parts: "it orders parts",
  certification: "it needs a certified technician",
  campaign: "it is part of a bulletin campaign",
  specialist: "it needs a specialist",
  "return visit": "it needs a return visit",
  "no eligible approver": "no team lead can approve it",
};

export type FlagKind = "superseded" | "stale" | "scan" | "translated";
export interface Flag { kind: FlagKind; text: string }

type Flaggable = Partial<Pick<Citation, "superseded" | "possibly_stale" | "ocr" | "translated">> &
  Partial<Pick<SourceView, "status" | "text_en" | "lang">>;

/** Labels for a citation or source view: superseded, possibly stale, scanned, machine-translated. */
export function sourceFlags(src: Flaggable): Flag[] {
  const flags: Flag[] = [];
  if (src.superseded || src.status === "superseded") flags.push({ kind: "superseded", text: "Superseded revision" });
  if (src.possibly_stale) flags.push({ kind: "stale", text: "Possibly out of date" });
  if (src.ocr) flags.push({ kind: "scan", text: "Scanned" });
  if (src.translated || (src.text_en && src.lang && src.lang !== "en")) {
    flags.push({ kind: "translated", text: "Machine-translated" });
  }
  return flags;
}

/**
 * The one turn of memory (answer.md, follow-ups): the answer on screen as AskRequest.previous,
 * or null when there is none.
 */
export function previousTurn(current: Turn | null | undefined): PreviousTurn | null {
  const resp = current?.response;
  if (!resp?.answer_id) return null;
  const question = (resp.question_used || current?.request?.question || "").slice(0, 2000);
  if (!question.trim()) return null;
  return { answer_id: resp.answer_id, question, asset_id: resp.asset?.asset_id ?? null };
}

/**
 * AskRequest for a tapped clarify option. "Did you mean" options resend their `question`;
 * machine options resend the question with `asset_id` and `clarification_of`. Both keep the
 * `previous` the clarify answered.
 */
export function clarifyRequest(current: Turn, option: ClarifyOption): AskRequest {
  const keep = current.request?.previous ? { previous: current.request.previous } : {};
  if (option.question) return { question: option.question, ...keep };
  return {
    question: current.response.question_used || current.request.question,
    asset_id: option.asset_id ?? null,
    clarification_of: current.response.answer_id,
    ...keep,
  };
}

/** Clarify where every option retypes the question ("did you mean HCP-200?"). */
export function isDidYouMean(resp: AnswerResponse): boolean {
  return resp.status === "clarify" && Boolean(resp.clarification?.options.every((o) => o.question));
}

/** Asset ID as typed, upper-cased with all whitespace removed; "" for null. */
export function normalizeAssetId(raw: string | null | undefined): string {
  return String(raw ?? "").trim().toUpperCase().replace(/\s+/g, "");
}

/**
 * Message for the machine field when creating a draft fails because of the asset, else null
 * (the error then belongs to the whole form). 404 and 403 are always about the machine here;
 * 422 only when its detail names the asset.
 */
export function assetFieldError(err: { status?: number; detail?: string | null } | null | undefined, assetId?: string): string | null {
  const id = assetId || "that machine";
  if (err?.status === 404) return `${id} isn't in the asset records. Check the asset ID on the nameplate.`;
  if (err?.status === 403) return `${id} is not visible to you, or a source behind this work order isn't. Ask your team lead.`;
  const detail = err?.detail ?? "";
  if (err?.status === 422 && /asset/i.test(detail)) {
    if (/required/i.test(detail)) return "Enter the machine's asset ID.";
    if (/unknown asset/i.test(detail)) return `${id} isn't in the asset records. Check the asset ID on the nameplate.`;
    return detail.charAt(0).toUpperCase() + detail.slice(1) + ".";
  }
  return null;
}

export const LANGUAGE_NAMES: Record<string, string> = { de: "German", nl: "Dutch", en: "English", pl: "Polish" };

/** Passage ID from a `/sources/{id}` viewer URL, or null when the URL has none. */
export function passageIdFromViewerUrl(url: string | null | undefined): string | null {
  const m = String(url ?? "").match(/\/sources\/([\w-]+)/);
  return m?.[1] ?? null;
}

/** Hash route for a source; `page` scrolls to the page image. */
export function sourceHref(passageId: string, focus?: "page"): string {
  return `#/sources/${encodeURIComponent(passageId)}${focus ? `/${focus}` : ""}`;
}

/** Title with the revision appended unless the title already names it. */
export function titleWithRevision(title: string, revision: string | null | undefined): string {
  if (!revision || new RegExp(`\\bRev\\.? ${revision.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(title)) return title;
  return `${title} · Rev ${revision}`;
}
