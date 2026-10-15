"""Engine pipeline offline: fake serving layer, scripted model (no network)."""
import pytest

from copilot_answer import config
from copilot_answer.engine import ConfigurationError, Engine
from copilot_answer.restricted import marker_hits, unsatisfied
from copilot_answer.serving import Document, Passage, ProcedureAlt
from copilot_contracts import AskRequest, PreviousTurn
from tests.answer.fakes import (
    HV_MARKERS,
    HV_TECH,
    NA_TECH,
    FakeServing,
    corpus,
    dump,
    identity,
    label,
    scripted,
    sentence,
)


def ask(engine, groups, question, **kw):
    return engine.answer(identity("t", groups), AskRequest(question=question, **kw))


def test_grounded_answer_cites_supplied_passages():
    llm = scripted(lambda p: {"sentences": [sentence(
        "E-31 on the VRS-110 is a VFD overcurrent fault.", label(p, "E-31 is a VFD"))]})
    resp = ask(Engine(corpus(), llm), HV_TECH, "What does E-31 mean on TAC-C-0143?")
    assert resp.status == "answer"
    assert resp.asset.asset_id == "TAC-C-0143"
    [s] = resp.sentences
    assert s.citations == ["p_vrs1"]
    assert resp.citations["p_vrs1"].title == "Vastra VRS-110 Service Manual"


def test_fabricated_value_is_regenerated_then_dropped():
    def gen(p):
        lab = label(p, "Tighten the casing bolts to 45")
        return {"sentences": [sentence("Torque the casing bolts to 45 N-m.", lab),
                              sentence("Use 52 N-m on the second pass.", lab)]}
    llm = scripted(gen, regenerate=lambda p: {"fixes": [
        {"index": 1, "drop": False, "text": "Use 55 N-m on the second pass.", "cites": ["P1"]}]})
    resp = ask(Engine(corpus(), llm), NA_TECH, "Casing bolt torque on the HCP-350 FRS-P-0012?")
    texts = [seg.text for s in resp.sentences for seg in s.segments]
    assert texts == ["Torque the casing bolts to 45 N-m."]
    assert [v for v, _ in llm.prompts].count(config.PROMPT_REGENERATE) == 1


def test_other_model_passage_is_never_offered():
    llm = scripted(lambda p: {"sentences": [sentence(
        "Torque the casing bolts to 45 N-m.", label(p, "Tighten the casing bolts to 45"))]})
    ask(Engine(corpus(), llm), NA_TECH, "Casing bolt torque on FRS-P-0012?")
    assert all("60 N-m" not in prompt for _, prompt in llm.prompts)


def test_applying_bulletin_is_evidence_and_notice():
    llm = scripted(lambda p: {"sentences": [sentence(
        "Use 38 N-m on this unit.", label(p, "For HCP-350 serials"))]})
    resp = ask(Engine(corpus(), llm), NA_TECH, "Casing bolt torque on FRS-P-0031?")
    assert resp.status == "answer"
    assert [n.kind for n in resp.notices].count("bulletin") == 1
    assert resp.asset.bulletins[0].status == "affected"


def test_clarify_when_candidates_differ_without_model_calls():
    llm = scripted(lambda p: pytest.fail("no generation expected"))
    resp = ask(Engine(corpus(), llm), NA_TECH, "Casing bolt torque on the HCP-350 at Fresno?")
    assert resp.status == "clarify"
    assert {o.asset_id for o in resp.clarification.options} == {"FRS-P-0012", "FRS-P-0031"}
    assert llm.prompts == []


def test_unknown_asset_abstains():
    llm = scripted(lambda p: pytest.fail("no generation expected"))
    resp = ask(Engine(corpus(), llm), NA_TECH, "Seal kit for FRS-P-9999?")
    assert (resp.status, resp.abstain_reason) == ("abstain", "unknown_asset")


def test_no_permitted_source_abstains():
    llm = scripted(lambda p: pytest.fail("no generation expected"))
    resp = ask(Engine(corpus(), llm), frozenset({"region-na"}), "Belt tracking on a BX-20?")
    assert resp.status == "abstain"
    assert resp.abstain_reason in {"no_permitted_source", "not_visible"}
    assert resp.sentences == []


