import pytest

from copilot_ingest.acl import AccessRules
from copilot_ingest.stages.register import register


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr("copilot_ingest.stages.register.copy_raw", lambda p, fp: p)
    root = tmp_path / "corpus"
    (root / "confluence").mkdir(parents=True)
    (root / "sharepoint").mkdir()
    (root / "confluence" / "ok.html").write_text("<html><body><p>hi</p></body></html>")
    (root / "confluence" / "no_rule.html").write_text("<p>unofficial</p>")
    (root / "confluence" / "bad_group.html").write_text("<p>x</p>")
    (root / "sharepoint" / "empty.docx").write_bytes(b"")
    (root / "confluence" / "notes.xyz").write_text("?")
    (root / ".DS_Store").write_bytes(b"\0")
    return root


@pytest.fixture
def rules():
    return AccessRules(
        documents={"confluence/ok.html": ["region-na"], "confluence/bad_group.html": ["typo"],
                   "sharepoint/empty.docx": [], "confluence/notes.xyz": [],
                   "confluence/gone.html": []},
        source_systems={}, groups={"region-na": ""}, users={"u": ["region-na"]}, titles={})


def _reasons(reg):
    return {q.path: q.reason for q in reg.quarantine}


def test_quarantine_reasons(corpus, rules):
    reg = register(corpus, rules, previous={})
    assert _reasons(reg) == {
        "confluence/no_rule.html": "no_access_rule",
        "confluence/bad_group.html": "unknown_group",
        "sharepoint/empty.docx": "empty_file",
        "confluence/notes.xyz": "unsupported_format",
    }
    assert [f.path for f in reg.active] == ["confluence/ok.html"]
    assert all(".DS_Store" not in f.path for f in reg.files)
    assert reg.acl_without_file == ["confluence/gone.html"]


def test_change_detection(corpus, rules):
    first = register(corpus, rules, previous={})
    prev = {f.path: f.fingerprint for f in first.files}
    prev["confluence/deleted.html"] = "abc"
    (corpus / "confluence" / "ok.html").write_text("<p>changed</p>")
    reg = register(corpus, rules, previous=prev)
    assert reg.changed == ["confluence/ok.html"]
    assert reg.removed == ["confluence/deleted.html"]
    assert reg.added == []
