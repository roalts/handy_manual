import pytest

from copilot_ingest.models import Anchor, ExtractResult, Passage, ReviewItem
from copilot_ingest.review import (
    Decisions,
    InvalidResolution,
    item_id,
    normalize_value,
    with_fingerprint,
)
from copilot_ingest.stages.link import build_history
from copilot_ingest.stages.restricted import build_procedures, propose_markers, tag


def _p(pid, doc, text, role="standard", block_types=("paragraph",)):
    return Passage(passage_id=pid, doc_id=doc, role=role, anchor=Anchor(), text_original=text,
                   block_types=list(block_types), fingerprint="f", extractor_version="t")


DOCS = {
    "hv7": {"path": "sharepoint/HV-PROC-07.docx", "name": "HV-PROC-07", "controlled": True,
            "groups": ["cert-hv", "family-compressors"]},
    "wiki": {"path": "confluence/page.html", "name": "Wiki", "controlled": False,
             "groups": ["family-compressors"]},
}
FPS = {"sharepoint/HV-PROC-07.docx": "fp-hv7"}


def _decide(item: ReviewItem, value) -> Decisions:
    """Decisions holding `value` under the ID the pipeline would store for `item`."""
    stored = with_fingerprint(item.model_copy(), FPS)
    return Decisions({item_id(stored): value}, FPS)


# --- value checks -----------------------------------------------------------------------------

def test_marker_shortcuts_expand_to_the_proposed_markers():
    cand = {"proposed": ["P9.01", "TP1"]}
    assert normalize_value("marker_approval", cand, "approve") == {
        "approved": ["P9.01", "TP1"], "rejected": []}
    assert normalize_value("marker_approval", cand, '{"rejected": ["TP1"]}') == {
        "approved": [], "rejected": ["TP1"]}


@pytest.mark.parametrize("kind,raw", [
    ("marker_approval", "maybe"),
    ("marker_approval", '{"approved": ["TP1"], "rejected": ["TP1"]}'),
    ("restricted_borderline", "approve"),
    ("unknown_asset", '""'),
])
def test_invalid_values_are_refused(kind, raw):
    with pytest.raises(InvalidResolution):
        normalize_value(kind, {"proposed": ["TP1"]}, raw)


def test_decision_lookup_uses_the_source_fingerprint():
    item = ReviewItem(kind="marker_approval", path="sharepoint/HV-PROC-07.docx",
                      field="HV-PROC-07", reason="r", stage="restricted")
    decisions = _decide(item, {"approved": [], "rejected": []})
    assert decisions.get(item) is not None
    changed = Decisions(decisions.values, {"sharepoint/HV-PROC-07.docx": "fp-new"})
    assert changed.get(item) is None  # file changed: the old decision no longer applies


# --- markers ----------------------------------------------------------------------------------

def _marker_setup(*others):
    steps = _p("s1", "hv7", "Step 14: set P9.01 to 1. Measure TP1 to TP2, below 50 V DC.",
               role="parent", block_types=("procedure_step",))
    passages = [steps, *others]
    return build_procedures(DOCS, passages, ["cert-hv"]), passages


def _marker_item():
    return ReviewItem(kind="marker_approval", path="sharepoint/HV-PROC-07.docx",
                      field="HV-PROC-07", reason="r", stage="restricted")


def test_approved_markers_need_no_review_and_still_restrict():
    leak = _p("w1", "wiki", "Quick way: P9.01 to 1 then check TP1/TP2.")
    procs, passages = _marker_setup(leak)
    decisions = _decide(_marker_item(), {"approved": ["P9.01", "TP1", "TP2", "50 V DC"],
                                         "rejected": []})
    assert propose_markers(procs, passages, decisions) == []
    tag(procs, passages)
    assert leak.restricted_groups == ["cert-hv", "family-compressors"]


def test_rejected_markers_are_not_applied():
    mention = _p("w2", "wiki", "The keypad shows P9.01 and TP1 on the service page.")
    procs, passages = _marker_setup(mention)
    decisions = _decide(_marker_item(), {"approved": ["TP2", "50 V DC"],
                                         "rejected": ["P9.01", "TP1"]})
    propose_markers(procs, passages, decisions)
    tag(procs, passages)
    assert mention.restricted_groups == []


# --- borderline -------------------------------------------------------------------------------

PROC = ("1. Isolate the drive at the main switch and lock it\n"
        "2. Wait ten minutes for the DC bus to discharge fully\n"
        "3. Measure the bus voltage between both terminals")
CAND = ("1. Lock out the drive at the main switch\n"
        "2. Allow ten minutes for the bus to discharge\n"
        "3. Check the bus voltage on the terminals")
E = [[1.0 if i == k else 0.0 for i in range(4)] for k in range(4)]
VECTORS = {"Lock": E[0], "Allow": E[1], "Check": [0.0, 0.0, 0.72, 0.694],
           "Isolate": E[0], "Wait": E[1], "Measure": E[2]}


def _borderline(decided):
    proc = _p("s1", "hv7", PROC, role="parent", block_types=("procedure_step",))
    para = _p("w8", "wiki", CAND)
    passages = [proc, para]
    procs = build_procedures(DOCS, passages, ["cert-hv"])
    embed = lambda texts: [VECTORS[t.split()[0]] for t in texts]  # noqa: E731
    paths = {"wiki": "confluence/page.html"}
    first = tag(procs, passages, embed, paths)
    item = first.review[0]
    para.restricted_groups, para.restricted_tags = [], []
    return para, tag(procs, passages, embed, paths, _decide(item, decided))


def test_released_borderline_passage_stays_visible():
    para, result = _borderline("release")
    assert para.restricted_groups == [] and result.review == []
    assert result.released == ["w8"]


def test_confirmed_borderline_passage_is_restricted_without_review():
    para, result = _borderline("restrict")
    assert para.restricted_groups == ["cert-hv", "family-compressors"]
    assert result.review == []


# --- service history --------------------------------------------------------------------------

FLEET = ExtractResult(path="data/fleet_register.csv", fingerprint="fl", extractor="tabular",
                      extractor_version="t", records=[{
                          "_row": 2, "asset_id": "RTM-H-0007", "model": "NK-600",
                          "serial": "NK600-1", "site": "RTM", "region": "EU",
                          "install_date": "", "contract_end": ""}])


def test_unknown_case_asset_mapped_by_reviewer():
    cases = ExtractResult(path="data/sf.json", fingerprint="sf", extractor="salesforce",
                          extractor_version="t", records=[{
                              "case_number": "00049999", "status": "Closed",
                              "created": "2026-03-01", "asset": "RTM-H-07", "serial": "",
                              "site": "", "subject": "E-14", "description": "", "resolution": "",
                              "fault_code": "", "parts_used": "", "owner": "x"}])
    first = build_history(FLEET, [], [(cases, ["region-eu"])])
    assert [i.kind for i in first.review] == ["unknown_asset"]
    item = first.review[0]
    decided = Decisions({item_id(item): "RTM-H-0007"})
    h = build_history(FLEET, [], [(cases, ["region-eu"])], decided)
    assert h.review == [] and h.events[0].asset_id == "RTM-H-0007"


def test_ocr_value_is_kept_verbatim_even_when_numeric():
    from copilot_ingest.review import normalize_value
    assert normalize_value("ocr_value_mismatch", None, "6309") == "6309"
    assert normalize_value("ocr_value_mismatch", None, " 3,2 m ") == "3,2 m"