def test_not_covered_abstains():
    llm = scripted(lambda p: pytest.fail("no generation expected"),
                   sufficiency=lambda p: {"covered": False, "out_of_scope": False,
                                          "restricted_procedure": None, "reason": "not covered"})
    resp = ask(Engine(corpus(), llm), HV_TECH, "What is the warranty on TAC-C-0143?")
    assert (resp.status, resp.abstain_reason) == ("abstain", "no_permitted_source")


def _restricted_llm():
    suff = lambda p: {"covered": True, "out_of_scope": False,  # noqa: E731
                      "restricted_procedure": "HV-PROC-07", "reason": "reset needs it"}

    def gen(p):
        lab = label(p, "E-31 is a VFD")
        return {"sentences": [
            sentence("E-31 is a VFD overcurrent fault; the reset is done under HV-PROC-07.", lab),
            sentence("Set P9.01 to 1 and test at 1,000 V DC.", lab),
            sentence("Reset it on the drive keypad.", lab, kind="step", step=1)],
            "work_order": {"needed": True, "summary": "E-31 on TAC-C-0143 needs HV reset.",
                           "fault_code": "E-31", "parts": [], "cites": [lab]}}

    leak_again = lambda p: {"fixes": [  # noqa: E731
        {"index": 1, "drop": False, "text": "Prove TP1 is below 50 V DC.", "cites": ["P1"]}]}
    return scripted(gen, sufficiency=suff, regenerate=leak_again)


def test_restricted_never_discloses_markers_or_steps():
    llm = _restricted_llm()
    resp = ask(Engine(corpus(), llm), NA_TECH, "How do I reset E-31 on TAC-C-0143?")
    assert resp.status == "restricted"
    assert resp.restricted.procedure == "HV-PROC-07"
    assert resp.restricted.missing_groups == ["cert-hv"]
    assert all(s.kind != "step" for s in resp.sentences)
    assert marker_hits(dump(resp), HV_MARKERS) == []
    # The procedure body is hidden by the database filter: never given to the model.
    assert all("P9.01" not in prompt for v, prompt in llm.prompts
               if v != config.PROMPT_REGENERATE)
    wo = resp.work_order_suggestion
    assert wo.asset_id == "TAC-C-0143"
    assert wo.required_certification == ["cert-hv"]


def test_certified_user_gets_the_procedure():
    def gen(p):
        lab = label(p, "Test insulation")
        return {"sentences": [sentence("Set P9.01 to 1.", lab, kind="step", step=1)]}
    resp = ask(Engine(corpus(), scripted(gen)), HV_TECH, "How do I reset E-31 on TAC-C-0143?")
    assert resp.status == "answer"
    assert resp.sentences[0].citations == ["p_hv7"]


def test_dataset_embedding_mismatch_is_a_configuration_error():
    s = FakeServing()
    with pytest.raises(ConfigurationError):
        Engine(s, scripted(lambda p: {}), embedding_dims=7)


def test_answer_cache_scope_includes_groups_and_version():
    seen = []

    def gen(p):
        return {"sentences": [sentence("E-31 is a VFD overcurrent fault.",
                                       label(p, "E-31 is a VFD"))]}
    llm = scripted(gen)
    original = llm.complete_json

    def spy(model, prompt, schema, version, scope, meter):
        seen.append(scope)
        return original(model, prompt, schema, version, scope, meter)
    llm.complete_json = spy
    engine = Engine(corpus(), llm)
    ask(engine, HV_TECH, "What does E-31 mean on TAC-C-0143?")
    ask(engine, HV_TECH | {"cert-refrigerant"}, "What does E-31 mean on TAC-C-0143?")
    assert len(set(seen)) == 2
    assert all("ds_9001" in s for s in seen)


def test_not_visible_when_relevant_hidden_content_exists():
    llm = scripted(lambda p: pytest.fail("no generation expected"))
    resp = ask(Engine(corpus(), llm), frozenset({"region-na"}), "What does E-31 mean on a VRS-110?")
    assert (resp.status, resp.abstain_reason) == ("abstain", "not_visible")
    assert "E-31 is a VFD" not in dump(resp)


