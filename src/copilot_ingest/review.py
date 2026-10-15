import json
import re
from typing import Any

from psycopg.types.json import Jsonb

from copilot_ingest.ids import review_item_id
from copilot_ingest.models import ReviewItem


def item_id(item: ReviewItem) -> str:
    """Stable review item ID from source fingerprint, stage, anchor and field."""
    anchor_key = json.dumps(item.anchor or {}, sort_keys=True)
    return review_item_id(item.fingerprint, item.stage, anchor_key, item.field or "")


def upsert_items(conn, items: list[ReviewItem], run_id: str) -> None:
    """Insert new items, refresh existing ones; reopen resolved items whose candidates changed."""
    for item in items:
        iid = item_id(item)
        conn.execute(
            """
            INSERT INTO control.review_items
                (item_id, kind, path, anchor, field, candidates, reason, status, first_run,
                 last_run)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s)
            ON CONFLICT (item_id) DO UPDATE SET
                last_run = EXCLUDED.last_run,
                reason = EXCLUDED.reason,
                status = CASE WHEN control.review_items.status = 'obsolete'
                                   OR control.review_items.candidates IS DISTINCT FROM
                                      EXCLUDED.candidates
                              THEN 'open' ELSE control.review_items.status END,
                candidates = EXCLUDED.candidates
            """,
            (iid, item.kind, item.path, Jsonb(item.anchor), item.field, Jsonb(item.candidates),
             item.reason, run_id, run_id),
        )


def close_unraised(conn, run_id: str) -> None:
    """Open items this run did not raise again are obsolete (source or rule changed)."""
    conn.execute("UPDATE control.review_items SET status = 'obsolete'"
                 " WHERE status = 'open' AND last_run IS DISTINCT FROM %s", (run_id,))


def resolutions(conn, kind: str | None = None) -> dict[str, Any]:
    """Recorded resolution values by item ID, optionally only for one item kind."""
    q = ("SELECT r.item_id, r.value FROM control.resolutions r "
         "JOIN control.review_items i USING (item_id)")
    params: tuple = ()
    if kind:
        q += " WHERE i.kind = %s"
        params = (kind,)
    return {iid: value for iid, value in conn.execute(q, params)}


def with_fingerprint(item: ReviewItem, fingerprints: dict[str, str]) -> ReviewItem:
    """Items raised without a fingerprint take their source file's, so the ID changes when the
    file does."""
    if not item.fingerprint and item.path and item.path in fingerprints:
        item.fingerprint = fingerprints[item.path]
    return item


class Decisions:
    """Reviewer resolutions, looked up by the item a stage would raise. Item IDs hash the
    source fingerprint and anchor, so a changed source needs a fresh decision."""

    def __init__(self, values: dict[str, Any] | None = None,
                 fingerprints: dict[str, str] | None = None):
        """Hold resolution values by item ID and source fingerprints by path."""
        self.values = values or {}
        self.fingerprints = fingerprints or {}
        self.applied: list[str] = []

    def get(self, item: ReviewItem) -> Any | None:
        """Reviewer's value for this item, or None if undecided. Records hits in `applied`."""
        iid = item_id(with_fingerprint(item.model_copy(), self.fingerprints))
        if iid in self.values:
            self.applied.append(iid)
            return self.values[iid]
        return None


def load_decisions(conn, fingerprints: dict[str, str]) -> Decisions:
    """All recorded resolutions, ready for stages to look up."""
    return Decisions(resolutions(conn), fingerprints)


class InvalidResolution(ValueError):
    pass


