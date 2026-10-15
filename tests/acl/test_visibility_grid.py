"""SC-001: for every user and every document, visibility equals what the access rules allow."""
import pytest

from copilot_ingest.acl import can_see

pytestmark = [pytest.mark.acl, pytest.mark.integration]


def _visible_paths(db, groups):
    return {r[0] for r in db.execute(
        "SELECT o.path FROM serving.documents_for(%s) d JOIN serving.document_origins o"
        " USING (doc_id)", (groups,))}


def _all_paths(db):
    return {r[0]: r[1] for r in db.execute("SELECT path, doc_id FROM serving.document_origins")}


def test_document_grid(db, rules):
    indexed = _all_paths(db)
    for user, groups in rules.users.items():
        allowed_docs = {indexed[p] for p, req in rules.documents.items()
                        if p in indexed and can_see(req, groups)}
        expected = {p for p, d in indexed.items() if d in allowed_docs}
        assert _visible_paths(db, groups) == expected, user


def test_passages_follow_documents(db, rules):
    """No user sees a passage of a document they cannot see (event passages excepted)."""
    for user, groups in rules.users.items():
        leaked = db.execute(
            """SELECT p.passage_id FROM serving.passages_for(%s) p
               WHERE NOT p.passage_id LIKE 'p_ev_%%'
                 AND p.doc_id NOT IN (SELECT doc_id FROM serving.documents_for(%s))""",
            (groups, groups)).fetchall()
        assert not leaked, (user, leaked[:3])


def test_hv_tagged_passages_need_cert_hv(db, rules):
    for user, groups in rules.users.items():
        if "cert-hv" in groups:
            continue
        rows = db.execute("SELECT passage_id FROM serving.passages_for(%s)"
                          " WHERE EXISTS (SELECT 1 FROM unnest(restricted_tags) t"
                          " WHERE t LIKE 'HV-PROC-%%')", (groups,)).fetchall()
        assert not rows, (user, rows[:3])


def test_quarantined_paths_invisible(db, rules):
    indexed = _all_paths(db)
    for path in ("confluence/VRS-110-VFD-quick-reset-unofficial.html",
                 "sharepoint/Inspection_Checklist_Q3_FINAL.docx"):
        assert path not in indexed
    everyone = sorted({g for gs in rules.users.values() for g in gs})
    hits = db.execute("SELECT count(*) FROM serving.keyword_search(%s, 'TP1 TP2', 50)",
                      (rules.user_groups("u03"),)).fetchone()[0]
    assert hits == 0
    assert db.execute("SELECT count(*) FROM serving.keyword_search(%s, 'P9.01', 50)",
                      (everyone,)).fetchone()[0] > 0