def test_hidden_but_unrelated_content_is_no_permitted_source():
    s = corpus()
    s.hidden_distance = 0.9
    llm = scripted(lambda p: pytest.fail("no generation expected"))
    resp = ask(Engine(s, llm), frozenset({"region-na"}), "What does E-31 mean on a VRS-110?")
    assert (resp.status, resp.abstain_reason) == ("abstain", "no_permitted_source")


def test_restricted_model_level_answer_suggests_work_order_without_asset():
    resp = ask(Engine(corpus(), _restricted_llm()), NA_TECH, "How do I reset E-31 on a VRS-110?")
    assert resp.status == "restricted" and resp.asset is None
    wo = resp.work_order_suggestion
    assert wo.asset_id is None
    assert wo.fault_code == "E-31"
    assert wo.required_certification == ["cert-hv"]


def test_markers_come_from_the_serving_layer():
    s = corpus()
    s.markers = {"HV-PROC-07": (*HV_MARKERS, "OVERCURRENT")}
    resp = ask(Engine(s, _restricted_llm()), NA_TECH, "How do I reset E-31 on TAC-C-0143?")
    assert resp.status in {"restricted", "abstain"}
    assert "overcurrent" not in dump(resp).casefold()


def test_no_suggestion_without_machine_unless_restricted_or_parts():
    def gen(p):
        lab = label(p, "Tighten the casing bolts to 45")
        return {"sentences": [sentence("Torque the casing bolts to 45 N-m.", lab)],
                "work_order": {"needed": True, "summary": "Retorque.", "fault_code": None,
                               "parts": [], "cites": [lab]}}
    resp = ask(Engine(corpus(), scripted(gen)), NA_TECH, "Casing bolt torque on an HCP-350?")
    assert resp.status == "answer" and resp.work_order_suggestion is None


def test_certification_decided_by_code_from_procedure_in_evidence():
    def gen(p):
        lab = label(p, "Test insulation")
        return {"sentences": [sentence("Set P9.01 to 1.", lab, kind="step", step=1)],
                "work_order": {"needed": True, "summary": "Reset the drive.", "fault_code": "E-31",
                               "parts": [], "cites": [lab]}}
    resp = ask(Engine(corpus(), scripted(gen)), HV_TECH, "How do I reset E-31 on TAC-C-0143?")
    assert resp.status == "answer"
    assert resp.work_order_suggestion.required_certification == ["cert-hv"]


def test_certification_from_passage_tagged_with_procedure():
    s = corpus()
    s.corpus["p_iom"].restricted_tags = ["HV-PROC-07"]

    def gen(p):
        lab = label(p, "Tighten the casing bolts to 45")
        return {"sentences": [sentence("Torque the casing bolts to 45 N-m.", lab)],
                "work_order": {"needed": True, "summary": "Retorque.", "fault_code": None,
                               "parts": [], "cites": [lab]}}
    resp = ask(Engine(s, scripted(gen)), HV_TECH, "Casing bolt torque on FRS-P-0012?")
    assert resp.work_order_suggestion.required_certification == ["cert-hv"]


# ------------------------------------------------------------------ did you mean

def _no_model():
    return scripted(lambda p: pytest.fail("no model call expected"))


def test_unknown_model_suggests_close_known_model_without_model_calls():
    llm = _no_model()
    resp = ask(Engine(corpus(), llm), NA_TECH,
               "What's the impeller-to-casing clearance spec on an HCP-20?")
    assert resp.status == "clarify"
    assert resp.clarification.question == "Did you mean HCP-200?"
    [opt] = resp.clarification.options
    assert (opt.label, opt.asset_id) == ("HCP-200", None)
    assert opt.question == "What's the impeller-to-casing clearance spec on an HCP-200?"
    assert llm.prompts == []


def test_unknown_model_without_close_match_says_it_is_not_in_the_documents():
    resp = ask(Engine(corpus(), _no_model()), NA_TECH, "Seal kit for an HCP-90?")
    assert (resp.status, resp.abstain_reason) == ("abstain", "no_permitted_source")
    assert [n.kind for n in resp.notices] == ["no_answer"]
    assert "not a model in the documents" in resp.notices[0].text


