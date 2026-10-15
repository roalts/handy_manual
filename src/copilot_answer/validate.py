"""Deterministic citation validation (Principle II, FR-019..021, research R7).

A sentence passes when it cites at least one supplied, visible passage and every checkable token
in it (specification values, part numbers, fault codes, case numbers, asset IDs, serials, bulletin
and procedure IDs, withheld-value markers) appears in at least one of its cited passages, or in
the resolved asset record.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from copilot_answer.ids import (
    ASSET,
    BULLETIN,
    CAMPAIGN,
    CASE,
    FAULT,
    MODEL,
    PART,
    PROCEDURE,
    SERIAL,
    recognize,
)

UNVERIFIED = re.compile(r"\[\[unverified:[^\]|]+\|page=\d+\]\]")
# Evidence labels ("[P4]", "(P4, P7)", "[Passage 3]") belong in "cites", never in text a
# technician reads. A bracket must hold only labels, so "(P9.01)" or "(TP1)" are kept.
_LABEL = r"(?:P|Passage\s?)\d+"
LABELS = re.compile(rf"\s*[\[(]\s*{_LABEL}(?:\s*(?:,|;|/|and)\s*{_LABEL})*\s*[\])]")


def strip_labels(text: str) -> str:
    """Text without evidence labels, tidying the spaces and punctuation left behind."""
    t, n = LABELS.subn("", text)
    if not n:
        return text
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()

_NUM = r"\d+(?:[.,]\d+)*"
_UNIT = (r"(?:mm|cm|bar|psi|kpa|mpa|n\s?[·.\-]?\s?m|v\s?dc|v\s?ac|kw|kva|hz|rpm|1/min|"
         r"hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|sec|s|°\s?c|deg\s?c|c|%|kg|g|"
         r"litres?|liters?|l|m³/h|m3/h|megohms?|mω|mohm|ohms?|Ω|months?|weeks?|days?|years?|"
         r"v|a|m)")
VALUE = re.compile(rf"(?<![\w.]){_NUM}(?:\s?(?:-|–|—|to)\s?{_NUM})?\s?{_UNIT}(?![a-zA-Z0-9])",
                   re.I)
DECIMAL = re.compile(r"(?<![\w.])\d+[.,]\d+(?![\w.])")

_UNIT_SUBS = [
    (r"(\d)\s*n\s*[·.\-]?\s*m(?![a-z])", r"\1nm"),
    (r"(?<![a-z])n\s?[·\-]\s?m(?![a-z])", "nm"),
    (r"(\d)\s*(?:megohms?|mω|m\s?ohms?|mohm)(?![a-z])", r"\1mohm"),
    (r"(\d)\s*(?:°\s*|deg\s*)c(?![a-z])", r"\1c"),
    (r"(\d)\s*(?:hours?|hrs?|h)(?![a-z])", r"\1h"),
    (r"(\d)\s*(?:minutes?|mins?|min)(?![a-z])", r"\1min"),
    (r"(\d)\s*(?:seconds?|secs?|sec|s)(?![a-z])", r"\1s"),
    (r"(\d)\s*months?(?![a-z])", r"\1month"),
    (r"(\d)\s*weeks?(?![a-z])", r"\1week"),
    (r"(\d)\s*days?(?![a-z])", r"\1day"),
    (r"(\d)\s*years?(?![a-z])", r"\1year"),
    (r"(\d)\s*(?:litres?|liters?)(?![a-z])", r"\1l"),
    (r"(\d)\s*m3/h", r"\1m³/h"),
    (r"(\d)\s*v\s*dc(?![a-z])", r"\1vdc"),
    (r"(\d)\s*v\s*ac(?![a-z])", r"\1vac"),
]


def norm(text: str) -> str:
    """Normalization for value matching: case, dashes, units, separators, whitespace."""
    t = unicodedata.normalize("NFKC", text).casefold()
    t = re.sub(r"[‐‑‒–—−]", "-", t)
    for pat, rep in _UNIT_SUBS:
        t = re.sub(pat, rep, t)
    t = re.sub(r"(\d)\s*(?:-|to)\s*(\d)", r"\1-\2", t)
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"(\d),(\d{3})(?!\d)", r"\1\2", t)
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)
    t = re.sub(r"\s+", " ", t)
    return re.sub(r"(\d) (?=(?:mm|cm|bar|psi|kpa|mpa|kw|kva|hz|rpm|kg|g|l|m|a|v|c|%|mohm|vdc|"
                  r"vac|nm|h|min|s|month|week|day|year|m³/h)(?![a-z]))", r"\1", t)


def ident_norm(text: str) -> str:
    """Identifier normalization: casefold, no hyphens, single spaces."""
    t = re.sub(r"-", "", unicodedata.normalize("NFKC", text).casefold())
    return re.sub(r"\s+", " ", t)


def _has(token: str, haystack: str) -> bool:
    """Whether `token` occurs in `haystack` not as part of a longer number."""
    return re.search(rf"(?<![\d.]){re.escape(token)}(?!\d)", haystack) is not None


def _has_ident(token: str, haystack: str) -> bool:
    """Whether `token` occurs with no letter or digit before it and no digit after it."""
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![0-9])", haystack) is not None


# Sensor, test-point and component tags (TS-2, TP1, PI-01, EXV-2): short upper-case letters and
# a number, not part of a recognized identifier, not a decimal parameter (P9.01).
TAG = re.compile(r"(?<![\w.])[A-Z]{1,4}-?\d{1,3}(?![\w]|[.,]\d|-\d)")
_KNOWN = [ASSET, SERIAL, MODEL, FAULT, CASE, PART, BULLETIN, CAMPAIGN, PROCEDURE]

_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]
_MONTH = "|".join(_MONTHS)
ISO_DATE = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d])")
DAY_MONTH_YEAR = re.compile(rf"(?<!\d)(\d{{1,2}}) ({_MONTH}) (\d{{4}})(?!\d)", re.I)
MONTH_DAY_YEAR = re.compile(rf"\b({_MONTH}) (\d{{1,2}}),? (\d{{4}})(?!\d)", re.I)
# A date without its year ("the 07-01 cleanup", "on 07/01"). Month 01-09 only, so number ranges
# such as "10-12" are not read as dates.
MONTH_DAY = re.compile(r"(?<![\w./-])(0[1-9])[-/](0[1-9]|[12]\d|3[01])(?![\w/-]|[.,]\d)")


def tags(text: str) -> list[str]:
    """Sensor, test-point and component tags not inside a recognized identifier."""
    taken = [m.span() for pat in _KNOWN for m in pat.finditer(text)]
    return [m.group(0) for m in TAG.finditer(text)
            if not any(s < m.end() and m.start() < e for s, e in taken)]


def dates(text: str) -> list[tuple[int, int, int]]:
    """Calendar dates in a sentence as (year, month, day)."""
    out = [(int(y), int(m), int(d)) for y, m, d in ISO_DATE.findall(text)]
    out += [(int(y), _MONTHS.index(m.lower()) + 1, int(d))
            for d, m, y in DAY_MONTH_YEAR.findall(text)]
    out += [(int(y), _MONTHS.index(m.lower()) + 1, int(d))
            for m, d, y in MONTH_DAY_YEAR.findall(text)]
    return [x for x in dict.fromkeys(out) if 1 <= x[1] <= 12 and 1 <= x[2] <= 31]


def date_grounded(y: int, m: int, d: int, hay: str) -> bool:
    """A date written in the passage's own format (same rule as the evaluation harness): ISO,
    "28.07.2026", "28 July 2026", "July 28, 2026", "07/28/2026", or "07/28" / "7/28" when the
    year appears in the cited text (month first, as the NA exports write it)."""
    month = _MONTHS[m - 1]
    full = [f"{y}-{m:02d}-{d:02d}", f"{d:02d}.{m:02d}.{y}", f"{d}.{m}.{y}", f"{d} {month} {y}",
            f"{month} {d}, {y}", f"{month} {d} {y}", f"{m:02d}/{d:02d}/{y}", f"{m}/{d}/{y}"]
    if any(f in hay for f in full):
        return True
    return str(y) in hay and any(
        re.search(rf"(?<![\w./]){re.escape(s)}(?![\w/]|\.\d)", hay)
        for s in (f"{m:02d}/{d:02d}", f"{m}/{d}"))


def month_day_grounded(m: str, d: str, hay: str) -> bool:
    """A year-less date is grounded when the cited text has that month and day, alone or in a
    full date (ISO, "01.07.2026", "07/01/2026")."""
    return bool(re.search(rf"(?<![\d/]){m}[-/]{d}(?!\d)|(?<!\d){d}\.{m}\.\d{{4}}", hay))


def checkable(sentence: str) -> tuple[list[str], list[str], list[str]]:
    """(values, identifiers, unverified markers) to check in a sentence."""
    markers = UNVERIFIED.findall(sentence)
    text = UNVERIFIED.sub(" ", sentence)
    values = [m.group(0) for m in VALUE.finditer(text)]
    rest = VALUE.sub(" ", text)
    values += DECIMAL.findall(rest)
    rec = recognize(text)
    idents = [*rec.asset_ids, *rec.serials, *rec.fault_codes, *rec.case_numbers,
              *rec.part_numbers, *rec.bulletins, *rec.procedures, *CAMPAIGN.findall(text),
              *tags(text)]
    # Decimals inside identifiers (P9.01) are checked as values, which is stricter.
    return values, list(dict.fromkeys(idents)), markers


@dataclass
class Grounding:
    """The text a sentence may rely on: its cited passages plus the resolved asset record."""
    raw: str
    values: str = field(init=False)
    idents: str = field(init=False)

    def __post_init__(self) -> None:
        """Normalize the text once for value and identifier matching."""
        self.values = norm(self.raw)
        self.idents = ident_norm(self.raw)


def value_grounded(value: str, g: Grounding) -> bool:
    """Whether the value appears in the grounding; a range, or a number whose unit appears
    elsewhere (such as a table header), counts when its numbers do."""
    tok = norm(value)
    if _has(tok, g.values):
        return True
    m = re.match(r"^(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?(\D*)$", tok)
    if not m:
        return False
    lo, hi, unit = m.groups()
    nums = [n for n in (lo, hi) if n]
    if not all(_has(n, g.values) for n in nums):
        return False
    # Number present, unit given elsewhere in the passage (table header such as "Torque (N-m)").
    return not unit or unit in g.values


@dataclass
class Verdict:
    ok: bool
    missing: list[str] = field(default_factory=list)
    reason: str = ""


def check_sentence(text: str, cited: list[str], supplied: dict[str, str],
                   asset_record: str = "", typed: str = "") -> Verdict:
    """`supplied` maps passage ID to its full text (original + English) for passages given to
    the model and visible to the user. Tags the technician typed in `typed` (the question) may
    be repeated without a source."""
    good = [c for c in cited if c in supplied]
    if not good:
        return Verdict(False, reason="no citation to a supplied passage")
    g = Grounding("\n".join(supplied[c] for c in good) + "\n" + asset_record)
    values, idents, markers = checkable(text)
    own = {ident_norm(t) for t in tags(typed)}
    missing = [v for v in values if not value_grounded(v, g)]
    missing += [i for i in idents
                if not _has_ident(ident_norm(i), g.idents) and ident_norm(i) not in own]
    missing += [m for m in markers if m not in g.raw]
    missing += [f"{y}-{m:02d}-{d:02d}" for y, m, d in dates(text)
                if not date_grounded(y, m, d, g.values)]
    missing += [f"{m}-{d}" for m, d in MONTH_DAY.findall(text)
                if not month_day_grounded(m, d, g.raw)]
    if missing:
        return Verdict(False, missing, "not in cited passages: " + ", ".join(missing))
    return Verdict(True)
