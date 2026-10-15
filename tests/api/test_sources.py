"""GET /api/sources/{id} and page.png against the real published serving schema (003 US2, SC-001,
SC-002). Skipped when the database or a published dataset is missing."""
import json

import pymupdf
import pytest

from copilot_api.sources import MAX_WIDTH, SourceStore
from copilot_ingest.settings import PROJECT_ROOT
from tests.api.conftest import Harness

pytestmark = [pytest.mark.acl, pytest.mark.integration]

NK600_83 = "p_f71b980da8173a0d23371f8c"
"""NK-600 chiller manual 8.3 Low charge, page 11, visible to u06."""
NK600_84 = "p_89e01fa9f9431d888616bfd8"
"""NK-600 chiller manual 8.4 Recovery and recharge, page 11, tagged SOP-020 (restricted)."""
SB_009_TABLE = "p_e35d98a44e996383173e0193"
"""SB-2025-009 (Halden HCP-350 casing-torque bulletin), 2 Affected products table, page 1."""
HCP200_SCAN = "p_7a891cda95ff12c33c8caaa5"
"""HCP-200 1998 scanned German manual, technical data, page 3."""

USERS = {u["id"]: u["groups"] for u in json.loads((PROJECT_ROOT / "users.json").read_text())
         ["users"]}
CATALOG = sorted(json.loads((PROJECT_ROOT / "users.json").read_text())["groups"])


@pytest.fixture(scope="module")
def store():
    import psycopg

    from copilot_ingest.settings import get_settings

    s = get_settings()
    try:
        with psycopg.connect(s.database_url) as conn:
            if conn.execute("SELECT to_regnamespace('serving')").fetchone()[0] is None:
                pytest.skip("no published dataset")
    except psycopg.OperationalError as e:
        pytest.skip(f"database not available: {e}")
    return SourceStore(s.database_url, s.corpus_dir, s.data_dir, known_groups=lambda: CATALOG)


@pytest.fixture
def h(config, store) -> Harness:
    return Harness(config, sources=store)


def _png_width(data: bytes) -> int:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return pymupdf.Pixmap(data).width


def test_exhaustive_grid_matches_can_see(h, db):
    """SC-001 and SC-002: every user x every passage; allow/deny equals serving.can_see, and no
    page image is offered unless serving.page_fully_visible is true for that page."""
    passages = db.execute(
        "SELECT passage_id, doc_id, (anchor->>'page')::int FROM serving.passages_for(%s)",
        (CATALOG,)).fetchall()
    assert len(passages) > 1000
    mismatches, images = [], 0
    for user, groups in USERS.items():
        client = h.client(user)
        allowed = {r[0] for r in db.execute(
            "SELECT id FROM unnest(%s::text[]) id WHERE serving.can_see('passage', id, %s)",
            ([p[0] for p in passages], groups)).fetchall()}
        full_pages = {(d, pg) for d, pg, ok in db.execute(
            "SELECT doc_id, page, serving.page_fully_visible(%s, doc_id, page) FROM"
            " (SELECT DISTINCT doc_id, (anchor->>'page')::int AS page"
            "  FROM serving.passages_for(%s) WHERE anchor ? 'page') x",
            (groups, CATALOG)).fetchall() if ok}
        for pid, doc_id, page in passages:
            r = client.get(f"/api/sources/{pid}")
            expected = 200 if pid in allowed else 403
            if r.status_code != expected:
                mismatches.append((user, pid, r.status_code))
                continue
            if expected == 403:
                assert r.json() == {"error": "not_visible"}
                continue
            body = r.json()
            assert body["passage_id"] == pid and body["page"] == page
            if body["page_image_url"]:
                images += 1
                if (doc_id, page) not in full_pages:
                    mismatches.append((user, pid, "page image on a partly hidden page"))
    assert mismatches == []
    assert images > 0
    shown = len(h.events("source_view"))
    denied = len(h.events("access_denied"))
    assert shown + denied == len(USERS) * len(passages)


def test_absent_passage_is_404(h):
    r = h.client("u08").get("/api/sources/p_000000000000000000000000")
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})
    assert h.client("u08").get("/api/sources/p_000000000000000000000000/page.png"
                               ).status_code == 404