def test_unknown_asset_suggests_close_fleet_id():
    resp = ask(Engine(corpus(), _no_model()), NA_TECH, "Casing torque on frs-p-0013?")
    assert resp.status == "clarify"
    assert [o.question for o in resp.clarification.options] == ["Casing torque on FRS-P-0012?"]


def test_model_only_in_hidden_documents_is_not_a_typo():
    resp = ask(Engine(corpus(), _no_model()), frozenset({"region-na"}),
               "What's the impeller clearance on an HCP-200?")
    assert (resp.status, resp.abstain_reason) == ("abstain", "not_visible")


# ------------------------------------------------------------------ follow-ups

TYPO_Q = "What's the impeller-to-casing clearance spec on an HCP-20?"
FIXED_Q = "What's the impeller-to-casing clearance spec on an HCP-200?"


def _prev(question, asset_id=None):
    return PreviousTurn(answer_id="ans_prev", question=question, asset_id=asset_id)


def test_followup_is_rewritten_into_a_standalone_question():
    def follow(p):
        assert TYPO_Q in p and "Oh, I meant HCP-200" in p
        return {"continues": True, "standalone_question": FIXED_Q}
    llm = scripted(lambda p: {"sentences": [sentence(
        "The clearance is 0.38–0.50 mm.", label(p, "Impeller-to-casing"))]}, followup=follow)
    resp = ask(Engine(corpus(), llm), NA_TECH, "Oh, I meant HCP-200", previous=_prev(TYPO_Q))
    assert resp.status == "answer"
    assert resp.question_used == FIXED_Q
    assert resp.sentences[0].citations == ["p_200"]


def test_new_topic_is_used_as_typed():
    llm = scripted(lambda p: {"sentences": [sentence(
        "E-31 is a VFD overcurrent fault.", label(p, "E-31 is a VFD"))]},
        followup=lambda p: {"continues": False, "standalone_question": "ignored"})
    q = "What does E-31 mean on TAC-C-0143?"
    resp = ask(Engine(corpus(), llm), HV_TECH, q, previous=_prev(FIXED_Q))
    assert resp.question_used is None
    assert resp.asset.asset_id == "TAC-C-0143"


def test_no_previous_means_no_followup_call():
    llm = scripted(lambda p: {"sentences": [sentence(
        "E-31 is a VFD overcurrent fault.", label(p, "E-31 is a VFD"))]})
    ask(Engine(corpus(), llm), HV_TECH, "What does E-31 mean on TAC-C-0143?")
    assert config.PROMPT_FOLLOWUP not in [v for v, _ in llm.prompts]


def test_followup_naming_another_asset_switches_machine():
    llm = scripted(lambda p: {"sentences": [sentence(
        "Torque the casing bolts to 45 N-m.", label(p, "Tighten the casing bolts to 45"))]},
        followup=lambda p: {"continues": True,
                            "standalone_question": "Casing bolt torque on FRS-P-0012?"})
    resp = ask(Engine(corpus(), llm), NA_TECH, "and on FRS-P-0012?",
               previous=_prev("Casing bolt torque on FRS-P-0031?", "FRS-P-0031"))
    assert resp.asset.asset_id == "FRS-P-0012"


def test_restricted_followup_carries_the_machine_and_stays_restricted():
    llm = _restricted_llm()
    inner = llm.handler
    llm.handler = lambda v, p: ({"continues": True, "standalone_question": "How do I reset E-31?"}
                                if v == config.PROMPT_FOLLOWUP else inner(v, p))
    resp = ask(Engine(corpus(), llm), NA_TECH, "how do I reset it?",
               previous=_prev("What does E-31 mean on TAC-C-0143?", "TAC-C-0143"))
    assert resp.status == "restricted"
    assert resp.asset.asset_id == "TAC-C-0143"
    assert resp.question_used == "How do I reset E-31?"
    assert marker_hits(dump(resp), HV_MARKERS) == []


