"""Document metadata and bulletin applicability (US3).

Rules first: explicit cover lines, header cells and revision tables. A hosted model is asked only
for fields the rules cannot find, and its answers are kept only when the quoted text is an exact
(normalized) substring of the cited block and the value parses from that quote (research.md R7).
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from copilot_ingest.ids import sha256_bytes
from copilot_ingest.models import (
    Block,
    BulletinAsset,
    BulletinRule,
    ExtractResult,
    Relation,
    ReviewItem,
)
from copilot_ingest.providers.base import ProviderUnavailable
from copilot_ingest.review import Decisions

VERSION = "enrich-1"
PROMPT_METADATA = "metadata-1"
PROMPT_CONDITIONS = "bulletin-conditions-1"

# Document types whose revision and issue date matter for authority and supersession.
NEEDS_METADATA = {"bulletin", "service_manual", "controlled_procedure", "work_instruction"}


# --- normalization and parsers ----------------------------------------------------------------

def normalize(text: str) -> str:
    """NFKC, casefolded text with hyphenated line breaks joined and whitespace collapsed, for
    quote matching."""
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"-\s*\n\s*", "", text)  # hyphenated line breaks
    return re.sub(r"\s+", " ", text).strip().casefold()


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(text: str) -> date | None:
    """Unambiguous date forms only: ISO, '1 October 2024', 'Oct 14, 2025', EU 'DD-MM-YYYY'."""
    text = text.strip()
    if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        return _date(int(m[1]), int(m[2]), int(m[3]))
    if m := re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b", text):
        month = _MONTHS.get(m[2][:3].lower())
        return _date(int(m[3]), month, int(m[1])) if month else None
    if m := re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})\b", text):
        month = _MONTHS.get(m[1][:3].lower())
        return _date(int(m[3]), month, int(m[2])) if month else None
    if m := re.search(r"\b(\d{2})-(\d{2})-(\d{4})\b", text):
        return _date(int(m[3]), int(m[2]), int(m[1]))
    return None


def _date(y: int, m: int, d: int) -> date | None:
    """The date, or None if it does not exist (e.g. 31 February)."""
    try:
        return date(y, m, d)
    except ValueError:
        return None


_REV_TOKEN = r"([A-Z]|\d+(?:\.\d+)*)"
# A whole line that is only a revision statement, optionally with its date in brackets; prose
# such as "Rev E of the IOM is in preparation" does not match.
_REV_LINE = re.compile(rf"^(?:Revision|Rev\.?|Issue|Version)\s+{_REV_TOKEN}"
                       r"\s*(?:\(\s*\d{4}-\d{2}-\d{2}\s*\))?$")
_REV_INLINE = re.compile(rf"\b(?:Revision|Rev\.?|Issue)\s+{_REV_TOKEN}(?![\w-])")


def parse_revision(text: str) -> str | None:
    """Revision token from a revision-only line, else from an inline 'Rev X', or None."""
    m = _REV_LINE.search(text.strip()) or _REV_INLINE.search(text)
    return m.group(1) if m else None


PARSERS = {"revision": parse_revision, "issue_date": parse_date}


def verify(field_name: str, value: Any, quote: str, block_text: str) -> bool:
    """A model-supplied value counts only if its quote is in the block and the value parses from
    the quote."""
    q = normalize(quote)
    if len(q) < 4 or q not in normalize(block_text):
        return False
    parsed = PARSERS[field_name](quote)
    if parsed is None:
        return False
    if field_name == "issue_date":
        return isinstance(value, str) and parsed.isoformat() == value
    return str(parsed).casefold() == str(value).strip().casefold()


# --- metadata ---------------------------------------------------------------------------------

@dataclass
class Evidence:
    value: Any
    quote: str
    page: int | None
    source: str  # "properties", "cover", "revision_table", "page_metadata", "model"


@dataclass
class Metadata:
    fields: dict[str, Evidence] = field(default_factory=dict)
    replaces: Evidence | None = None  # "Replaces Rev. B, 2024-02"
    review: list[ReviewItem] = field(default_factory=list)


_DATE_LINE = re.compile(r"^(?:Issue date|Effective date|Date)(?:\s*/\s*[^\d\s]+)?\s+(.+)$", re.I)
_REPLACES = re.compile(rf"^(?:Replaces|Supersedes)\s+(?:Rev\.?|Revision|Issue)\s*{_REV_TOKEN}\b")


def _lines(b: Block) -> list[str]:
    """Non-empty lines of a block; for tables, its non-empty header and body cells."""
    if b.type == "table":
        cells = [c for row in [b.header or [], *(b.rows or [])] for c in row]
        return [c for c in cells if c]
    return [line for line in b.text.splitlines() if line.strip()]


def _cover_blocks(r: ExtractResult) -> list[Block]:
    """Blocks where cover metadata appears: the first two pages of a PDF, else the first 40."""
    if r.extractor in ("pdf", "pdf_thread"):
        return [b for b in r.blocks if (b.anchor.page or 1) <= 2]
    return r.blocks[:40]


def _revision_table(r: ExtractResult) -> tuple[str, date | None, str, int | None] | None:
    """Last row of a revision record table (header 'Rev'/'Rev.' plus a date column)."""
    for b in reversed(r.blocks):
        if b.type != "table" or not b.header or not b.rows:
            continue
        head = [h.strip().rstrip(".").casefold() for h in b.header]
        if head[0] not in ("rev", "revision") or not any("date" in h for h in head):
            continue
        row = b.rows[-1]
        dcol = next(i for i, h in enumerate(head) if "date" in h)
        rev = row[0].strip()
        if re.fullmatch(_REV_TOKEN, rev):
            return rev, parse_date(row[dcol]), " | ".join(row), b.anchor.page
    return None


def rule_metadata(r: ExtractResult, properties: dict) -> Metadata:
    """Revision, issue date and 'Replaces' line found by rules. Sources in priority order:
    property table, cover lines, revision table, page furniture, page metadata."""
    md = Metadata()
    if properties.get("revision"):
        md.fields["revision"] = Evidence(properties["revision"], "document property table", None,
                                         "properties")
    if properties.get("issue_date"):
        md.fields["issue_date"] = Evidence(properties["issue_date"], "document property table",
                                           None, "properties")
    for b in _cover_blocks(r):
        for line in _lines(b):
            if "revision" not in md.fields and (m := _REV_LINE.match(line.strip())):
                md.fields["revision"] = Evidence(m.group(1), line.strip(), b.anchor.page, "cover")
                if (d := parse_date(line)) and "issue_date" not in md.fields:
                    md.fields["issue_date"] = Evidence(d, line.strip(), b.anchor.page, "cover")
            if "issue_date" not in md.fields and (m := _DATE_LINE.match(line.strip())):
                if d := parse_date(m.group(1)):
                    md.fields["issue_date"] = Evidence(d, line.strip(), b.anchor.page, "cover")
            if "revision" not in md.fields and (m := re.search(
                    rf"\bIssue\s+{_REV_TOKEN},\s*(.+)$", line)):
                md.fields["revision"] = Evidence(m.group(1), line.strip(), b.anchor.page, "cover")
                if (d := parse_date(m.group(2))) and "issue_date" not in md.fields:
                    md.fields["issue_date"] = Evidence(d, line.strip(), b.anchor.page, "cover")
            if md.replaces is None and (m := _REPLACES.match(line.strip())):
                md.replaces = Evidence(m.group(1), line.strip(), b.anchor.page, "cover")
    if not {"revision", "issue_date"} <= md.fields.keys() and (t := _revision_table(r)):
        rev, d, quote, page = t
        md.fields.setdefault("revision", Evidence(rev, quote, page, "revision_table"))
        if d:
            md.fields.setdefault("issue_date", Evidence(d, quote, page, "revision_table"))
    for line in r.flags.get("page_furniture", []):
        if "revision" not in md.fields and (m := _REV_INLINE.search(line)):
            md.fields["revision"] = Evidence(m.group(1), line, None, "page_furniture")
    meta = r.flags.get("page_metadata") or ""
    if "issue_date" not in md.fields and (m := re.search(r"last modified on (.+)$", meta)):
        if d := parse_date(m.group(1)):
            md.fields["issue_date"] = Evidence(d, meta, None, "page_metadata")
    return md


_METADATA_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["fields"],
    "properties": {"fields": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["field", "value", "quote", "block_id"],
        "properties": {
            "field": {"type": "string", "enum": ["revision", "issue_date"]},
            "value": {"type": "string",
                      "description": "revision token (e.g. C, 3) or ISO date YYYY-MM-DD"},
            "quote": {"type": "string", "description": "exact text copied from the block"},
            "block_id": {"type": "string"},
        }}}},
}


def _numbered(blocks: list[Block], limit_chars: int = 8000) -> tuple[str, dict[str, Block]]:
    """Non-empty blocks as '[bN] text' lines for a prompt, plus the ID-to-block map. Stops after
    the block that passes `limit_chars`."""
    out, ids, size = [], {}, 0
    for i, b in enumerate(blocks):
        text = b.text.strip()
        if not text:
            continue
        bid = f"b{i}"
        ids[bid] = b
        out.append(f"[{bid}] {text}")
        size += len(text)
        if size > limit_chars:
            break
    return "\n".join(out), ids


def model_metadata(r: ExtractResult, md: Metadata, missing: list[str], provider, model: str,
                   path: str, decisions: Decisions | None) -> None:
    """Ask the model for missing fields; keep only verified answers, else raise review items."""
    blocks = _cover_blocks(r)
    text, ids = _numbered(blocks)
    answers: dict[str, dict] = {}
    if text and provider is not None and model:
        prompt = (
            "From the document excerpt below, report the document's own revision and issue date "
            "if the text states them. Copy the quote exactly from one block and give that block's "
            "ID. Do not infer, do not use dates of other documents, leave a field out if the text "
            f"does not state it.\nFields wanted: {', '.join(missing)}\n\n{text}")
        try:
            out = provider.complete_json(model, prompt, _METADATA_SCHEMA, PROMPT_METADATA)
            answers = {a["field"]: a for a in out.get("fields", []) if a["field"] in missing}
        except ProviderUnavailable:
            answers = {}
    for name in missing:
        a = answers.get(name)
        block = ids.get(a["block_id"]) if a else None
        if a and block and verify(name, a["value"], a["quote"], block.text):
            value = parse_date(a["quote"]) if name == "issue_date" else parse_revision(a["quote"])
            md.fields[name] = Evidence(value, a["quote"], block.anchor.page, "model")
            continue
        item = ReviewItem(kind="metadata_unverified", path=path, field=name,
                          candidates={"model_answer": a} if a else None,
                          reason=("model answer failed quote verification" if a
                                  else "not found in the document text"),
                          fingerprint=r.fingerprint, stage="enrich")
        decided = decisions.get(item) if decisions else None
        if decided:
            value = parse_date(str(decided)) if name == "issue_date" else str(decided)
            md.fields[name] = Evidence(value, "reviewer", None, "reviewer")
        else:
            md.review.append(item)


# --- bulletin applicability --------------------------------------------------------------------

_SERIAL = r"[A-Z]{2,4}\d{2,3}-\d{6}"


def parse_serial_range(text: str) -> tuple[str | None, str | None] | None:
    """'A to B', 'A and later', 'all'. Returns None if the cell is not a range."""
    t = text.strip()
    if re.fullmatch(r"all\b.*", t, re.I):
        return None, None
    if m := re.match(rf"({_SERIAL})\s+(?:to|-|–)\s+({_SERIAL})", t):
        return m[1], m[2]
    if m := re.match(rf"({_SERIAL})\s+and later", t, re.I):
        return m[1], None
    if m := re.match(rf"from\s+({_SERIAL})", t, re.I):
        return m[1], None
    return None


def _outcome(text: str) -> tuple[str, str | None]:
    """(outcome, campaign code) from an applicability cell; anything unrecognised is affected."""
    t = text.strip()
    if m := re.search(r"\bin campaign\s+([A-Z0-9][A-Z0-9-]+)", t, re.I):
        return "in_campaign", m[1]
    if re.search(r"\b(not affected|no action|unchanged)\b", t, re.I):
        return "not_affected", None
    return "affected", None


def _applicability_tables(r: ExtractResult) -> list[Block]:
    """Tables whose first column is 'Model' and that have a serial column."""
    out = []
    for b in r.blocks:
        if b.type != "table" or not b.header or not b.rows:
            continue
        head = [h.strip().casefold() for h in b.header]
        if head and head[0] == "model" and any("serial" in h for h in head):
            out.append(b)
    return out


def bulletin_rules(r: ExtractResult, doc_id: str) -> list[BulletinRule]:
    """One rule per applicability-table row with a serial range; the last column is the outcome.
    Rows with a different cell count or no parseable range are skipped."""
    rules = []
    for t in _applicability_tables(r):
        head = [h.strip().casefold() for h in t.header]
        col = {"serial": next(i for i, h in enumerate(head) if "serial" in h)}
        for i, h in enumerate(head):
            if "firmware" in h:
                col["firmware"] = i
            elif h in ("market", "region"):
                col["market"] = i
        outcome_col = len(head) - 1
        for row in t.rows:
            if len(row) != len(head):
                continue
            rng = parse_serial_range(row[col["serial"]])
            if rng is None:
                continue
            outcome, code = _outcome(row[outcome_col])
            market = row[col["market"]].strip() if "market" in col else None
            firmware = row[col["firmware"]].strip() if "firmware" in col else None
            quote = " | ".join(row)
            rules.append(BulletinRule(
                rule_id="br_" + sha256_bytes(f"{doc_id}|{quote}".encode())[:16], doc_id=doc_id,
                model=row[0].strip().upper(), serial_from=rng[0], serial_to=rng[1],
                firmware_condition=firmware if firmware and firmware.lower() != "all" else None,
                market_condition=market if market and market.lower() != "all" else None,
                outcome=outcome, campaign_code=code, action_summary=row[outcome_col].strip(),
                quote=quote, page=t.anchor.page))
    return rules


@dataclass
class Condition:
    """A condition the bulletin states outside its table, e.g. a retrofit on earlier units."""
    model: str
    serial_from: str | None
    serial_before: str | None  # exclusive
    outcome_if_met: str
    quote: str
    page: int | None


_CONDITIONS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["conditions"],
    "properties": {"conditions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["model", "serial_from", "serial_before", "outcome_if_met", "quote",
                     "block_id"],
        "properties": {
            "model": {"type": "string"},
            "serial_from": {"type": ["string", "null"],
                            "description": "first serial the condition can apply to, inclusive"},
            "serial_before": {"type": ["string", "null"],
                              "description": "serial the condition applies below, exclusive"},
            "outcome_if_met": {"type": "string",
                               "enum": ["affected", "not_affected", "in_campaign"]},
            "quote": {"type": "string", "description": "exact sentence copied from the block"},
            "block_id": {"type": "string"},
        }}}},
}


def bulletin_conditions(r: ExtractResult, rules: list[BulletinRule], provider,
                        model: str) -> tuple[list[Condition], list[str]]:
    """Conditions on hardware state the fleet register does not hold (FR-024), such as a retrofit
    that brings earlier serials into scope. Kept only if the quote is in the cited block and
    states its serial bound verbatim; they can only widen scope, never clear a unit."""
    if not rules or provider is None or not model:
        return [], []
    text, ids = _numbered([b for b in r.blocks if b.type != "table"])
    table = "\n".join(f"- {x.model} {x.serial_from or 'any'} to {x.serial_to or 'any'}: "
                      f"{x.action_summary}" for x in rules)
    prompt = (
        "This is a service bulletin. Its applicability table was parsed as:\n"
        f"{table}\n\n"
        "List only conditions stated in the text that change whether a unit is affected and that "
        "depend on the unit's physical state or history rather than its model, serial number, "
        "firmware or market (for example: a part fitted later, a retrofit, a modification). "
        "Copy the quote exactly from one block. Give serial bounds only if the quote states them "
        "verbatim. Return an empty list if there are none.\n\n" + text)
    try:
        out = provider.complete_json(model, prompt, _CONDITIONS_SCHEMA, PROMPT_CONDITIONS)
    except ProviderUnavailable as e:
        return [], [f"conditions not checked: {e}"]
    kept, notes = [], []
    for c in out.get("conditions", []):
        block = ids.get(c["block_id"])
        bound = quoted_serial_bound(c["quote"])
        if not block or normalize(c["quote"]) not in normalize(block.text):
            notes.append(f"rejected, quote not in source: {c['quote'][:80]!r}")
        elif bound is None or c["outcome_if_met"] == "not_affected":
            notes.append(f"ignored, no serial scope stated: {c['quote'][:80]!r}")
        else:
            kept.append(Condition(model=c["model"].strip().upper(), serial_from=bound[0],
                                  serial_before=bound[1], outcome_if_met=c["outcome_if_met"],
                                  quote=c["quote"], page=block.anchor.page))
    return kept, notes


def quoted_serial_bound(quote: str) -> tuple[str | None, str | None] | None:
    """(serial_from, serial_before) as stated in the quote itself; the model's own serial fields
    are not trusted."""
    if m := re.search(rf"\b(?:before|earlier than|below|prior to)\s+(?:serial\s+)?({_SERIAL})",
                      quote, re.I):
        return None, m[1]
    if m := re.search(rf"\bfrom\s+(?:serial\s+)?({_SERIAL})", quote, re.I):
        return m[1], None
    return None


def condition_rules(conditions: list[Condition], doc_id: str) -> list[BulletinRule]:
    """Conditions become rules with a variant condition: evaluation turns them into
    check_on_site for units whose table outcome differs."""
    out = []
    for c in conditions:
        serial_to = None
        if c.serial_before and (m := re.match(r"(.*-)(\d+)$", c.serial_before)):
            serial_to = f"{m[1]}{int(m[2]) - 1:0{len(m[2])}d}"
        out.append(BulletinRule(
            rule_id="br_" + sha256_bytes(f"{doc_id}|cond|{c.quote}".encode())[:16],
            doc_id=doc_id, model=c.model, serial_from=c.serial_from, serial_to=serial_to,
            variant_condition=c.quote, outcome=c.outcome_if_met, action_summary=None,
            quote=c.quote, page=c.page))
    return out


# --- evaluation against the fleet register -----------------------------------------------------

def _serial_key(serial: str) -> tuple[str, int] | None:
    """(prefix, number) of a serial for ordering, or None if it has another shape."""
    m = re.fullmatch(r"([A-Z0-9]+)-(\d+)", serial.strip().upper())
    return (m[1], int(m[2])) if m else None


def _in_serial_range(serial: str, rule: BulletinRule) -> bool | None:
    """Whether the serial is inside the rule's inclusive range; None if the serial does not
    parse or its prefix differs from the bounds'."""
    s = _serial_key(serial)
    lo = _serial_key(rule.serial_from) if rule.serial_from else None
    hi = _serial_key(rule.serial_to) if rule.serial_to else None
    if s is None or (lo and lo[0] != s[0]) or (hi and hi[0] != s[0]):
        return None
    return (lo is None or s[1] >= lo[1]) and (hi is None or s[1] <= hi[1])


