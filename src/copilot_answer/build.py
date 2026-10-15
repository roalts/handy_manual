"""Turn validated model output and code decisions into contract objects."""
import re

from copilot_answer.applicability import Candidate
from copilot_answer.validate import UNVERIFIED, ident_norm
from copilot_contracts import Citation, Conflict, ConflictSide, PartLine, Segment

_MARKER = re.compile(r"\[\[unverified:([^\]|]+)\|page=(\d+)\]\]")
APPLYING = {"affected", "in_campaign", "check_on_site"}


def locator(c: Candidate) -> str:
    """Where the passage is: case, record or message ID, pages and section, or the title."""
    a, d = c.passage.anchor or {}, c.doc
    section = (a.get("section_path") or c.passage.heading_path or [""])[-1]
    section = re.sub(r"\s{2,}", " ", section).strip()
    if a.get("record_id"):
        return (f"Case {a['record_id']}" if d.doc_type == "case_export"
                else f"Record {a['record_id']}")
    if a.get("message_id"):
        return f"Message {a['message_id']}" + (f", {section}" if section else "")
    if a.get("page"):
        page = f"p. {a['page']}" + (f"-{a['page_end']}" if a.get("page_end") else "")
        return page + (f", {section}" if section else "")
    return section or d.title


def citation(c: Candidate) -> Citation:
    """Contract citation for a candidate, flagging superseded, stale, OCR and translation."""
    p, d = c.passage, c.doc
    return Citation(
        passage_id=p.passage_id, doc_id=d.doc_id, title=d.title, doc_type=d.doc_type,
        revision=d.revision, issue_date=d.issue_date, authority_tier=d.authority_tier,
        locator=locator(c), viewer_url=f"/sources/{p.passage_id}",
        superseded=c.superseded, possibly_stale=c.stale or p.possibly_stale,
        ocr=p.ocr != "none", translated=bool(p.text_en) and (p.lang or "en") != "en")


def segments(text: str, cited: list[Candidate]) -> list[Segment]:
    """Split text into plain and unverified-value segments; each marker points to the cited
    passage that holds it (for its page image)."""
    out: list[Segment] = []
    pos = 0
    for m in _MARKER.finditer(text):
        if m.start() > pos:
            out.append(Segment(kind="text", text=text[pos:m.start()]))
        holder = next((c.pid for c in cited if m.group(0) in c.passage.all_text), None)
        out.append(Segment(kind="unverified", review_item_id=m.group(1), page=int(m.group(2)),
                           page_image_passage_id=holder))
        pos = m.end()
    if pos < len(text):
        out.append(Segment(kind="text", text=text[pos:]))
    return out or [Segment(kind="text", text=text)]


def has_unverified(text: str) -> bool:
    """Whether the text holds a withheld-value marker."""
    return bool(UNVERIFIED.search(text))


def preferred_side(sides: list[list[Candidate]]) -> tuple[int | None, str]:
    """Applicability to this machine first, then authority tier (research R8)."""
    applying = [i for i, cs in enumerate(sides)
                if any(c.bulletin_status in APPLYING for c in cs)]
    if len(applying) == 1:
        return applying[0], "The bulletin applies to this unit and takes precedence."
    tiers = [min((c.doc.authority_tier for c in cs if c.doc.authority_tier > 0), default=None)
             for cs in sides]
    ranked = sorted((t, i) for i, t in enumerate(tiers) if t is not None)
    if len(ranked) >= 2 and ranked[0][0] < ranked[1][0]:
        i = ranked[0][1]
        best = min((c for c in sides[i] if c.doc.authority_tier > 0),
                   key=lambda c: c.doc.authority_tier)
        return i, f"{best.doc.title} has the higher source authority."
    return None, "Sources have equal authority; check with your team lead."


def conflict(topic: str, sides: list[tuple[str, list[Candidate]]]) -> Conflict:
    """Contract conflict with the preferred side and its reason, decided by code."""
    pref, reason = preferred_side([cs for _, cs in sides])
    return Conflict(topic=topic, preferred=pref, reason=reason,
                    sides=[ConflictSide(statement=s, citations=[c.pid for c in cs])
                           for s, cs in sides])


def parts(proposed: list[dict], cited: list[Candidate]) -> list[PartLine]:
    """Keep parts whose number appears in a cited passage; quantity only if it appears on the
    same line as the part number, else 1."""
    out: list[PartLine] = []
    for item in proposed:
        pn = item.get("part_number", "").strip()
        if not re.fullmatch(r"\d{2}-\d{4}", pn):
            continue
        lines = [ln for c in cited for ln in c.passage.all_text.splitlines() if pn in ln]
        if not lines:
            continue
        qty = int(item.get("quantity") or 1)
        words = {2: "two", 3: "three", 4: "four"}
        ok = qty == 1 or any(re.search(rf"(?<![\d-]){qty}(?![\d-])", ln.replace(pn, " "))
                             or words.get(qty, "\0") in ln.casefold() for ln in lines)
        if pn not in [p.part_number for p in out]:
            out.append(PartLine(part_number=pn, quantity=qty if ok else 1))
    return out


def fault_in(code: str | None, texts: list[str]) -> bool:
    """Whether the fault code appears in any text, ignoring case and hyphens; False for None."""
    return bool(code) and any(ident_norm(code) in ident_norm(t) for t in texts)