@pytest.mark.parametrize(("groups", "question", "reason", "kind"), [
    (NA_TECH, "Seal kit for FRS-P-9999?", "unknown_asset", "no_answer"),
    (frozenset({"region-na"}), "What's the impeller clearance on an HCP-200?", "not_visible",
     "not_visible"),
])
def test_abstain_notice_kind_follows_the_reason(groups, question, reason, kind):
    resp = ask(Engine(corpus(), _no_model()), groups, question)
    assert resp.abstain_reason == reason
    assert [n.kind for n in resp.notices] == [kind]


def test_not_covered_abstain_has_no_answer_notice():
    llm = scripted(lambda p: pytest.fail("no generation expected"),
                   sufficiency=lambda p: {"covered": False, "out_of_scope": True,
                                          "restricted_procedure": None, "reason": "off topic"})
    resp = ask(Engine(corpus(), llm), HV_TECH, "What's the weather at TAC-C-0143?")
    assert (resp.abstain_reason, [n.kind for n in resp.notices]) == ("out_of_scope", ["no_answer"])


def test_evidence_labels_never_reach_the_technician():
    def gen(p):
        lab = label(p, "E-31 is a VFD")
        return {"sentences": [sentence(f"E-31 on the VRS-110 is a VFD overcurrent fault [{lab}].",
                                       lab),
                              sentence("Torque the casing bolts to 45 N-m (P1).", lab)]}

    def regen(p):
        return {"fixes": [{"index": 1, "drop": False, "cites": [label(p, "E-31 is a VFD")],
                           "text": "E-31 means the drive saw overcurrent [P1, P2]."}]}

    resp = ask(Engine(corpus(), scripted(gen, regenerate=regen)), HV_TECH,
               "What does E-31 mean on TAC-C-0143?")
    texts = ["".join(seg.text or "" for seg in s.segments) for s in resp.sentences]
    assert texts == ["E-31 on the VRS-110 is a VFD overcurrent fault.",
                     "E-31 means the drive saw overcurrent."]
    assert "[P" not in dump(resp) and "(P1" not in dump(resp)


def test_labels_removed_from_conflicts_and_work_order_summary():
    from copilot_answer.engine import _without_labels

    out = _without_labels({
        "sentences": [],
        "conflicts": [{"topic": "Top-up [P3]", "sides": [
            {"statement": "KT-WI-14 allows a top-up (P3).", "cites": ["P3"]},
            {"statement": "SOP-020 forbids it [P5, P6].", "cites": ["P5"]}]}],
        "work_order": {"needed": True, "summary": "Replace EXV [P2].", "cites": ["P2"]},
    })
    assert out["conflicts"][0]["topic"] == "Top-up"
    assert [s["statement"] for s in out["conflicts"][0]["sides"]] == [
        "KT-WI-14 allows a top-up.", "SOP-020 forbids it."]
    assert out["conflicts"][0]["sides"][0]["cites"] == ["P3"]
    assert out["work_order"]["summary"] == "Replace EXV."


def test_sentence_with_an_unsourced_tag_or_date_is_regenerated_then_dropped():
    def gen(p):
        lab = label(p, "Tighten the casing bolts to 45")
        return {"sentences": [sentence("Torque the casing bolts to 45 N-m.", lab),
                              sentence("Check that TS-2 reads normal before restart.", lab),
                              sentence("The joint was last opened on 2026-07-28.", lab)]}
    llm = scripted(gen, regenerate=lambda p: {"fixes": [
        {"index": 1, "drop": True, "text": "", "cites": []},
        {"index": 2, "drop": False, "text": "The joint was last opened on 2026-07-29.",
         "cites": ["P1"]}]})
    resp = ask(Engine(corpus(), llm), NA_TECH, "Casing bolt torque on the HCP-350 FRS-P-0012?")
    texts = [seg.text for s in resp.sentences for seg in s.segments]
    assert texts == ["Torque the casing bolts to 45 N-m."]
    [regen] = [prompt for v, prompt in llm.prompts if v == config.PROMPT_REGENERATE]
    assert "not in cited passages: TS-2" in regen
    assert "not in cited passages: 2026-07-28" in regen


# ------------------------------------------------------------------ completeness pass

@pytest.fixture
def complete_on(monkeypatch):
    monkeypatch.setattr(config, "COMPLETE_ENABLED", True)


def _torque_answer(p):
    return {"sentences": [sentence("Use 38 N-m on this unit.", label(p, "For HCP-350 serials"))]}