def test_shared_page_hides_image_from_uncertified(h):
    """u06 (chiller technician without refrigerant certification) opens NK-600 8.3: text, page
    number, no page image, because 8.4 (restricted to SOP-020 holders) is on the same page."""
    c = h.client("u06")
    r = c.get(f"/api/sources/{NK600_83}")
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 11
    assert body["page_image_url"] is None
    assert body["locator"].startswith("p. 11, 8.3 Low charge")
    png = c.get(f"/api/sources/{NK600_83}/page.png")
    assert (png.status_code, png.json()["error"]) == (403, "not_visible")
    assert png.headers["cache-control"] == "no-store"


def test_shared_page_image_for_certified(h):
    """u05 (refrigerant-certified engineer) sees every passage on page 11, so gets the image."""
    c = h.client("u05")
    body = c.get(f"/api/sources/{NK600_83}").json()
    assert body["page_image_url"] == f"/api/sources/{NK600_83}/page.png"
    r = c.get(body["page_image_url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-store"
    assert _png_width(r.content) <= MAX_WIDTH


def test_restricted_passage_is_403_and_audited(h):
    c = h.client("u06")
    r = c.get(f"/api/sources/{NK600_84}")
    assert (r.status_code, r.json()) == (403, {"error": "not_visible"})
    assert NK600_84 not in r.text or r.text == '{"error":"not_visible"}'
    assert c.get(f"/api/sources/{NK600_84}/page.png").status_code == 403
    [first, second] = h.events("access_denied")
    assert (first.user_id, first.passage_ids, first.outcome) == ("u06", [NK600_84], "not_visible")
    assert first.dataset_version.startswith("ds_")
    assert h.events("source_view") == []


def test_bulletin_table_with_page_image(h):
    """US2 scenario 1: u04 opens the SB-2025-009 table passage."""
    c = h.client("u04")
    body = c.get(f"/api/sources/{SB_009_TABLE}").json()
    assert body["locator"].startswith("p. 1, 2 Affected products")
    assert body["doc_type"] == "bulletin" and body["status"] == "active"
    assert "HCP-350" in body["text_original"]
    r = c.get(body["page_image_url"])
    assert r.status_code == 200
    width = _png_width(r.content)
    assert 600 < width <= MAX_WIDTH
    [view, image] = h.events("source_view")
    assert (view.outcome, view.details["page_image"]) == ("shown", True)
    assert (image.outcome, image.details["kind"]) == ("page_image", "pdf")


def test_scanned_page_uses_stored_scan(h, store):
    """US2 scenario 4: the HCP-200 scan; the stored scan image, downscaled to 1,600 px."""
    c = h.client("u01")
    body = c.get(f"/api/sources/{HCP200_SCAN}").json()
    assert body["ocr"] is True and body["lang"] == "de" and body["text_en"]
    r = c.get(body["page_image_url"])
    assert r.status_code == 200
    assert _png_width(r.content) == MAX_WIDTH
    assert h.events("source_view")[-1].details["kind"] == "scan"
    res = store.source(frozenset(USERS["u01"]), HCP200_SCAN)
    assert res.image.kind == "scan" and _png_width(res.image.path.read_bytes()) > MAX_WIDTH


def test_withheld_values_pass_through_as_markers(h, db):
    """Text is returned exactly as stored, so any [[unverified:...]] marker stays a marker."""
    for pid, text in db.execute(
            "SELECT passage_id, text_original FROM serving.passages_for(%s) WHERE ocr <> 'none'",
            (USERS["u01"],)).fetchall():
        assert h.client("u01").get(f"/api/sources/{pid}").json()["text_original"] == text


def test_superseded_document(h, db):
    row = db.execute("SELECT from_doc, to_doc FROM serving.document_relations"
                     " WHERE relation = 'supersedes'").fetchone()
    if row is None:
        pytest.skip("no superseded document in this dataset")
    newer, older = row
    pid = db.execute("SELECT passage_id FROM serving.passages_for(%s) WHERE doc_id = %s LIMIT 1",
                     (USERS["u03"], older)).fetchone()[0]
    body = h.client("u03").get(f"/api/sources/{pid}").json()
    assert body["status"] == "superseded"
    assert body["superseded_by"] == newer
