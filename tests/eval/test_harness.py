"""The harness against a stub API serving recorded responses (006 US1 independent test).
Offline: no server, no model, no database."""
from copy import deepcopy

import pytest

from copilot_eval.cases import load
from copilot_eval.categorize import CATEGORIES, Failure
from copilot_eval.client import Api, InfrastructureError
from copilot_eval.runner import run
from copilot_ingest.settings import PROJECT_ROOT
from tests.eval.stub import FakeReference, StubApi, load_fixture, users

GOLDEN = [c for c in load(PROJECT_ROOT / "eval") if c.kind == "golden"]

# The 21:55 review of this run: what each incomplete answer misses (the brief's list, plus the
# reference facts noted in evaluation.md).
EXPECTED_MISSES = {
    "q01": {"definition: suction pressure fluctuating more than 15% for 10 s",
            "cause: NPSH available is too low", "the strainer cleaning is section 8.3"},
    "q04": {"FRS-P-0031's own serial: HCP350-241187",
            "the incident: torquing this unit to 45 N-m cracked the gasket seat in June 2026",
            "the incident is case 00041988"},
    "q05": {"E-31 is a VFD overcurrent trip", "notify the site",
            "branch: if E-31 returns within 24 hours, escalate to Vastra L2 and open a High case"},
    "q06": {"it can't be reset from the panel", "so a supervisor assigns a certified technician"},
    "q08": {"reason: the TS-2 harness on this unit runs along the freezer exhaust duct"},
    "q09": {"L-03 is low suction pressure", "RTM-H-0007's own serial: NK600-230415",
            "replace the EXV with 63-1180 rev 3",
            "branch: if the EXV is fine, leak test per SOP-020 before any recharge"},
}


@pytest.fixture
def fixture():
    return load_fixture()


def _run(fixture, stub=None, cases=GOLDEN, ref=None):
    stub = stub or StubApi(fixture)
    return run(cases, Api("http://stub", transport=stub.transport()),
               ref or FakeReference(fixture), users(fixture), embed=None,
               progress=lambda *_: None)


def test_key_facts_file_covers_every_golden_question():
    assert [c.id for c in GOLDEN] == [f"q{i:02}" for i in range(1, 11)]
    for c in GOLDEN:
        assert c.reference and c.outcomes
        assert c.required, c.id
        assert all(f.category for f in c.forbidden)


def test_recorded_run_scores_like_the_review(fixture):
    result = _run(fixture)
    by_id = {r.case.id: r for r in result.results}
    assert all(r.outcome_ok for r in result.results)
    for qid, r in by_id.items():
        missed = {f.fact.fact for f in r.facts if not f.hit}
        assert missed == EXPECTED_MISSES.get(qid, set()), qid
    assert not result.blocking
    # Each missed fact is one failure with one category.
    facts = [f for f in result.failures if f.check == "fact"]
    assert len(facts) == sum(len(v) for v in EXPECTED_MISSES.values())
    assert all(f.category in CATEGORIES for f in result.failures)


def test_missing_fact_in_cited_passage_is_generation(fixture):
    result = _run(fixture)
    q04 = next(r for r in result.results if r.case.id == "q04")
    case = next(f for f in q04.failures if "00041988" in f.detail)
    assert case.category == "generation"
    assert "cited passage" in case.evidence


def test_q07_twelve_months_is_an_applicability_error(fixture):
    """US1 scenario 2: the BX-12 warranty given for the BX-20."""
    stub = StubApi(fixture)
    key = ("u12", "What's the warranty period on a Belton BX-20?")
    q10 = stub.responses[("u12", next(c.question for c in GOLDEN if c.id == "q10"))]
    pid = next(iter(q10["citations"]))
    stub.responses[key] = {**deepcopy(stub.responses[key]), "status": "answer",
                           "abstain_reason": None, "notices": [],
                           "citations": {pid: q10["citations"][pid]},
                           "sentences": [{"kind": "statement", "step_number": None,
                                          "segments": [{"kind": "text", "text":
                                                        "The BX-20 warranty is 12 months."}],
                                          "citations": [pid]}]}
    result = _run(fixture, stub, [c for c in GOLDEN if c.id == "q07"])
    fails = result.results[0].failures
    assert {(f.check, f.category) for f in fails} >= {("outcome", "applicability"),
                                                     ("forbidden", "applicability")}


