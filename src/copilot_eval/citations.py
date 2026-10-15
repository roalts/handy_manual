"""Citation validity (FR-006, US3), independent of the engine.

1. Every cited passage is fetched through `GET /api/sources/{id}` as the asking user and must
   return 200 (a 403 means the answer cites something the user can't see).
2. Every value in a sentence (number, part number, fault code, case number, identifier) must
   appear in one of that sentence's cited passages as returned by the API, or in the resolved
   asset record (answer.md guarantee 2). Numbers followed by a unit are matched with the unit.
"""
import re
from dataclasses import dataclass

from copilot_contracts import AnswerResponse
from copilot_eval.textnorm import contains, decimal_comma, norm

# A token holding a digit: 38, 0.38, 6000, 63-1180, E-31, P9.01, TP1, HCP350-241187,
# 2026-03-12, NK-C25-14, 00041988. A hyphenated word after it is not part of it ("6000-hour",
# "TS-2-versus-handheld"); short parts are ("TP1-PE").
_TOKEN = re.compile(r"(?<![\w.])(?:[a-z]+-?)*\d\w*(?:[-.:](?=\w*\d|[a-z]{1,3}(?!\w))\w+)*")
# "a" is amperes only when no word follows it, or a word that can't follow the article ("16 a at
# 400 v"): "on firmware 5.0 a failing TS-2" is the number 5.0.
_AMPS = (r"a(?![\w-])(?!\s+[a-z])|a(?=\s+(?:and|or|at|to|per|max|from|with|on|in|for|when|is|"
         r"are|was|were|rms)\b)")
_UNIT = re.compile(r"\s(mm|bar|n-m|mohm|kg|ppm|v dc|v ac|v|" + _AMPS + r"|h|s|min|minutes|"
                   r"seconds|hours|months|c|k|microns|%)\b")
# "under-5.1", "below-5.1.0": a plain word joined to a dotted number; the number is the value.
_WORD_ON_NUMBER = re.compile(r"^[a-z]{4,}-(?=\d+(?:\.\d+)+$)")
_UNIT_WORDS = {"minutes": "min", "seconds": "s", "hours": "h"}
_LABEL = re.compile(r"\[\s*p\d+(?:\s*,\s*p\d+)*\s*\]")


@dataclass(frozen=True)
class CitationFailure:
    rule: str
    """`hidden` (403), `missing` (404), `http` (other status), `value` (value not in sources),
    `label` (the engine's evidence labels, "[P4]", shown in the answer text)."""
    where: str
    detail: str


def values(text: str) -> list[str]:
    """Values a technician would act on, each with its unit when one follows."""
    s = norm(text)
    out = []
    for m in _TOKEN.finditer(s):
        tok = m.group(0).rstrip(".:/-")
        tok = _WORD_ON_NUMBER.sub("", tok, count=1)
        if not any(ch.isdigit() for ch in tok) or re.fullmatch(r"x\d+", tok):
            continue
        if re.fullmatch(r"\d", tok) and not _UNIT.match(s, m.end()):
            continue  # a bare count or circuit number ("circuit 2"), not a value
        unit = _UNIT.match(s, m.end()) if re.fullmatch(r"[\d.]+", tok) else None
        if unit:
            u = _UNIT_WORDS.get(unit.group(1), unit.group(1))
            out.append(f"{tok} {u}" if u != "%" else f"{tok}%")
        else:
            out.append(tok)
    return list(dict.fromkeys(out))


def _present(value: str, hay: str) -> bool:
    """`value` in `hay`, allowing the ways sources rewrite it: split code ranges, a word joined to
    a code, a date or time unit written another way."""
    if contains(hay, value):
        return True
    parts = value.split("-")
    if len(parts) > 1 and all(re.search(r"[a-z]", p) for p in parts):
        # "TP1-TP2" written as "TP1 and TP2"; never split a number ("63-1180") or a serial.
        return all(contains(hay, p) for p in parts)
    word = re.match(r"(?:[a-z]{3,}-)+(?=.*[a-z])(?=.*\d)", value)
    if word:
        # "repeated-E-14", "high-TS-2": a word joined to a code; the code must still be there.
        return _present(value[word.end():], hay)
    tail = re.search(r"(?:-[a-z]{3,})+$", value)
    if tail and re.search(r"\d", value[:tail.start()]):
        # "HCP350-240001-and-later": the code is "HCP350-240001".
        return _present(value[:tail.start()], hay)
    if date := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value):
        return _date_present(*(int(x) for x in date.groups()), hay)
    num, _, unit = value.partition(" ")
    if unit in ("min", "s", "h"):
        long = {"min": "minutes", "s": "seconds", "h": "hours"}[unit]
        return contains(hay, f"{num} {long}") or contains(hay, f"{num} {long[:-1]}")
    return False


