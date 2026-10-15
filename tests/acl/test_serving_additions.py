"""specs/contracts/serving-additions.md: restricted procedures, page visibility, dataset info."""
import pytest

from copilot_ingest.settings import get_settings

pytestmark = [pytest.mark.acl, pytest.mark.integration]


def _pages(db):
    """(doc_id, page) -> passage_ids anchored on that page, page ranges expanded."""
    out: dict[tuple[str, int], set[str]] = {}
    for doc_id, pid, first, last in db.execute(
            "SELECT doc_id, passage_id, (anchor->>'page')::int,"
            " coalesce((anchor->>'page_end')::int, (anchor->>'page')::int)"
            " FROM serving.passages_for(ARRAY(SELECT DISTINCT unnest(required_groups)"
            "  FROM serving.document_origins)) WHERE anchor ? 'page'"):
        for page in range(first, last + 1):
            out.setdefault((doc_id, page), set()).add(pid)
    return out


def test_page_fully_visible_grid(db, rules):
    pages = _pages(db)
    for user, groups in rules.users.items():
        visible = {r[0] for r in db.execute(
            "SELECT passage_id FROM serving.passages_for(%s)", (groups,))}
        docs = {r[0] for r in db.execute(
            "SELECT doc_id FROM serving.documents_for(%s)", (groups,))}
        for (doc_id, page), pids in pages.items():
            expected = doc_id in docs and pids <= visible
            got = db.execute("SELECT serving.page_fully_visible(%s, %s, %s)",
                             (groups, doc_id, page)).fetchone()[0]
            assert got == expected, (user, doc_id, page)


def test_nk600_refrigerant_page_hidden_from_uncertified(db, rules):
    """NK600 8.3 (visible) shares a page with 8.4 (SOP-020 steps): no page image for u06."""
    doc_id, page = db.execute(
        "SELECT p.doc_id, (p.anchor->>'page')::int FROM serving.passages_for(%s) p"
        " JOIN serving.documents_for(%s) d USING (doc_id)"
        " WHERE d.title = 'Nordkyl NK-600 Service Manual Rev C'"
        " AND p.heading_path[array_length(p.heading_path, 1)] = '8.3 Low charge'",
        (rules.users["u06"], rules.users["u06"])).fetchone()
    check = "SELECT serving.page_fully_visible(%s, %s, %s)"
    assert db.execute(check, (rules.users["u06"], doc_id, page)).fetchone()[0] is False
    assert db.execute(check, (rules.users["u05"], doc_id, page)).fetchone()[0] is True


def test_restricted_procedures_are_names_only(db):
    cols = {r[0] for r in db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'serving'"
        " AND table_name = 'restricted_procedures'")}
    assert cols == {"name", "title", "doc_id", "alt_no", "required_groups"}
    rows = {r[0]: r[1] for r in db.execute(
        "SELECT name, required_groups FROM serving.restricted_procedures")}
    assert rows == {"HV-PROC-07": ["cert-hv", "family-compressors"], "HV-PROC-02": ["cert-hv"],
                    "SOP-020": ["cert-refrigerant", "family-chillers"],
                    "CS-PROC-03": ["cert-confined-space"]}


def test_dataset_info_matches_embedding_settings(db):
    s = get_settings()
    version, model, dims = db.execute(
        "SELECT dataset_version, embedding_model, embedding_dims FROM serving.dataset_info()"
    ).fetchone()
    assert version == db.execute("SELECT dataset_version FROM control.published").fetchone()[0]
    assert (model, dims) == (s.embedding_model, s.embedding_dims)


def test_restricted_markers_match_reviewed_decision(db):
    rows = {(r[0], r[1]) for r in db.execute(
        "SELECT procedure, marker FROM serving.restricted_markers WHERE status = 'approved'")}
    assert {m for p, m in rows if p == "HV-PROC-07"} == {
        "1,000 V DC", "100 MOHM", "50 V DC", "P9.01", "TP1", "TP2"}


def test_hidden_exists_needs_relevance(db, rules):
    """Identifiers alone: EU (Europe) BX-20 records are hidden from u12 (NA conveyor technician)
    though none is about the warranty. With an embedding, only nearby hidden passages count."""
    u12, eu = rules.users["u12"], ["region-eu", "family-conveyors"]
    assert db.execute("SELECT serving.hidden_exists(%s, %s)", (u12, ["BX-20"])).fetchone()[0]
    probe = ("(SELECT embedding FROM serving.passages_for(%s) WHERE 'BX-20' = ANY(models)"
             " AND embedding IS NOT NULL AND NOT serving.can_see('passage', passage_id, %s)"
             " LIMIT 1)")
    near = f"SELECT serving.hidden_exists(%s, %s, {probe}, 0.001)"
    assert db.execute(near, (u12, ["BX-20"], eu, u12)).fetchone()[0] is True
    assert db.execute(near, (eu, ["BX-20"], eu, u12)).fetchone()[0] is False
