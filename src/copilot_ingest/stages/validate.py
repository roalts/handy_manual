"""Validation gate (FR-036): structural checks plus acceptance facts. Errors block publishing."""
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from copilot_ingest.acl import AccessRules, can_see
from copilot_ingest.models import ExtractResult
from copilot_ingest.settings import PROJECT_ROOT
from copilot_ingest.stages.index import Dataset

FACTS_PATH = PROJECT_ROOT / "acceptance" / "ingestion_facts.yaml"


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    severity: str = "error"  # "error" blocks publishing, "warning" does not


@dataclass
class Context:
    conn: object
    schema: str
    ds: Dataset
    rules: AccessRules
    extracts: dict[str, ExtractResult]  # path -> extract
    quarantined: dict[str, str]  # path -> reason
    open_review: list[dict] = field(default_factory=list)
    embeddings_expected: bool = True

    def doc_for_path(self, path: str) -> str | None:
        """The document with this path among its origins, or None."""
        for d in self.ds.documents.values():
            if any(o["path"] == path for o in d.origins):
                return d.doc_id
        return None

    def q(self, sql: str, params=()) -> list[tuple]:
        """Run `sql` with `{s}` replaced by the dataset schema; return all rows."""
        return self.conn.execute(sql.replace("{s}", self.schema), params).fetchall()


CHECKS: list[tuple[str, Callable[[Context], CheckResult]]] = []


def check(name: str):
    """Register the decorated function as a validation check under `name`."""
    def deco(fn):
        """Append to CHECKS and return the function unchanged."""
        CHECKS.append((name, fn))
        return fn
    return deco


def _result(name: str, bad: list, what: str, severity: str = "error") -> CheckResult:
    """Passed if `bad` is empty, else failed with the count and the first five offenders."""
    if bad:
        return CheckResult(name, False, f"{len(bad)} {what}: {bad[:5]}", severity)
    return CheckResult(name, True, "", severity)


# --- US1 ------------------------------------------------------------------------------------

@check("objects_have_access_alternatives")
def _objects_have_access(c: Context) -> CheckResult:
    """Every passage, document and event has at least one access alternative."""
    bad = c.q("""
        SELECT 'passage', passage_id FROM {s}.passages p WHERE NOT EXISTS (
            SELECT 1 FROM {s}.access_alternatives a
            WHERE a.object_type = 'passage' AND a.object_id = p.passage_id)
        UNION ALL
        SELECT 'document', doc_id FROM {s}.documents d WHERE NOT EXISTS (
            SELECT 1 FROM {s}.access_alternatives a
            WHERE a.object_type = 'document' AND a.object_id = d.doc_id)
        UNION ALL
        SELECT 'event', event_id FROM {s}.service_events e WHERE NOT EXISTS (
            SELECT 1 FROM {s}.access_alternatives a
            WHERE a.object_type = 'event' AND a.object_id = e.event_id)""")
    return _result("objects_have_access_alternatives", bad, "objects without access")


@check("passage_access_matches_rules")
def _passage_access(c: Context) -> CheckResult:
    """Stored passage alternatives equal those recomputed from origins or events plus the
    passage's restricted groups."""
    stored: dict[str, set[tuple]] = {}
    for oid, groups in c.q("SELECT object_id, required_groups FROM {s}.access_alternatives"
                           " WHERE object_type = 'passage'"):
        stored.setdefault(oid, set()).add(tuple(sorted(groups)))
    events = {e.event_id: e for e in c.ds.events}
    bad = []
    for pid, p in c.ds.passages.items():
        if pid in c.ds.event_passages:
            base = events[c.ds.event_passages[pid]].required_groups
        else:
            base = [o["required_groups"] for o in c.ds.documents[p.doc_id].origins]
        expected = {tuple(sorted(set(b) | set(p.restricted_groups))) for b in base}
        if stored.get(pid) != expected:
            bad.append(pid)
    return _result("passage_access_matches_rules", bad, "passages with wrong alternatives")


@check("no_quarantined_content")
def _no_quarantined(c: Context) -> CheckResult:
    """No quarantined path appears as a document origin."""
    paths = list(c.quarantined)
    bad = c.q("SELECT path FROM {s}.document_origins WHERE path = ANY(%s)", (paths,))
    return _result("no_quarantined_content", [r[0] for r in bad], "quarantined paths indexed")