def _added(p, text):
    return {"additions": [{"after": 0, "kind": "warning", "text": text,
                           "cites": [label(p, "For HCP-350 serials")]}]}


def test_completeness_pass_is_off_unless_enabled():
    llm = scripted(_torque_answer, complete=lambda p: pytest.fail("pass is off"))
    resp = ask(Engine(corpus(), llm), NA_TECH, "Casing bolt torque on FRS-P-0031?")
    assert len(resp.sentences) == 1


@pytest.mark.usefixtures("complete_on")
def test_completeness_pass_adds_a_cited_fact_the_answer_left_out():
    llm = scripted(_torque_answer, complete=lambda p: _added(
        p, "45 N-m applies only to HCP-350 serials before HCP350-240001."))
    resp = ask(Engine(corpus(), llm), NA_TECH, "Casing bolt torque on FRS-P-0031?")
    assert resp.status == "answer"
    texts = ["".join(seg.text or "" for seg in s.segments) for s in resp.sentences]
    assert texts == ["Use 38 N-m on this unit.",
                     "45 N-m applies only to HCP-350 serials before HCP350-240001."]
    assert resp.sentences[1].kind == "warning"
    assert resp.sentences[1].citations == ["p_sb9"]
    [prompt] = [prompt for v, prompt in llm.prompts if v == config.PROMPT_COMPLETE]
    assert '"HCP350-240001"' in prompt and "45 N-m" in prompt
    assert "timings_ms" in resp.model_dump() and "complete" in resp.timings_ms


@pytest.mark.usefixtures("complete_on")
def test_completeness_addition_failing_the_citation_check_is_dropped():
    def add(p):
        lab = label(p, "For HCP-350 serials")
        return {"additions": [
            {"after": 0, "kind": "statement", "text": "Use 52 N-m on older serials.",
             "cites": [lab]},
            {"after": 0, "kind": "statement", "text": "This range starts at HCP350-240001.",
             "cites": [lab]}]}
    resp = ask(Engine(corpus(), scripted(_torque_answer, complete=add)), NA_TECH,
               "Casing bolt torque on FRS-P-0031?")
    texts = ["".join(seg.text or "" for seg in s.segments) for s in resp.sentences]
    assert texts == ["Use 38 N-m on this unit.", "This range starts at HCP350-240001."]


@pytest.mark.usefixtures("complete_on")
def test_completeness_addition_with_a_marker_keeps_the_first_answer():
    llm = scripted(_torque_answer, complete=lambda p: _added(
        p, "Serials from HCP350-240001 are revised; prove TP1 first."))
    resp = ask(Engine(corpus(), llm), NA_TECH, "Casing bolt torque on FRS-P-0031?")
    assert [len(s.segments) and s.segments[0].text for s in resp.sentences] == [
        "Use 38 N-m on this unit."]
    assert marker_hits(dump(resp), HV_MARKERS) == []


@pytest.mark.usefixtures("complete_on")
def test_completeness_addition_close_to_hidden_content_keeps_the_first_answer():
    s = corpus()
    s.hidden_distance = 0.1  # the hidden HV-PROC-07 passage is very close to anything asked

    def gen(p):
        return {"sentences": [sentence("On the VRS-110 this is a VFD overcurrent fault.",
                                       label(p, "E-31 is a VFD"))]}

    def add(p):
        return {"additions": [{"after": 0, "kind": "statement", "cites": [label(p, "E-31 is a")],
                               "text": "E-31 can't be reset from the operator panel."}]}
    resp = ask(Engine(s, scripted(gen, complete=add)), NA_TECH,
               "What does E-31 mean on TAC-C-0143?")
    assert resp.status == "answer"
    assert len(resp.sentences) == 1
    # Not close: the same addition is kept.
    s.hidden_distance = 0.3
    resp = ask(Engine(s, scripted(gen, complete=add)), NA_TECH,
               "What does E-31 mean on TAC-C-0143?")
    assert len(resp.sentences) == 2


