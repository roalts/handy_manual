import json
from pathlib import Path

import pytest

from copilot_ingest.models import ReviewItem
from copilot_ingest.review import (
    InvalidResolution,
    close_unraised,
    item_id,
    resolve,
    upsert_items,
)
from copilot_ingest.settings import get_settings

ITEM = ReviewItem(kind="marker_approval", path="test/never-a-real-file.docx", field="TEST-PROC",
                  candidates={"proposed": ["TP9", "P1.23"], "approved": []},
                  reason="test item", stage="test")


@pytest.fixture
def test_item(db):
    iid = item_id(ITEM)
    upsert_items(db, [ITEM], "test-run")
    yield iid
    db.execute("DELETE FROM control.resolutions WHERE item_id = %s", (iid,))
    db.execute("DELETE FROM control.review_items WHERE item_id = %s", (iid,))


def _status(db, iid):
    return db.execute("SELECT status FROM control.review_items WHERE item_id = %s",
                      (iid,)).fetchone()[0]


def test_resolve_records_value_and_closes_item(db, test_item):
    full, value = resolve(db, test_item[:14], '{"rejected": ["TP9"]}', "not distinctive", "qa")
    assert full == test_item and _status(db, test_item) == "resolved"
    # a second decision adds to the first instead of replacing it
    _, value = resolve(db, test_item, '{"approved": ["P1.23"]}', None, "qa")
    assert value == {"approved": ["P1.23"], "rejected": ["TP9"]}
    stored = db.execute("SELECT value FROM control.resolutions WHERE item_id = %s",
                        (test_item,)).fetchone()[0]
    assert stored == value


def test_invalid_value_leaves_item_open(db, test_item):
    with pytest.raises(InvalidResolution):
        resolve(db, test_item, "perhaps", None, None)
    assert _status(db, test_item) == "open"


def test_item_not_raised_again_becomes_obsolete_and_reopens(db, test_item):
    before = db.execute("SELECT item_id, status FROM control.review_items"
                        " WHERE item_id <> %s", (test_item,)).fetchall()
    try:
        close_unraised(db, "test-run-2")
        assert _status(db, test_item) == "obsolete"
        upsert_items(db, [ITEM], "test-run-3")
        assert _status(db, test_item) == "open"
    finally:  # leave the real queue as the last run left it
        for iid, status in before:
            db.execute("UPDATE control.review_items SET status = %s WHERE item_id = %s",
                       (status, iid))


def test_every_corpus_file_once_in_latest_report(db):
    """SC-002: every source file appears in the report with exactly one outcome."""
    path = db.execute("SELECT report_path FROM control.runs WHERE report_path IS NOT NULL"
                      " ORDER BY started_at DESC LIMIT 1").fetchone()[0]
    report = json.loads(Path(path).with_suffix(".json").read_text())
    corpus = get_settings().corpus_dir
    on_disk = {str(p.relative_to(corpus)) for p in corpus.rglob("*")
               if p.is_file() and p.name not in (".DS_Store", "Thumbs.db")
               and not p.name.startswith("~$")}
    listed = [f["path"] for f in report["files"]]
    assert sorted(listed) == sorted(on_disk)
    assert all(f["outcome"] for f in report["files"])