_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]


def _date_present(y: int, m: int, d: int, hay: str) -> bool:
    """An ISO date written another way in the passage: "07/28" or "7/28" in a record of that
    year (month first, as the NA exports write it), "28.07.2026", "28 July 2026",
    "July 28, 2026"."""
    month = _MONTHS[m - 1] if 1 <= m <= 12 else ""
    full = [f"{d:02d}.{m:02d}.{y}", f"{d}.{m}.{y}", f"{d} {month} {y}", f"{month} {d}, {y}",
            f"{month} {d} {y}", f"{m:02d}/{d:02d}/{y}", f"{m}/{d}/{y}"]
    if any(contains(hay, f) for f in full):
        return True
    short = [f"{m:02d}/{d:02d}", f"{m}/{d}"]
    return contains(hay, str(y)) and any(
        re.search(rf"(?<![\w./]){re.escape(s)}(?![\w/]|\.\d)", hay) for s in short)


def asset_text(resp: AnswerResponse) -> str:
    """Normalized identifiers of the resolved asset, or "" when the response has none."""
    a = resp.asset
    return norm(f"{a.asset_id} {a.model} {a.serial} {a.firmware or ''} {a.site}") if a else ""


def check_values(resp: AnswerResponse, sources: dict[str, dict],
                 question: str = "") -> list[CitationFailure]:
    """`sources`: passage_id -> body of `GET /api/sources/{id}` (200 only). A passage's document
    title counts as part of it: "per SOP-020" citing a SOP-020 passage is grounded. Identifiers
    the technician typed ("pit PP-1") may be repeated; numbers and values never are exempt."""
    texts = {pid: norm(f"{b.get('title') or ''} rev {b.get('revision') or ''} "
                       f"{b.get('issue_date') or ''}\n{b.get('text_original') or ''}\n"
                       f"{b.get('text_en') or ''}") for pid, b in sources.items()}
    texts = {pid: t if (d := decimal_comma(t)) == t else f"{t}\n{d}" for pid, t in texts.items()}
    asset = asset_text(resp) + "\n" + " ".join(
        v for v in values(question) if re.search(r"[a-z]", v) and " " not in v)
    items = [(f"sentence {i}", "".join(g.text for g in s.segments if g.kind == "text"),
              s.citations) for i, s in enumerate(resp.sentences, 1)]
    items += [(f"conflict {i} side {j}", side.statement, side.citations)
              for i, c in enumerate(resp.conflicts, 1) for j, side in enumerate(c.sides, 1)]
    out = []
    for where, text, cites in items:
        if labels := _LABEL.findall(norm(text)):
            out.append(CitationFailure("label", where,
                                       f"evidence labels in the text: {', '.join(labels)}"))
            text = _LABEL.sub(" ", norm(text))
        hay = "\n".join(texts[c] for c in cites if c in texts) + "\n" + asset
        missing = [v for v in values(text) if not _present(v, hay)]
        if missing:
            out.append(CitationFailure("value", where,
                                       f"not in its cited passages: {', '.join(missing)}"))
    if w := resp.work_order_suggestion:
        hay = "\n".join(texts.values()) + "\n" + asset
        vals = [p.part_number for p in w.parts] + [v for v in (w.fault_code, w.campaign_code) if v]
        if w.asset_id:
            vals.append(w.asset_id)
        missing = [v for v in vals if not contains(hay, v)]
        if missing:
            out.append(CitationFailure("value", "work order",
                                       f"not in any cited passage: {', '.join(missing)}"))
    return out


def check(resp: AnswerResponse, fetch, question: str = ""
          ) -> tuple[list[CitationFailure], dict[str, dict]]:
    """`fetch(passage_id) -> (status, body)` as the asking user. Returns failures and the
    fetched sources (200 only)."""
    out: list[CitationFailure] = []
    fetched: dict[str, dict] = {}
    for pid in resp.citations:
        status, body = fetch(pid)
        if status == 200 and body.get("passage_id") == pid:
            fetched[pid] = body
        elif status == 403:
            out.append(CitationFailure("hidden", pid, "403 not_visible for the asking user"))
        elif status == 404:
            out.append(CitationFailure("missing", pid, "404: passage does not exist"))
        else:
            out.append(CitationFailure("http", pid, f"status {status}"))
    return out + check_values(resp, fetched, question), fetched