def test_corrupted_value_is_a_release_blocking_citation_failure(fixture):
    """US3 independent test: 38 N-m changed to 39 N-m in q04."""
    stub = StubApi(fixture)
    key = ("u04", next(c.question for c in GOLDEN if c.id == "q04"))
    for s in stub.responses[key]["sentences"]:
        for seg in s["segments"]:
            seg["text"] = seg["text"].replace("38 N-m", "39 N-m")
    result = _run(fixture, stub, [c for c in GOLDEN if c.id == "q04"])
    cit = [f for f in result.failures if f.check == "citation"]
    assert cit and all(f.blocking and f.category == "citation" for f in cit)
    assert any("39 n-m" in f.detail for f in cit)


def test_hidden_citation_is_a_policy_failure(fixture):
    stub = StubApi(fixture)
    c = fixture["cases"][5]  # q06, u03
    resp = stub.responses[(c["user_id"], c["question"])]
    hidden = c["hidden_passage"]
    first = resp["sentences"][0]["citations"][0]
    resp["citations"][hidden] = {**resp["citations"].pop(first), "passage_id": hidden}
    for s in resp["sentences"]:
        s["citations"] = [hidden if x == first else x for x in s["citations"]]
    if resp.get("restricted"):
        resp["restricted"]["citations"] = [hidden if x == first else x
                                           for x in resp["restricted"]["citations"]]
    for n in resp["notices"]:
        n["citations"] = [hidden if x == first else x for x in n["citations"]]
    if resp.get("work_order_suggestion"):
        w = resp["work_order_suggestion"]
        w["citations"] = [hidden if x == first else x for x in w["citations"]]
    result = _run(fixture, stub, [x for x in GOLDEN if x.id == "q06"])
    hid = [f for f in result.failures if f.check == "citation" and f.category == "policy"]
    assert hid and hid[0].blocking


def test_marker_in_uncertified_answer_blocks_the_release(fixture):
    stub = StubApi(fixture)
    c = fixture["cases"][5]  # q06 for u03, who can't satisfy HV-PROC-07
    resp = stub.responses[(c["user_id"], c["question"])]
    resp["sentences"][0]["segments"][0]["text"] += " Then set zz-mark-1."
    result = _run(fixture, stub, [x for x in GOLDEN if x.id == "q06"])
    dis = [f for f in result.failures if f.check == "disclosure"]
    assert dis and dis[0].blocking and dis[0].category == "policy"
    assert "zz-mark" not in dis[0].detail.casefold()  # markers are never printed


def test_marker_in_certified_answer_is_not_a_disclosure(fixture):
    stub = StubApi(fixture)
    c = fixture["cases"][4]  # q05 for u02, who holds cert-hv
    resp = stub.responses[(c["user_id"], c["question"])]
    resp["sentences"][0]["segments"][0]["text"] += " Then set ZZ-MARK-1."
    result = _run(fixture, stub, [x for x in GOLDEN if x.id == "q05"])
    assert not [f for f in result.failures if f.check == "disclosure"]


def test_api_unavailable_stops_without_a_score(fixture):
    with pytest.raises(InfrastructureError):
        _run(fixture, StubApi(fixture, status=503))


def test_dataset_mismatch_stops_without_a_score(fixture):
    stub = StubApi(fixture)
    stub.dataset_version = "ds_0099"
    with pytest.raises(InfrastructureError):
        _run(fixture, stub)