def _version(text: str) -> tuple[int, ...] | None:
    """Dotted version as an int tuple, or None if not purely numeric."""
    m = re.fullmatch(r"\d+(?:\.\d+)*", text.strip())
    return tuple(int(p) for p in m[0].split(".")) if m else None


def firmware_matches(asset_fw: str | None, condition: str | None) -> bool | None:
    """'4.x', '5.0.0 to 5.0.3', '5.1.0'. Compared at the precision the fleet register holds, so
    '5.0' is inside '5.0.0 to 5.0.3'. None when it cannot be decided."""
    if condition is None:
        return True
    fw = _version(asset_fw or "")
    if fw is None:
        return None
    c = condition.strip().lower()
    if m := re.fullmatch(r"(\d+(?:\.\d+)*)\.x", c):
        prefix = _version(m[1])
        return fw[:len(prefix)] == prefix
    if m := re.fullmatch(r"(\S+)\s+(?:to|-|–)\s+(\S+)", c):
        lo, hi = _version(m[1]), _version(m[2])
        if lo is None or hi is None:
            return None
        n = len(fw)
        return lo[:n] <= fw <= hi[:n]
    if (v := _version(c)) is not None:
        n = min(len(fw), len(v))
        return fw[:n] == v[:n]
    return None


def market_matches(region: str | None, condition: str | None) -> bool | None:
    """'EU', 'outside EU', 'NA' against the asset's region. None when it cannot be decided."""
    if condition is None:
        return True
    c = condition.strip().lower()
    if not region:
        return None
    if re.fullmatch(r"outside (the )?eu.*", c):
        return region.upper() != "EU"
    if re.fullmatch(r"(eu|europe)\b.*", c):
        return region.upper() == "EU"
    if re.fullmatch(r"(na|north america)\b.*", c):
        return region.upper() == "NA"
    return None