@check("children_have_parents")
def _children(c: Context) -> CheckResult:
    """Every child passage points at an existing passage whose role is parent."""
    bad = c.q("""SELECT c.passage_id FROM {s}.passages c
                 LEFT JOIN {s}.passages p ON p.passage_id = c.parent_passage_id
                 WHERE c.role = 'child' AND (p.passage_id IS NULL OR p.role <> 'parent')""")
    return _result("children_have_parents", [r[0] for r in bad], "orphan child passages")


@check("passages_traceable")
def _traceable(c: Context) -> CheckResult:
    """Every passage has an anchor, fingerprint, extractor version and non-blank text."""
    bad = c.q("""SELECT passage_id FROM {s}.passages
                 WHERE anchor = '{{}}'::jsonb OR fingerprint = '' OR extractor_version = ''
                    OR length(trim(text_original)) = 0""".replace("{{}}", "{}"))
    return _result("passages_traceable", [r[0] for r in bad], "passages without source location")


@check("table_passages_have_headers")
def _tables(c: Context) -> CheckResult:
    """A passage holding any row of an extracted table also holds that table's header line."""
    bad = []
    by_doc: dict[str, list] = {}
    for p in c.ds.passages.values():
        by_doc.setdefault(p.doc_id, []).append(p)
    for path, r in c.extracts.items():
        doc_id = c.doc_for_path(path)
        if doc_id is None:
            continue
        for b in r.blocks:
            if b.type != "table" or not b.header or not b.rows:
                continue
            header = " | ".join(b.header)
            rows = {" | ".join(row) for row in b.rows if any(row)}
            for p in by_doc.get(doc_id, []):
                lines = set(p.text_original.split("\n"))
                if rows & lines and header not in lines:
                    bad.append(f"{path}#{p.passage_id}")
    return _result("table_passages_have_headers", sorted(set(bad)),
                   "passages with table rows but no header")


@check("procedures_not_split")
def _procedures(c: Context) -> CheckResult:
    """Every numbered procedure step block lives in a parent or standard passage."""
    bad = []
    for path, r in c.extracts.items():
        doc_id = c.doc_for_path(path)
        if doc_id is None:
            continue
        whole = [p.text_original for p in c.ds.passages.values()
                 if p.doc_id == doc_id and p.role in ("parent", "standard")]
        for b in r.blocks:
            if b.type == "procedure_step" and not any(b.text in t for t in whole):
                bad.append(f"{path}: {b.text[:40]}")
    return _result("procedures_not_split", bad, "steps only found in child passages")


@check("page_coverage")
def _coverage(c: Context) -> CheckResult:
    """FR-008: every page has extracted blocks or an explicit reason why not."""
    bad = []
    for path, r in c.extracts.items():
        if r.extractor != "pdf":
            continue
        pages_with_blocks = {b.anchor.page for b in r.blocks}
        for p in r.pages:
            if p.status == "text" and p.page not in pages_with_blocks:
                bad.append(f"{path} p{p.page}")
    return _result("page_coverage", bad, "text pages without blocks")


_MARKER = re.compile(r"\[\[unverified:(r_[0-9a-f]+)\|page=\d+\]\]")


@check("ocr_passages_marked")
def _ocr_marked(c: Context) -> CheckResult:
    """Passages from OCR'd pages say so and point at the page image."""
    ocr_pages = {c.doc_for_path(path): set(r.flags["ocr_pages"])
                 for path, r in c.extracts.items() if r.flags.get("ocr_pages")}
    bad = []
    for p in c.ds.passages.values():
        if p.anchor.page not in ocr_pages.get(p.doc_id, ()):
            continue
        has_marker = bool(_MARKER.search(p.text_original))
        if p.ocr == "none" or not p.page_image or has_marker != (p.ocr == "has_withheld_values"):
            bad.append(p.passage_id)
    return _result("ocr_passages_marked", bad, "OCR passages without status or page image")


@check("withheld_values_stay_withheld")
def _withheld(c: Context) -> CheckResult:
    """SC-004: every withheld value has an open review item, and no English text drops a marker
    or restores a value."""
    open_ids = {i["item_id"] for i in c.open_review if i["kind"] == "ocr_value_mismatch"}
    bad = []
    for p in c.ds.passages.values():
        markers = _MARKER.findall(p.text_original)
        bad += [f"{p.passage_id}: {m} not in review queue" for m in markers if m not in open_ids]
        if p.text_en is not None and _MARKER.findall(p.text_en) != markers:
            bad.append(f"{p.passage_id}: English text changes the withheld markers")
    return _result("withheld_values_stay_withheld", bad, "withheld-value problems")