def test_question_identifiers_may_be_repeated_but_values_must_be_grounded(fixture):
    from copilot_contracts import AnswerResponse
    from copilot_eval.citations import check_values

    c = fixture["cases"][3]  # q04
    raw = deepcopy(c["response"])
    raw["sentences"][0]["segments"][0]["text"] = "Pit PP-1 needs 45 N-m and 41 N-m."
    resp = AnswerResponse.model_validate(raw)
    fails = check_values(resp, c["sources"], "Is pit PP-1 at 41 N-m?")
    detail = " ".join(f.detail for f in fails)
    assert "pp-1" not in detail      # typed by the technician: an identifier, not a claim
    assert "41 n-m" in detail        # a value is never exempt, even when the question has it
    assert "45 n-m" not in detail    # in the cited IOM passage


def test_a_failure_has_exactly_one_known_category():
    with pytest.raises(ValueError):
        Failure("q01", "fact", "model", False, "x")


def test_runs_are_repeatable(fixture):
    """SC-004: same responses, same verdicts."""
    a = _run(fixture)
    b = _run(fixture)
    assert [(f.case_id, f.check, f.category, f.detail) for f in a.failures] == \
           [(f.case_id, f.check, f.category, f.detail) for f in b.failures]


def test_values_from_metadata_compounds_and_labels():
    from copilot_contracts import AnswerResponse
    from copilot_eval import citations

    rec = next(c for c in load_fixture()["cases"] if c["id"] == "q08")
    resp = AnswerResponse.model_validate(rec["response"])
    first = resp.sentences[0]
    pid = first.citations[0]
    body = {"passage_id": pid, "title": "Case", "text_original": "E-14 trip overnight.",
            "issue_date": "2026-03-12"}
    text = first.segments[0].model_copy(
        update={"text": "On 2026-03-12 the repeated-E-14 trips began. [P4]"})
    resp = resp.model_copy(update={
        "sentences": [first.model_copy(update={"segments": [text]})], "conflicts": [],
        "work_order_suggestion": None})
    stamped = {"passage_id": pid, "text_original": "E-14. Opened 2026-03-12T13:47:00.000+0000"}
    assert [f.rule for f in citations.check_values(resp, {pid: stamped})] == ["label"]
    assert [f.rule for f in citations.check_values(resp, {pid: body})] == ["label"]
    body["issue_date"] = None
    assert [f.rule for f in citations.check_values(resp, {pid: body})] == ["label", "value"]


def _one_sentence(text: str):
    from copilot_contracts import AnswerResponse

    rec = next(c for c in load_fixture()["cases"] if c["id"] == "q08")
    resp = AnswerResponse.model_validate(rec["response"])
    first = resp.sentences[0]
    seg = first.segments[0].model_copy(update={"text": text})
    resp = resp.model_copy(update={
        "sentences": [first.model_copy(update={"segments": [seg]})], "conflicts": [],
        "work_order_suggestion": None})
    return resp, first.citations[0]


def _value_failures(text: str, passage: str) -> list[str]:
    from copilot_eval import citations

    resp, pid = _one_sentence(text)
    body = {"passage_id": pid, "title": "MaintPro history NA", "text_original": passage}
    return [f.detail for f in citations.check_values(resp, {pid: body})]


def test_code_followed_by_and_later():
    passage = "on all pumps from serial HCP350-240001 (and on earlier pumps"
    assert _value_failures("It is in the HCP350-240001-and-later range.", passage) == []
    assert _value_failures("It is in the HCP350-240002-and-later range.", passage) != []


def test_dates_written_as_month_day_in_a_dated_record():
    record = ("2026-09-22 TAC-C-0142 preventive (completed): ctrl log 3x e-14 auto restart "
              "since july (7/28, 8/30, 9/17). Case opened 2026-07-02; unit tripped 07/01.")
    ok = "On 2026-07-28, 2026-08-30, 2026-09-17 and 2026-07-01 it logged E-14."
    assert _value_failures(ok, record) == []
    assert _value_failures("On 2026-07-29 it logged E-14.", record) != []
    assert _value_failures("On 2025-07-28 it logged E-14.", record) != []
    assert _value_failures("On 2026-07-28 it logged E-14.", "E-14 on 7/28.") != []
    assert _value_failures("On 2026-03-12 it logged E-14.", "E-14, 12 March 2026.") == []