def _max_firmware(rules: list[BulletinRule]) -> tuple[tuple[int, ...], BulletinRule] | None:
    """Highest firmware version any rule names, with its rule ('4.x' counts as 4.999)."""
    best = None
    for r in rules:
        if not r.firmware_condition:
            continue
        top = r.firmware_condition.split()[-1].replace(".x", ".999")
        if (v := _version(top)) and (best is None or v > best[0]):
            best = (v, r)
    return best


def evaluate(rules: list[BulletinRule], assets: list, doc_id: str,
             partial: bool) -> list[BulletinAsset]:
    """One status per fleet unit of a model the bulletin names (FR-024). Conditions the register
    cannot decide and partially recovered bulletins never yield not_affected."""
    table = [r for r in rules if r.variant_condition is None]
    conditions = [r for r in rules if r.variant_condition is not None]
    models = {r.model for r in rules}
    out = []
    for a in assets:
        if a.model.upper() not in models:
            continue
        mine = [r for r in table if r.model == a.model.upper()]
        status, rule, reason = "check_on_site", None, "no applicability row matches this unit"
        undecided = []
        for r in mine:
            checks = (_in_serial_range(a.serial, r), firmware_matches(a.firmware,
                      r.firmware_condition), market_matches(a.region, r.market_condition))
            if all(c is True for c in checks):
                status, rule = r.outcome, r
                reason = f"matches row: {r.quote}"
                break
            if None in checks and False not in checks:
                undecided.append(r)
        if rule is None and undecided:
            reason = f"cannot decide from fleet register: {undecided[0].quote}"
        if rule is None and not undecided and (top := _max_firmware(mine)):
            fw = _version(a.firmware or "")
            in_band = all(_in_serial_range(a.serial, r) is not False for r in [top[1]])
            if fw and fw > top[0][:len(fw)] and in_band and top[1].outcome == "not_affected":
                status, rule = "not_affected", top[1]
                reason = (f"firmware {a.firmware} is newer than every version the bulletin lists; "
                          f"highest row: {top[1].quote}")
        for c in conditions:
            if c.model != a.model.upper() or _in_serial_range(a.serial, c) is not True:
                continue
            if status == "not_affected":
                status, rule = "check_on_site", c
                reason = f"depends on the unit's hardware: {c.variant_condition}"
        if partial and status == "not_affected":
            status = "check_on_site"
            reason = "bulletin only partially recovered; " + reason
        out.append(BulletinAsset(doc_id=doc_id, asset_id=a.asset_id, status=status,
                                 rule_id=rule.rule_id if rule else None, reason=reason))
    return out