@pytest.mark.usefixtures("complete_on")
def test_completeness_drops_additions_naming_a_withheld_procedure_or_repeating_the_answer():
    def gen(p):
        return {"sentences": [sentence("On the VRS-110 this is a VFD overcurrent fault.",
                                       label(p, "E-31 is a VFD"))]}

    def add(p):
        lab = [label(p, "E-31 is a")]
        return {"additions": [
            {"after": 0, "kind": "statement", "cites": lab,
             "text": "The E-31 reset is done under HV-PROC-07."},
            {"after": 0, "kind": "statement", "cites": lab,
             "text": "This is a VFD overcurrent fault on the VRS-110."},
            {"after": 0, "kind": "statement", "cites": lab,
             "text": "E-31 can't be reset from the operator panel."}]}
    llm = scripted(gen, complete=add)
    resp = ask(Engine(corpus(), llm), NA_TECH, "What does E-31 mean on TAC-C-0143?")
    texts = ["".join(seg.text or "" for seg in s.segments) for s in resp.sentences]
    assert texts == ["On the VRS-110 this is a VFD overcurrent fault.",
                     "E-31 can't be reset from the operator panel."]
    [prompt] = [prompt for v, prompt in llm.prompts if v == config.PROMPT_COMPLETE]
    assert "HV-PROC-07" not in prompt.split("Passages:")[0]


@pytest.mark.usefixtures("complete_on")
def test_no_completeness_pass_for_restricted_answers_or_when_nothing_is_missing():
    llm = _restricted_llm()
    ask(Engine(corpus(), llm), NA_TECH, "How do I reset E-31 on TAC-C-0143?")
    assert config.PROMPT_COMPLETE not in [v for v, _ in llm.prompts]

    def whole(p):
        return {"sentences": [sentence(
            "Clearance is 0.38–0.50 mm diametral.", label(p, "Impeller-to-casing"))]}
    llm = scripted(whole, complete=lambda p: pytest.fail("nothing is missing"))
    resp = ask(Engine(corpus(), llm), NA_TECH, "Impeller clearance on an HCP-200?")
    assert resp.status == "answer"
    assert config.PROMPT_COMPLETE not in [v for v, _ in llm.prompts]


# ------------------------------------------------------------------ restricted backstop

PIT_Q = ("I need to clean the foot strainer in pump pit PP-1 at Fresno. How do I enter the pit "
         "safely?")
ISOLATE_Q = ("How do I electrically isolate TAC-C-0143 and prove the VFD cabinet is dead before "
             "I work inside it?")
NOT_COVERED = {"covered": False, "out_of_scope": False, "restricted_procedure": None,
               "reason": "no isolation steps"}


def _backstop_corpus() -> FakeServing:
    s = corpus()
    s.add_doc(Document("d_pit", "Halden HCP-200 Manual", "service_manual", 3, ("HCP-200",)),
              frozenset({"family-pumps"}),
              Passage("p_pit", "d_pit", "Installation in pits: before entering the pit, observe "
                      "the local rules for confined spaces (gas measurement, ventilation, safety "
                      "attendant).", anchor={"page": 2}))
    s.add_doc(Document("d_wog", "Work Order Writing Guide", "wiki", 4),
              frozenset({"region-na"}),
              Passage("p_wog", "d_wog", "Entering a pump pit at Fresno or any other permit "
                      "space: Confined space, plus the permit under CS-PROC-03."))
    s.add_doc(Document("d_fs", "FS-STD-001 Field Service Standard", "controlled_procedure", 1),
              frozenset({"region-na"}),
              Passage("p_fs", "d_fs", "HV: any work inside an enclosure with exposed live parts, "
                      "for example a VFD cabinet. See HV-PROC-02.",
                      heading_path=["7.1 Required certification on every work order"]))
    s.add_doc(Document("d_cs3", "CS-PROC-03 Confined Space Entry, Pump Pits",
                       "controlled_procedure", 1), frozenset({"cert-confined-space"}),
              Passage("p_cs3", "d_cs3", "Test the atmosphere at three levels; oxygen 19.5% to "
                      "23.5%.", restricted_tags=["CS-PROC-03"]))
    s.add_doc(Document("d_hv2", "HV-PROC-02 Electrical Isolation Verification",
                       "controlled_procedure", 1), frozenset({"cert-hv"}),
              Passage("p_hv2", "d_hv2", "Lock each isolation point; prove-test-prove with a "
                      "voltage tester.", restricted_tags=["HV-PROC-02"]))
    s.procs += [
        ProcedureAlt("CS-PROC-03", "CS-PROC-03 Confined Space Entry, Pump Pits", "d_cs3",
                     frozenset({"cert-confined-space"})),
        ProcedureAlt("HV-PROC-02", "HV-PROC-02 Electrical Isolation Verification", "d_hv2",
                     frozenset({"cert-hv"})),
    ]
    return s