@check("partial_documents_list_pages")
def _partial(c: Context) -> CheckResult:
    """Every partial document lists its missing pages."""
    bad = [d.doc_id for d in c.ds.documents.values()
           if d.status == "partial" and not d.missing_pages]
    return _result("partial_documents_list_pages", bad, "partial documents without missing pages")


@check("visibility_matches_rules")
def _visibility(c: Context) -> CheckResult:
    """SC-001: per user, visible documents equal those the access rules allow."""
    bad = []
    path_to_doc = {o["path"]: d.doc_id for d in c.ds.documents.values() for o in d.origins}
    for user, groups in c.rules.users.items():
        visible = {r[0] for r in c.q(
            """SELECT DISTINCT o.path FROM {s}.document_origins o
               JOIN {s}.access_alternatives a ON a.object_type = 'document'
                    AND a.object_id = o.doc_id
               WHERE a.required_groups <@ %s""", (groups,))}
        # a duplicate's paths are visible together when any copy is permitted
        expected_docs = {path_to_doc[p] for p, req in c.rules.documents.items()
                         if p in path_to_doc and can_see(req, groups)}
        expected = {p for p, d in path_to_doc.items() if d in expected_docs}
        if visible != expected:
            bad.append(f"{user}: +{sorted(visible - expected)} -{sorted(expected - visible)}")
    return _result("visibility_matches_rules", bad, "users with wrong visibility")


@check("embeddings_present")
def _embeddings(c: Context) -> CheckResult:
    """Every passage has an embedding; only a warning when embeddings were not expected."""
    missing = c.q("SELECT count(*) FROM {s}.passages WHERE embedding IS NULL")[0][0]
    total = c.q("SELECT count(*) FROM {s}.passages")[0][0]
    sev = "error" if c.embeddings_expected else "warning"
    if missing:
        return CheckResult("embeddings_present", False, f"{missing} of {total} passages have no"
                           " embedding; vector search will not find them", sev)
    return CheckResult("embeddings_present", True, "", sev)


# --- US2 ------------------------------------------------------------------------------------

@check("events_valid")
def _events_valid(c: Context) -> CheckResult:
    """Every service event has a date and a known status."""
    bad = c.q("""SELECT event_id FROM {s}.service_events WHERE event_date IS NULL
                 OR status NOT IN ('completed', 'open', 'cancelled')""")
    return _result("events_valid", [r[0] for r in bad], "events without date or status")


@check("event_assets_known")
def _event_assets(c: Context) -> CheckResult:
    """Events on assets missing from the fleet register are allowed only with an open
    unknown_asset review item."""
    flagged = set()
    for i in c.open_review:
        if i.get("kind") == "unknown_asset":
            cand = i.get("candidates") or {}
            flagged |= {str(v).upper() for v in cand.values() if isinstance(v, str)}
    rows = c.q("""SELECT e.event_id, e.asset_id FROM {s}.service_events e
                  WHERE NOT EXISTS (SELECT 1 FROM {s}.assets a WHERE a.asset_id = e.asset_id)""")
    bad = [r for r in rows if r[1] not in flagged]
    return _result("event_assets_known", bad, "events with unknown assets and no review item")


@check("events_not_double_counted")
def _double(c: Context) -> CheckResult:
    """No source record belongs to more than one event; 'references' links do not count."""
    keys = Counter()
    for e in c.ds.events:
        for s in e.sources:
            if s.get("relation") != "references":
                keys[(s["system"], s["record_id"])] += 1
    bad = [k for k, n in keys.items() if n > 1]
    return _result("events_not_double_counted", bad, "source records in more than one event")


# --- acceptance facts -----------------------------------------------------------------------