# --- supersession and staleness ---------------------------------------------------------------

REVISIONED_TYPES = {"service_manual", "controlled_procedure", "work_instruction"}


def supersessions(docs: dict, md: dict[str, Metadata]) -> list[Relation]:
    """Newer revision supersedes older revision of the same document type for the same models.
    An explicit 'Replaces Rev. X' line is the quote when present."""
    out = []
    by_key: dict[tuple, list] = {}
    for d in docs.values():
        if d.doc_type in REVISIONED_TYPES and d.models and d.issue_date:
            by_key.setdefault((d.doc_type, tuple(sorted(d.models))), []).append(d)
    for group in by_key.values():
        group.sort(key=lambda d: d.issue_date)
        for older, newer in zip(group, group[1:], strict=False):
            if older.issue_date == newer.issue_date:
                continue
            ev = md.get(newer.doc_id)
            quote, page = None, None
            if ev and ev.replaces and older.revision and \
                    ev.replaces.value.casefold() == older.revision.casefold():
                quote, page = ev.replaces.quote, ev.replaces.page
            elif ev and "revision" in ev.fields:
                quote, page = ev.fields["revision"].quote, ev.fields["revision"].page
            out.append(Relation(from_doc=newer.doc_id, to_doc=older.doc_id,
                                relation="supersedes", quote=quote, page=page))
    return out


