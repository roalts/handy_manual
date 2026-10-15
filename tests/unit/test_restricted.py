from copilot_ingest.models import Anchor, Passage
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


def _setup(*others):
    steps = _p("s1", "hv7", "Step 14: set P9.01 to 1. Measure TP1 to TP2, below 50 V DC.",
               role="parent", block_types=("procedure_step",))
    passages = [steps, *others]
    procs = build_procedures(DOCS, passages, ["cert-hv", "cert-refrigerant"])
    items = propose_markers(procs, passages)
    return procs, passages, items


def test_two_markers_add_procedure_groups():
    leak = _p("w1", "wiki", "Quick way: P9.01 to 1 then check TP1/TP2 with the meter.")
    procs, passages, items = _setup(leak)
    result = tag(procs, passages)
    assert leak.restricted_groups == ["cert-hv", "family-compressors"]
    assert leak.restricted_tags == ["HV-PROC-07"]
    assert "w1" in result.tagged
    assert items and items[0].kind == "marker_approval"  # proposals await approval


def test_document_name_alone_is_not_restricted():
    mention = _p("w2", "wiki", "E-31 needs an HV technician: follow HV-PROC-07.")
    procs, passages, _ = _setup(mention)
    tag(procs, passages)
    assert mention.restricted_groups == [] and mention.restricted_tags == []


def test_one_marker_is_not_enough():
    single = _p("w3", "wiki", "Drive parameter P9.01 exists on the keypad.")
    procs, passages, _ = _setup(single)
    tag(procs, passages)
    assert single.restricted_groups == []


def test_tagging_never_removes_groups():
    leak = _p("w4", "wiki", "P9.01 then TP1 and TP2.")
    leak.restricted_groups = ["role-lead"]
    procs, passages, _ = _setup(leak)
    tag(procs, passages)
    assert set(leak.restricted_groups) >= {"role-lead", "cert-hv", "family-compressors"}


PROC_STEPS = ("1. Isolate the drive at the main switch and lock it\n"
              "2. Wait ten minutes for the DC bus to discharge fully\n"
              "3. Measure the bus voltage between both terminals\n"
              "4. Reset the drive fault from the keypad after the check")


def _vectors(table):
    """Fake embedder: each text maps to a fixed 2-d vector by its first word."""
    return lambda texts: [table[t.split()[0]] for t in texts]


def _setup_steps(other):
    proc = _p("s1", "hv7", PROC_STEPS, role="parent", block_types=("procedure_step",))
    passages = [proc, other]
    return build_procedures(DOCS, passages, ["cert-hv"]), passages


def test_passage_reproducing_three_steps_is_restricted():
    leak = _p("w5", "wiki", "1. Isolate the drive at the main switch first\n"
                            "2. Wait ten minutes for the bus to discharge\n"
                            "3. Measure the bus voltage on the terminals")
    procs, passages = _setup_steps(leak)
    same = [1.0, 0.0]
    result = tag(procs, passages, _vectors({"Isolate": same, "Wait": [0.0, 1.0],
                                            "Measure": [0.7071, 0.7071], "Reset": [-1.0, 0.0]}))
    assert leak.restricted_groups == ["cert-hv", "family-compressors"]
    assert result.review == []


def test_two_shared_generic_steps_are_not_restricted():
    generic = _p("w6", "wiki", "1. Isolate the drive at the main switch first\n"
                               "2. Wait ten minutes for the bus to discharge\n"
                               "3. Replace the air filter element and the cover")
    procs, passages = _setup_steps(generic)
    other = [0.0, 0.0, -1.0]
    tag(procs, passages, _vectors({"Isolate": [1.0, 0.0, 0.0], "Wait": [0.0, 1.0, 0.0],
                                   "Replace": [0.0, 0.0, 1.0], "Measure": other, "Reset": other}))
    assert generic.restricted_groups == []


def test_tag_spreads_between_parent_and_children_not_siblings():
    parent = _p("w9", "wiki", "Quick way: P9.01 to 1 then check TP1/TP2.", role="parent")
    child = _p("w9c1", "wiki", "Then close the cabinet.", role="child")
    child.parent_passage_id = "w9"
    procs, passages, _ = _setup(parent, child)
    tag(procs, passages)
    assert child.restricted_groups == ["cert-hv", "family-compressors"]

    leaky = _p("c1", "wiki", "P9.01 then TP1 and TP2.", role="child")
    sibling = _p("c2", "wiki", "Close the cabinet.", role="child")
    top = _p("top", "wiki", "Overview only.", role="parent")  # not tagged on its own text
    leaky.parent_passage_id = sibling.parent_passage_id = "top"
    procs, passages, _ = _setup(top, leaky, sibling)
    tag(procs, passages)
    assert top.restricted_groups == ["cert-hv", "family-compressors"]
    assert sibling.restricted_groups == []


def test_prose_is_not_compared():
    prose = _p("w7", "wiki", "Do not open the drive cabinet. Request HV on the work order.")
    procs, passages = _setup_steps(prose)
    tag(procs, passages, _vectors({}))  # would raise KeyError if prose were embedded
    assert prose.restricted_groups == []


def test_borderline_step_matches_are_restricted_and_reviewed():
    para = _p("w8", "wiki", "1. Lock out the drive at the main switch\n"
                            "2. Allow ten minutes for the bus to discharge\n"
                            "3. Check the bus voltage on the terminals")
    procs, passages = _setup_steps(para)
    # Two steps match strongly, a third only at the borderline level.
    e1, e2, e3, e4 = ([1.0 if i == k else 0.0 for i in range(4)] for k in range(4))
    vectors = _vectors({"Lock": e1, "Allow": e2, "Check": [0.0, 0.0, 0.72, 0.694],
                        "Isolate": e1, "Wait": e2, "Measure": e3, "Reset": e4})
    result = tag(procs, passages, vectors, {"wiki": "confluence/page.html"})
    assert para.restricted_groups == ["cert-hv", "family-compressors"]
    assert [r.kind for r in result.review] == ["restricted_borderline"]
    assert result.review[0].path == "confluence/page.html"