def test_article_a_after_a_number_is_not_amperes():
    from copilot_eval.citations import values

    passage = "On controller firmware below 5.1 a failing TS-2 is reported as E-14."
    assert values("On firmware 5.1 a failing or drifting TS-2 trips E-14.")[0] == "5.1"
    assert _value_failures("On firmware 5.1 a failing or drifting TS-2 trips E-14.", passage) == []
    assert _value_failures("On firmware 4.7 a failing TS-2 trips E-14.", passage) != []
    assert values("Limit 16 a. Trip at 18 a, alarm at 17 a") == ["16 a", "18 a", "17 a"]
    assert values("Rated 16 a at 400 v and 12 a or less idle") == ["16 a", "400 v", "12 a"]
    amps = "Motor FLA 16 A at 400 V."
    assert _value_failures("The motor draws 16 A at 400 V.", amps) == []
    assert _value_failures("The motor draws 18 A at 400 V.", amps) != []
    assert _value_failures("The motor draws 16 A.", "Motor FLA 16 V.") != []


def test_word_joined_to_a_dotted_number():
    from copilot_eval.citations import values

    passage = "Affected: controller firmware below 5.1 (5.0.x)."
    assert values("Update the under-5.1 firmware and the below-5.1.0 builds.") == ["5.1", "5.1.0"]
    assert _value_failures("Update the under-5.1 firmware.", passage) == []
    assert _value_failures("Update the under-5.2 firmware.", passage) != []
    assert values("Fit an HCP-350 or VRS-110 casing to HCP350-241187.") == [
        "hcp-350", "vrs-110", "hcp350-241187"]
    assert _value_failures("Use the HCP-350 kit.", "Use the HCP-500 kit.") != []
    assert _value_failures("Use the HCP-350 kit.", "Use the HCP-350 kit.") == []


def test_tag_missing_from_the_sentences_citations_is_still_caught():
    record = "2026-09-22 TAC-C-0142 preventive: 3x e-14 auto restart since july."
    fails = _value_failures("A failing TS-2 is reported as E-14 on firmware 5.0.", record)
    assert fails and "ts-2" in fails[0]


def test_q05_accepts_the_peak_current_paraphrase_and_q06_does_not():
    from copilot_eval.facts import Unit, match

    def overcurrent(qid):
        case = next(c for c in GOLDEN if c.id == qid)
        return next(f for f in case.required if f.fact == "E-31 is a VFD overcurrent trip")

    paraphrase = [Unit("text", "sentence 1",
                       "E-31 means the VFD saw output current above its peak current limit.")]
    literal = [Unit("text", "sentence 1", "E-31 is a VFD overcurrent fault.")]
    assert match(overcurrent("q05"), paraphrase).hit
    assert match(overcurrent("q05"), literal).hit
    assert not match(overcurrent("q06"), paraphrase).hit
    assert match(overcurrent("q06"), literal).hit
    assert not match(overcurrent("q05"), [Unit("text", "sentence 1",
                                               "E-31 means the output current was high.")]).hit


@pytest.mark.parametrize("fresh", [False, True])
def test_fresh_sets_answer_fresh_only_for_own_instance(monkeypatch, fresh):
    from copilot_eval.__main__ import _server_env

    monkeypatch.setenv("ANSWER_FRESH", "1")
    env = _server_env(0.5, fresh)
    assert env.get("ANSWER_FRESH") == ("1" if fresh else None)
    assert env["ANSWER_BUDGET_USD"] == "0.5"


def test_fresh_refuses_an_external_api():
    from copilot_eval.__main__ import main

    assert main(["run", "--fresh", "--base-url", "http://127.0.0.1:8030", "--no-grid"]) == 2