_SPEC_VALUE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:h|hours?|L|litres?|liters?|bar|°C|N-?m|Nm|kg|mm|kW|rpm|months?)"
    r"(?![\w-])", re.I)
STALE_TOPIC_SIMILARITY = 0.55
INFORMAL_TIER = 4  # wiki and below


def _cos(a, b) -> float:
    """Cosine similarity; 0.0 for a zero vector."""
    num = sum(x * y for x, y in zip(a, b, strict=True))
    den = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    return num / den if den else 0.0


@dataclass
class Stale:
    passage_id: str
    newer_doc: str
    score: float | None  # None when embeddings were unavailable


def possibly_stale(docs: dict, passages: dict, embeddings: dict) -> list[Stale]:
    """Informal passages stating a spec value for a model, where a more authoritative document
    for that model is newer and covers the same topic (FR-022)."""
    newer_by_model: dict[str, list] = {}
    for d in docs.values():
        if 1 <= d.authority_tier < INFORMAL_TIER and d.status != "superseded" and d.issue_date:
            for m in d.models:
                newer_by_model.setdefault(m, []).append(d)
    by_doc: dict[str, list] = {}
    for p in passages.values():
        by_doc.setdefault(p.doc_id, []).append(p)
    out = []
    for p in passages.values():
        d = docs[p.doc_id]
        models = p.models or d.models
        if d.authority_tier < INFORMAL_TIER or not d.issue_date or not models:
            continue
        if not _SPEC_VALUE.search(p.text_original):
            continue
        best: Stale | None = None
        for m in models:
            for n in newer_by_model.get(m, []):
                if n.issue_date <= d.issue_date:
                    continue
                if p.passage_id not in embeddings:
                    best = best or Stale(p.passage_id, n.doc_id, None)
                    continue
                scores = [_cos(embeddings[p.passage_id], embeddings[q.passage_id])
                          for q in by_doc.get(n.doc_id, []) if q.passage_id in embeddings]
                score = max(scores, default=0.0)
                if score >= STALE_TOPIC_SIMILARITY and (best is None or (best.score or 0) < score):
                    best = Stale(p.passage_id, n.doc_id, score)
        if best:
            out.append(best)
    return out


def iso(d: date | datetime | None) -> str | None:
    """ISO string, or None for no date."""
    return d.isoformat() if d else None
