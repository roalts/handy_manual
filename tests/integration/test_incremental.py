"""US5: runs over a changing corpus, against a scratch database (see conftest.py).

Tests run in file order and share one scratch corpus: each one changes it and runs the pipeline.
Changed text needs new embeddings, so a few hosted embedding calls (fractions of a cent) are made
once and then copied back into the real cache.
"""
import json

import psycopg
import pytest
from typer.testing import CliRunner

from copilot_ingest.acl import load_access_rules
from copilot_ingest.cli import app
from copilot_ingest.pipeline import EXIT_PUBLISHED, EXIT_VALIDATION_FAILED, RunOptions, run

pytestmark = [pytest.mark.integration, pytest.mark.hosted]

MODIFIED = "confluence/Tacoma-Site-Notes.html"
DELETED = "confluence/Lessons-Learned-2025.html"
TIGHTENED = "confluence/Rotterdam-Site-Notes.html"
HV7 = "sharepoint/HV-PROC-07_VRS-110_VFD_Fault_Reset.docx"


def _run(scratch, **kw):
    return run(RunOptions(corpus=scratch.corpus, acl=scratch.acl, users=scratch.users, **kw))


def _q(scratch, sql, params=()):
    with psycopg.connect(scratch.url) as conn:
        return conn.execute(sql, params).fetchall()


def _published(scratch):
    return _q(scratch, "SELECT dataset_version FROM control.published")[0][0]


def _doc_of(scratch, schema, path):
    rows = _q(scratch, f"SELECT doc_id FROM {schema}.document_origins WHERE path = %s",  # noqa: S608
              (path,))
    return rows[0][0] if rows else None


def _passages(scratch, schema):
    return dict(_q(scratch, f"SELECT passage_id, doc_id FROM {schema}.passages"))  # noqa: S608


def _visible_paths(scratch, user):
    groups = load_access_rules(scratch.acl, scratch.users).user_groups(user)
    return {r[0] for r in _q(scratch, "SELECT o.path FROM serving.documents_for(%s) d"
                                      " JOIN serving.document_origins o USING (doc_id)", (groups,))}


def _edit_acl(scratch, path, groups):
    acl = json.loads(scratch.acl.read_text())
    acl["documents"][f"corpus/{path}"]["required_groups"] = groups
    scratch.acl.write_text(json.dumps(acl, indent=2))


def test_first_run_publishes(scratch):
    code, report = _run(scratch)
    assert code == EXIT_PUBLISHED, report.get("validation")
    assert report["changes"]["files_added"] == len(report["files"])


def test_unchanged_corpus_gives_identical_passages(scratch):
    """SC-005: same IDs and texts when nothing changed."""
    before = _published(scratch)
    code, report = _run(scratch)
    assert code == EXIT_PUBLISHED
    ch = report["changes"]
    assert ch["compared_with"] == before
    assert ch["passages_added"] == ch["passages_removed"] == ch["passages_changed"] == 0
    assert ch["files_unchanged"] == len(report["files"])


def test_changing_one_file_changes_only_its_passages(scratch):
    before = _published(scratch)
    old_doc = _doc_of(scratch, before, MODIFIED)
    page = scratch.corpus / MODIFIED
    page.write_text(page.read_text().replace("Monday and Thursday mornings",
                                             "Tuesday and Thursday mornings"))
    code, report = _run(scratch)
    assert code == EXIT_PUBLISHED, report.get("validation")
    after = report["dataset_version"]
    new_doc = _doc_of(scratch, after, MODIFIED)
    assert report["changes"]["files_changed"] == 1
    old, new = _passages(scratch, before), _passages(scratch, after)
    assert {old[p] for p in old.keys() - new.keys()} <= {old_doc}
    assert {new[p] for p in new.keys() - old.keys()} <= {new_doc}
    assert new.keys() - old.keys(), "the edited page should produce new passages"


def test_deleted_file_leaves_the_dataset(scratch):
    (scratch.corpus / DELETED).unlink()
    code, report = _run(scratch)
    assert code == EXIT_PUBLISHED, report.get("validation")
    assert report["removed"] == [DELETED]
    assert _doc_of(scratch, report["dataset_version"], DELETED) is None
    status = _q(scratch, "SELECT status FROM control.source_files WHERE path = %s", (DELETED,))
    assert status == [("removed",)]


def test_tightened_rule_removes_visibility(scratch):
    """SC-007: an access change takes effect in the next version."""
    assert TIGHTENED in _visible_paths(scratch, "u06")
    _edit_acl(scratch, TIGHTENED, ["region-eu", "role-lead"])
    code, report = _run(scratch)
    assert code == EXIT_PUBLISHED, report.get("validation")
    assert TIGHTENED not in _visible_paths(scratch, "u06")  # region-eu, not a lead
    assert TIGHTENED in _visible_paths(scratch, "u07")  # region-eu lead


def test_only_rebuilds_a_complete_dataset(scratch):
    before = _published(scratch)
    count = len(_passages(scratch, before))
    code, report = _run(scratch, only={MODIFIED})
    assert code == EXIT_PUBLISHED
    assert len(_passages(scratch, report["dataset_version"])) == count
    detail = {f["path"]: f["detail"] for f in report["files"]}
    assert "reused extraction" not in detail[MODIFIED]
    assert "reused extraction" in detail[HV7]


def test_failed_validation_keeps_previous_version_and_rollback_works(scratch):
    good = _published(scratch)
    _edit_acl(scratch, HV7, ["family-compressors"])  # u03 would see the HV steps
    code, report = _run(scratch)
    assert code == EXIT_VALIDATION_FAILED
    assert any(not v["passed"] and v["name"] == "fact:us1-u03-no-hv-steps"
               for v in report["validation"])
    assert _published(scratch) == good
    _edit_acl(scratch, HV7, ["cert-hv", "family-compressors"])

    versions = [r[0] for r in _q(scratch, "SELECT dataset_version FROM control.runs"
                                          " WHERE outcome = 'published' ORDER BY started_at")]
    target = versions[-2]
    result = CliRunner().invoke(app, ["rollback", target])
    assert result.exit_code == 0, result.output
    assert _published(scratch) == target
    refused = CliRunner().invoke(app, ["rollback", report["dataset_version"]])
    assert refused.exit_code == 1  # a version that failed validation cannot be served
