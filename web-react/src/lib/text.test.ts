// Port of web/tests/text.test.mjs with every case kept, plus the helpers added for React.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import * as ex from "./contract.examples";
import {
  NOTICE_TITLES, assetFieldError, citationOrder, clarifyRequest, groupSentences, groupWords, isDidYouMean,
  noticeTitle, normalizeAssetId, parseSourceText, passageIdFromViewerUrl, personLabel, previousTurn, sentenceParts,
  setGroupWords, sourceFlags, sourceHref, titleWithRevision, unverifiedLabel,
} from "./text";
import type { AnswerResponse, SourceView, Turn } from "./types";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const sources = JSON.parse(readFileSync(`${root}web/dev/fixtures/sources.json`, "utf8")) as Record<string, SourceView>;
const scan = sources.p_7a891cda95ff12c33c8caaa5!;
const examples: Record<string, AnswerResponse> = {
  answer: ex.answer, restricted: ex.restricted, abstain: ex.abstain, clarify: ex.clarify, unverified: ex.unverified,
};

test("source markers become unverified parts without any value", () => {
  expect(parseSourceText("Head | [[unverified:r_1|page=3]] and more")).toEqual([
    { kind: "text", text: "Head | " },
    { kind: "unverified", reviewItemId: "r_1", page: 3 },
    { kind: "text", text: " and more" },
  ]);
});

test("marker without a page and an unclosed marker are still withheld", () => {
  expect(parseSourceText("[[unverified:r_2]]")).toEqual([{ kind: "unverified", reviewItemId: "r_2", page: null }]);
  const open = parseSourceText("a [[unverified:r_3|page=4 45 m and the rest");
  expect(open).toHaveLength(2);
  expect(open[1]!.kind).toBe("unverified");
  expect(JSON.stringify(open)).not.toContain("45 m");
});

test("unverified label wording", () => {
  expect(unverifiedLabel(3)).toBe("value unverified, see scanned page 3");
  expect(unverifiedLabel(null)).toBe("value unverified, see the scanned page");
});

test("unverified segment text is never passed through", () => {
  expect(sentenceParts([{ kind: "unverified", text: "45 m", page: 3, page_image_passage_id: "p_x" }]))
    .toEqual([{ kind: "unverified", page: 3, passageId: "p_x" }]);
});

test("unverified example and HCP-200 fixture never contain the withheld head value", () => {
  const shown = ex.unverified.sentences.flatMap((s) => sentenceParts(s.segments))
    .flatMap((p) => (p.kind === "text" ? [p.text] : [])).join("");
  expect(shown).toBe("The rated head is .");
  for (const text of [scan.text_original, scan.text_en]) {
    const parts = parseSourceText(text);
    const visible = parts.flatMap((p) => (p.kind === "text" ? [p.text] : [])).join("");
    expect(visible).not.toContain("45 m");
    expect(parts.some((p) => p.kind === "unverified" && p.page === 3)).toBe(true);
  }
});

test("every citation referenced by every example is numbered and listed", () => {
  for (const [name, r] of Object.entries(examples)) {
    for (const id of citationOrder(r)) expect(r.citations?.[id], `${name}: ${id} not in citations`).toBeTruthy();
  }
  expect(citationOrder(ex.answer).slice(0, 2)).toEqual(["p_32f5ef652cfa89ebd0e95aaf", "p_e35d98a44e996383173e0193"]);
});

test("consecutive steps are grouped into one list", () => {
  const blocks = groupSentences(ex.mockOil.sentences);
  expect(blocks.map((b) => b.kind)).toEqual(["statement", "steps", "warning", "statement"]);
  expect(blocks[1]!.items).toHaveLength(3);
});

test("flags for superseded, stale, scanned and translated", () => {
  const kinds = (o: Parameters<typeof sourceFlags>[0]) => sourceFlags(o).map((f) => f.kind);
  expect(kinds({ superseded: true })).toEqual(["superseded"]);
  expect(kinds({ possibly_stale: true })).toEqual(["stale"]);
  expect(kinds({ ocr: true, translated: true })).toEqual(["scan", "translated"]);
  expect(kinds(scan)).toEqual(["scan", "translated"]);
  expect(kinds({ lang: "en", text_en: null })).toEqual([]);
});

test("viewer_url maps to a passage ID", () => {
  expect(passageIdFromViewerUrl("/sources/p_abc")).toBe("p_abc");
  expect(passageIdFromViewerUrl("/api/sources/p_abc")).toBe("p_abc");
  expect(passageIdFromViewerUrl(null)).toBeNull();
});

test("server group descriptions override the offline fallback", () => {
  expect(groupWords("cert-hv")).toBe("high-voltage certification");
  setGroupWords({ "cert-hv": "High-voltage electrical certification (VFD cabinets)" });
  expect(groupWords("cert-hv")).toBe("High-voltage electrical certification (VFD cabinets)");
  expect(groupWords("region-na")).toBe("North America region");
  expect(groupWords("unknown-group")).toBe("unknown-group");
  setGroupWords(null);
  expect(groupWords("cert-hv")).toBe("high-voltage certification");
});