def _visible_passages(c: Context, user: str, doc_id: str | None = None) -> list[str]:
    """Texts of the passages the user may see, optionally limited to one document."""
    groups = c.rules.user_groups(user)
    sql = """SELECT p.text_original FROM {s}.passages p WHERE EXISTS (
                 SELECT 1 FROM {s}.access_alternatives a WHERE a.object_type = 'passage'
                 AND a.object_id = p.passage_id AND a.required_groups <@ %s)"""
    params: tuple = (groups,)
    if doc_id:
        sql += " AND p.doc_id = %s"
        params = (groups, doc_id)
    return [r[0] for r in c.q(sql, params)]


def _fact(c: Context, f: dict) -> tuple[bool, str]:
    """(passed, detail) for one acceptance fact, dispatched on its type. A fact naming a path
    fails when that document is not in the dataset, except for quarantine facts."""
    t = f["type"]
    doc_id = c.doc_for_path(f["path"]) if "path" in f and t != "quarantined" else None
    if "path" in f and t != "quarantined" and doc_id is None:
        return False, f"document {f['path']} not in dataset"
    if t == "quarantined":
        got = c.quarantined.get(f["path"])
        return got == f["reason"], f"quarantine reason {got}"
    if t == "same_passage":
        texts = [p.text_original for p in c.ds.passages.values() if p.doc_id == doc_id]
        ok = any(all(x in t_ for x in f["texts"]) for t_ in texts)
        return ok, "" if ok else "no single passage holds all texts"
    if t == "passage_contains":
        ok = any(f["text"] in p.text_original for p in c.ds.passages.values()
                 if p.doc_id == doc_id)
        return ok, ""
    if t == "passage_count":
        n = sum(1 for p in c.ds.passages.values() if p.doc_id == doc_id)
        return n == f["count"], f"{n} passages"
    if t == "no_visible_passage_contains":
        hits = [x for x in f["texts"] for txt in _visible_passages(c, f["user"]) if x in txt]
        return not hits, f"visible: {sorted(set(hits))}" if hits else ""
    if t == "visible_passage_contains":
        ok = any(f["text"] in txt for txt in _visible_passages(c, f["user"], doc_id))
        return ok, ""
    if t == "visible_document":
        groups = c.rules.user_groups(f["user"])
        ok = bool(c.q("""SELECT 1 FROM {s}.access_alternatives WHERE object_type = 'document'
                         AND object_id = %s AND required_groups <@ %s""", (doc_id, groups)))
        return ok, ""
    if t == "visible_event_contains":
        groups = c.rules.user_groups(f["user"])
        rows = c.q("""SELECT e.notes_original FROM {s}.service_events e WHERE e.asset_id = %s
                      AND EXISTS (SELECT 1 FROM {s}.access_alternatives a
                                  WHERE a.object_type = 'event' AND a.object_id = e.event_id
                                  AND a.required_groups <@ %s)""", (f["asset"], groups))
        ok = any(f["text"] in (r[0] or "") for r in rows)
        if ok and f["text"]:
            # the event's search passage must be visible too
            ok = any(f["text"] in txt for txt in _visible_passages(c, f["user"]))
        return ok, ""
    if t == "event_field":
        rows = c.q("""SELECT event_date::text, labor_hours::float, status FROM {s}.service_events
                      WHERE sources @> %s::jsonb""",
                   (f'[{{"system": "{f["system"]}", "record_id": "{f["record_id"]}"}}]',))
        if len(rows) != 1:
            return False, f"{len(rows)} events for the record"
        got = dict(zip(("event_date", "labor_hours", "status"), rows[0], strict=False))[f["field"]]
        return got == f["value"], f"got {got!r}"
    if t == "alias":
        rows = c.q("SELECT asset_id FROM {s}.asset_aliases WHERE alias = %s", (f["alias"],))
        return bool(rows) and rows[0][0] == f["asset_id"], f"got {rows}"
    if t == "site_alias":
        rows = c.q("SELECT site FROM {s}.site_aliases WHERE alias = %s", (f["alias"],))
        return bool(rows) and rows[0][0] == f["site"], f"got {rows}"
    if t == "event_query":
        rows = c.q("""SELECT to_char(event_date, 'YYYY-MM'), sources FROM {s}.service_events
                      WHERE asset_id = %s AND fault_code = %s""", (f["asset"], f["fault_code"]))
        months = {r[0] for r in rows}
        case_hits = Counter(s["record_id"] for r in rows for s in r[1]
                            if s["system"] == "salesforce" and s.get("relation") != "references")
        missing_months = [m for m in f["months"] if m not in months]
        bad_cases = {cn: case_hits.get(cn, 0) for cn in f["cases"] if case_hits.get(cn) != 1}
        ok = not missing_months and not bad_cases
        return ok, f"missing months {missing_months}, case counts {bad_cases}" if not ok else ""
    if t == "bulletin_asset":
        rows = c.q("""SELECT b.status, r.campaign_code FROM {s}.bulletin_assets b
                      LEFT JOIN {s}.bulletin_rules r USING (rule_id)
                      WHERE b.doc_id = %s AND b.asset_id = %s""", (doc_id, f["asset"]))
        got = rows[0] if rows else (None, None)
        ok = got[0] == f["status"] and ("campaign_code" not in f or got[1] == f["campaign_code"])
        return ok, f"got {got}"
    if t == "bulletin_rule":
        cols = [k for k in ("model", "serial_from", "serial_to", "firmware_condition",
                            "market_condition", "campaign_code", "outcome") if k in f]
        where = " AND ".join(f"{k} = %s" for k in cols)
        rows = c.q(f"SELECT 1 FROM {{s}}.bulletin_rules WHERE doc_id = %s AND {where}",
                   (doc_id, *[f[k] for k in cols]))
        return bool(rows), "" if rows else "no matching rule"
    if t == "document_field":
        if f["field"] not in ("revision", "issue_date", "status", "title", "doc_type", "models",
                              "missing_pages"):
            return False, f"field {f['field']} not checkable"
        rows = c.q(f"SELECT {f['field']}::text FROM {{s}}.documents WHERE doc_id = %s",
                   (doc_id,))
        return rows[0][0] == f["value"], f"got {rows[0][0]!r}"
    if t == "relation":
        to_doc = c.doc_for_path(f["to_path"])
        rows = c.q("""SELECT 1 FROM {s}.document_relations
                      WHERE from_doc = %s AND to_doc = %s AND relation = %s""",
                   (doc_id, to_doc, f["relation"]))
        return bool(rows), ""
    if t == "possibly_stale":
        flags = [p.possibly_stale for p in c.ds.passages.values()
                 if p.doc_id == doc_id and f["text"] in p.text_original]
        ok = bool(flags) and all(x == f["expected"] for x in flags)
        return ok, f"flags {flags}"
    if t == "no_passage_contains":
        hits = [x for x in f["texts"] for p in c.ds.passages.values() if p.doc_id == doc_id
                and (x in p.text_original or x in (p.text_en or ""))]
        return not hits, f"found {sorted(set(hits))}" if hits else ""
    if t == "event_notes_en":
        rows = c.q("""SELECT notes_en FROM {s}.service_events WHERE sources @> %s::jsonb""",
                   (f'[{{"system": "{f["system"]}", "record_id": "{f["record_id"]}"}}]',))
        got = rows[0][0] if len(rows) == 1 else None
        return bool(got) and f["contains"] in got, f"got {got!r}"
    if t == "origins":
        rows = c.q("SELECT path FROM {s}.document_origins WHERE doc_id = %s", (doc_id,))
        got = sorted(r[0] for r in rows)
        title = c.q("SELECT title FROM {s}.documents WHERE doc_id = %s", (doc_id,))[0][0]
        ok = got == sorted(f["paths"]) and ("title" not in f or title == f["title"])
        return ok, f"origins {got}, title {title!r}"
    return False, f"unknown fact type {t}"


def run_facts(c: Context, path: Path = FACTS_PATH) -> list[CheckResult]:
    """One result per acceptance fact; a fact that raises fails instead of aborting the run."""
    facts = yaml.safe_load(path.read_text())["facts"]
    out = []
    for f in facts:
        try:
            ok, detail = _fact(c, f)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"error: {e}"
        out.append(CheckResult(f"fact:{f['id']}", ok, detail))
    return out


def validate(c: Context) -> list[CheckResult]:
    """Run every registered check, then the acceptance facts. A check that raises fails."""
    results = []
    for name, fn in CHECKS:
        try:
            results.append(fn(c))
        except Exception as e:  # noqa: BLE001
            results.append(CheckResult(name, False, f"check raised {e}"))
    return results + run_facts(c)


def passed(results: list[CheckResult]) -> bool:
    """True when no error-severity result failed; warnings do not block publishing."""
    return all(r.passed for r in results if r.severity == "error")