def _parse(raw: str) -> Any:
    """Reviewer input as JSON if it parses, else the stripped string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()


def normalize_value(kind: str, candidates: Any, raw: str, field: str | None = None) -> Any:
    """Check a reviewer's value for an item kind; return what the stage will apply."""
    value = _parse(raw)
    if kind == "marker_approval":
        proposed = list((candidates or {}).get("proposed", []))
        if value == "approve":
            return {"approved": proposed, "rejected": []}
        if value == "reject":
            return {"approved": [], "rejected": proposed}
        if isinstance(value, dict) and set(value) <= {"approved", "rejected"}:
            out = {"approved": list(value.get("approved", [])),
                   "rejected": list(value.get("rejected", []))}
            if set(out["approved"]) & set(out["rejected"]):
                raise InvalidResolution("a marker cannot be both approved and rejected")
            return out
        raise InvalidResolution('use "approve", "reject" or {"approved": [...], "rejected": [...]}')
    if kind == "restricted_borderline":
        if value not in ("restrict", "release"):
            raise InvalidResolution('use "restrict" or "release"')
        return value
    if kind == "unresolved_link":
        if not isinstance(value, str) or not value:
            raise InvalidResolution('use the correct case number, or "none" to dismiss')
        return value
    if kind == "unknown_asset":
        if not isinstance(value, str) or not value:
            raise InvalidResolution('use a fleet asset ID, or "keep" to keep the raw ID')
        return value if value == "keep" else value.upper()
    if kind == "ocr_value_mismatch":
        value = raw.strip()  # verbatim: "6309" must stay the printed text, not become a number
        if not value or "[[" in value:
            raise InvalidResolution('use the value as printed on the page image (e.g. "3,2 m"),'
                                    ' or "withhold" to keep it withheld')
        return value.strip()
    if kind == "metadata_unverified":
        if not isinstance(value, str) or not value.strip():
            raise InvalidResolution("use the revision (e.g. A) or the issue date as YYYY-MM-DD")
        if field == "issue_date" and \
                not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            raise InvalidResolution("use the issue date as YYYY-MM-DD")
        return value.strip()
    return value


def resolve(conn, iid: str, raw: str, note: str | None, by: str | None) -> tuple[str, Any]:
    """Record a resolution (applied on the next run). Accepts a unique item ID prefix."""
    rows = conn.execute("SELECT item_id, kind, candidates, field FROM control.review_items"
                        " WHERE item_id LIKE %s", (iid + "%",)).fetchall()
    if len(rows) != 1:
        raise InvalidResolution(f"{len(rows)} items match {iid!r}")
    full, kind, candidates, field = rows[0]
    value = normalize_value(kind, candidates, raw, field)
    if kind == "marker_approval":
        prev = conn.execute("SELECT value FROM control.resolutions WHERE item_id = %s",
                            (full,)).fetchone()
        if prev:
            # Decisions accumulate: earlier approvals stay unless the reviewer flips them.
            approved = (set(prev[0]["approved"]) - set(value["rejected"])) | set(value["approved"])
            rejected = (set(prev[0]["rejected"]) - set(value["approved"])) | set(value["rejected"])
            value = {"approved": sorted(approved), "rejected": sorted(rejected)}
    conn.execute(
        "INSERT INTO control.resolutions (item_id, value, resolved_by, note)"
        " VALUES (%s, %s, %s, %s) ON CONFLICT (item_id) DO UPDATE SET value = EXCLUDED.value,"
        " resolved_by = EXCLUDED.resolved_by, note = EXCLUDED.note, resolved_at = now()",
        (full, Jsonb(value), by, note))
    conn.execute("UPDATE control.review_items SET status = 'resolved' WHERE item_id = %s",
                 (full,))
    return full, value


def open_items(conn, run_id: str) -> list[dict[str, Any]]:
    """Items still open that this run raised, ordered by kind and path."""
    rows = conn.execute(
        "SELECT item_id, kind, path, field, reason FROM control.review_items "
        "WHERE status = 'open' AND last_run = %s ORDER BY kind, path",
        (run_id,),
    ).fetchall()
    keys = ("item_id", "kind", "path", "field", "reason")
    return [dict(zip(keys, r, strict=True)) for r in rows]