def _pit_answer(p):
    """What the model wrote for cs3-uncert: the procedure named as the way, with its controls."""
    return {"sentences": [
        sentence("Pit entry falls under CS-PROC-03.", label(p, "Entering a pump pit")),
        sentence("Perform gas measurement, provide ventilation and assign a safety attendant.",
                 label(p, "Installation in pits"), kind="step", step=1)]}


def test_backstop_restricts_an_answer_naming_the_procedure_that_covers_the_work():
    llm = scripted(_pit_answer)  # sufficiency: covered, no restricted procedure
    resp = ask(Engine(_backstop_corpus(), llm), NA_TECH, PIT_Q)
    assert resp.status == "restricted"
    assert resp.restricted.procedure == "CS-PROC-03"
    assert resp.restricted.missing_groups == ["cert-confined-space"]
    assert all(s.kind != "step" for s in resp.sentences)
    assert "cert-confined-space" in resp.work_order_suggestion.required_certification
    [gen_prompt] = [p for v, p in llm.prompts if v == config.PROMPT_GENERATE]
    assert "NOT certified for CS-PROC-03" in gen_prompt


def test_backstop_turns_a_not_covered_abstain_into_restricted():
    def gen(p):
        return {"sentences": [sentence(
            "Work inside a VFD cabinet needs HV certification under HV-PROC-02.",
            label(p, "HV: any work inside"))]}
    llm = scripted(gen, sufficiency=lambda p: NOT_COVERED)
    resp = ask(Engine(_backstop_corpus(), llm), NA_TECH, ISOLATE_Q)
    assert resp.status == "restricted"
    assert resp.restricted.procedure == "HV-PROC-02"
    assert resp.restricted.missing_groups == ["cert-hv"]
    assert "p_fs" in resp.restricted.citations
    assert all("prove-test-prove" not in p for _, p in llm.prompts)


def test_backstop_keeps_certified_outcomes():
    s = _backstop_corpus()
    pit = ask(Engine(s, scripted(_pit_answer)), NA_TECH | {"cert-confined-space"}, PIT_Q)
    assert pit.status == "answer"
    hv = ask(Engine(s, scripted(lambda p: pytest.fail("no generation expected"),
                                sufficiency=lambda p: NOT_COVERED)), HV_TECH, ISOLATE_Q)
    assert (hv.status, hv.abstain_reason) == ("abstain", "no_permitted_source")


def test_backstop_ignores_questions_that_only_mention_the_procedure():
    def gen(p):
        return {"sentences": [sentence("CS-PROC-03 is the permit for pump pit entry.",
                                       label(p, "Entering a pump pit"))]}
    resp = ask(Engine(_backstop_corpus(), scripted(gen)), NA_TECH,
               "What does CS-PROC-03 cover for the pump pits?")
    assert resp.status == "answer"


def test_backstop_finds_a_visible_passage_naming_the_procedure():
    from copilot_answer.engine import Context, Timer
    from copilot_answer.llm import Meter

    s = _backstop_corpus()
    engine = Engine(s, _no_model())
    ctx = Context(identity("t", NA_TECH), AskRequest(question=ISOLATE_Q), "ds_9001", Meter(),
                  Timer())
    ctx.docs = s.documents(NA_TECH)
    uns = unsatisfied(s.procs, NA_TECH)
    proc, added = engine._backstop(ctx, ISOLATE_Q, uns, [])
    assert (proc.name, added.pid) == ("HV-PROC-02", "p_fs")
    del s.corpus["p_fs"]
    assert engine._backstop(ctx, ISOLATE_Q, uns, []) == (None, None)