test("approver labels use names when the dev user list is available", () => {
  expect(personLabel("u08", [{ user_id: "u08", name: "Kenji Watanabe" }])).toBe("Kenji Watanabe (u08)");
  expect(personLabel("u08", [])).toBe("u08");
});

test("asset IDs are normalized before sending", () => {
  expect(normalizeAssetId("  tac-c-0142 ")).toBe("TAC-C-0142");
  expect(normalizeAssetId(null)).toBe("");
});

test("create-draft errors about the machine become field errors", () => {
  expect(assetFieldError({ status: 404 }, "TAC-C-9999")).toMatch(/TAC-C-9999 isn't in the asset records/);
  expect(assetFieldError({ status: 403 }, "TAC-C-0142")).toMatch(/not visible to you/);
  expect(assetFieldError({ status: 422, detail: "unknown asset TAC-C-9" }, "TAC-C-9")).toMatch(/isn't in the asset records/);
  expect(assetFieldError({ status: 422, detail: "asset_id is required: choose the machine" })).toBe("Enter the machine's asset ID.");
  expect(assetFieldError({ status: 422, detail: "summary must not be empty" })).toBeNull();
  expect(assetFieldError({ status: 0 })).toBeNull();
  expect(assetFieldError({ status: 503 })).toBeNull();
});

describe("follow-ups", () => {
  test("previous is the answer on screen, using question_used when set", () => {
    expect(previousTurn(null)).toBeNull();
    expect(previousTurn({ request: { question: "torque?" }, response: ex.answer }))
      .toEqual({ answer_id: ex.answer.answer_id, question: "torque?", asset_id: ex.answer.asset.asset_id });
    const cl: AnswerResponse = { answer_id: "ans_x", dataset_version: "d", status: "answer", asset: null, question_used: "What's the clearance on an HCP-200?" };
    expect(previousTurn({ request: { question: "Oh, I meant HCP-200" }, response: cl }))
      .toEqual({ answer_id: "ans_x", question: "What's the clearance on an HCP-200?", asset_id: null });
  });

  test("clarify options: retyped questions resend their text, machine picks resend with asset", () => {
    const previous = { answer_id: "ans_0", question: "q", asset_id: null };
    const current: Turn = { request: { question: "clearance on HCP-20?", previous },
      response: { answer_id: "ans_1", dataset_version: "d", status: "clarify", question_used: null } };
    expect(clarifyRequest(current, { asset_id: null, label: "HCP-200", question: "clearance on HCP-200?" }))
      .toEqual({ question: "clearance on HCP-200?", previous });
    expect(clarifyRequest(current, { asset_id: "TAC-C-0143", label: "TAC-C-0143", question: null }))
      .toEqual({ question: "clearance on HCP-20?", asset_id: "TAC-C-0143", clarification_of: "ans_1", previous });
    expect(clarifyRequest({ request: { question: "E-31?" }, response: { answer_id: "a", dataset_version: "d", status: "clarify" } }, { asset_id: "TAC-C-0142", label: "x" }))
      .toEqual({ question: "E-31?", asset_id: "TAC-C-0142", clarification_of: "a" });
  });

  test("did-you-mean is told apart from a machine pick", () => {
    expect(isDidYouMean(ex.clarify)).toBe(false);
    expect(isDidYouMean({ ...ex.clarify, clarification: { question: "Did you mean HCP-200?", options: [{ asset_id: null, label: "HCP-200", question: "q?" }] } })).toBe(true);
  });
});

test("no_answer notices are not titled as hidden content", () => {
  expect(NOTICE_TITLES.no_answer).toBe("Why there's no answer");
  expect(NOTICE_TITLES.no_answer).not.toBe(NOTICE_TITLES.not_visible);
  expect(noticeTitle("no_answer", ex.abstain)).toBe("Why there's no answer");
  expect(noticeTitle("not_visible", { status: "abstain", abstain_reason: "no_permitted_source" })).toBe("Why there's no answer");
  expect(noticeTitle("not_visible", { status: "abstain", abstain_reason: "not_visible" })).toBe("Not visible to you");
  expect(noticeTitle("something_new", ex.answer)).toBe("Note");
});

test("source links and titles", () => {
  expect(sourceHref("p_1")).toBe("#/sources/p_1");
  expect(sourceHref("p_1", "page")).toBe("#/sources/p_1/page");
  expect(titleWithRevision("Halden HCP-350 IOM Rev D", "D")).toBe("Halden HCP-350 IOM Rev D");
  expect(titleWithRevision("VRS-75 manual", "B")).toBe("VRS-75 manual · Rev B");
  expect(titleWithRevision("VRS-75 manual", null)).toBe("VRS-75 manual");
});
