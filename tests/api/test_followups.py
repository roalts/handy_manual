"""Follow-ups (`AskRequest.previous`) and `AnswerResponse.question_used` pass through the API
unchanged, and a previous turn carries no access (answer.md, "Follow-ups"; http-api.md, Asking)."""
import pytest

from copilot_contracts import (
    AnswerResponse,
    Citation,
    Clarification,
    ClarifyOption,
    Segment,
    Sentence,
)
from tests.api.fakes import FakeEngine, example

FOLLOW_UP = {"question": "Oh, I meant HCP-200", "previous": {
    "answer_id": "ans_prev",
    "question": "What's the impeller-to-casing clearance spec on an HCP-20?",
    "asset_id": None}}
HV_PROC_07 = "p_8d53a48ac5150e1416041387"
"""A passage of HV-PROC-07 (high-voltage drive fault reset procedure, restricted): visible to u02
(compressor technician with high-voltage certification), not to u03 (without it)."""


def test_previous_reaches_engine_unchanged(harness):
    r = harness.client("u01").post("/api/ask", json=FOLLOW_UP)
    assert r.status_code == 200
    identity, req = harness.engine.calls[-1]
    assert req.model_dump(mode="json", exclude_none=True) == {
        "question": FOLLOW_UP["question"],
        "previous": {k: v for k, v in FOLLOW_UP["previous"].items() if v is not None}}
    assert identity.user_id == "u01"
    [event] = harness.events("answer")
    assert event.details["previous_answer_id"] == "ans_prev"


def test_previous_with_asset_reaches_engine(harness):
    body = {"question": "and the torque?", "previous": {
        "answer_id": "ans_1", "question": "Seal kit for FRS-P-0031?", "asset_id": "FRS-P-0031"}}
    harness.client("u04").post("/api/ask", json=body)
    assert harness.engine.calls[-1][1].previous.asset_id == "FRS-P-0031"


def test_question_used_round_trips(make_harness):
    resp = example("answer").model_copy(update={
        "question_used": "What's the impeller-to-casing clearance spec on an HCP-200?"})
    h = make_harness(engine=FakeEngine(resp))
    r = h.client("u01").post("/api/ask", json=FOLLOW_UP)
    assert r.status_code == 200
    assert r.json()["question_used"] == resp.question_used
    assert r.json() == resp.model_dump(mode="json")
    assert h.events("answer")[0].details["question_used"] == resp.question_used


def test_did_you_mean_clarify_round_trips(make_harness):
    base = example("abstain")
    resp = AnswerResponse(
        answer_id="ans_dym", dataset_version=base.dataset_version, status="clarify",
        clarification=Clarification(question="Did you mean HCP-200?", options=[ClarifyOption(
            label="HCP-200",
            question="What's the impeller-to-casing clearance spec on an HCP-200?")]))
    resp.check()
    h = make_harness(engine=FakeEngine(resp))
    r = h.client("u01").post("/api/ask", json={
        "question": "What's the impeller-to-casing clearance spec on an HCP-20?"})
    assert r.json() == resp.model_dump(mode="json")
    option = r.json()["clarification"]["options"][0]
    assert option["asset_id"] is None and option["question"].endswith("HCP-200?")


def test_responses_without_new_fields_still_valid(harness):
    r = harness.client("u04").post("/api/ask", json={"question": "q?"})
    assert r.json()["question_used"] is None


@pytest.mark.parametrize("previous", [
    {"answer_id": "a", "question": ""},
    {"answer_id": "a", "question": "x" * 2001},
    {"question": "no answer id"},
    {"answer_id": "a", "question": "q", "groups": ["cert-hv"]},
    {"answer_id": "a", "question": "q", "user_id": "u02"},
    "ans_1",
    ["ans_1"],
])
def test_invalid_previous_is_422(harness, previous):
    r = harness.client("u03").post("/api/ask", json={"question": "and then?",
                                                     "previous": previous})
    assert (r.status_code, r.json()["error"]) == (422, "invalid_request")
    assert harness.engine.calls == []


def test_previous_of_another_user_changes_no_identity(harness):
    """u03 sends u02's answer as `previous`: the engine still gets u03 and u03's groups."""
    u02 = harness.client("u02").post("/api/ask", json={"question": "E-31 reset TAC-C-0143?"})
    body = {"question": "and the next step?", "previous": {
        "answer_id": u02.json()["answer_id"], "question": "E-31 reset TAC-C-0143?",
        "asset_id": "TAC-C-0143"}}
    harness.client("u03").post("/api/ask", json=body)
    identity, req = harness.engine.calls[-1]
    assert identity.user_id == "u03"
    assert identity.groups == {"region-na", "family-compressors"}
    assert req.previous.answer_id == u02.json()["answer_id"]


@pytest.mark.integration
def test_previous_of_another_user_grants_no_passage(make_harness, db):
    """Against the real serving schema: even if an engine echoed the previous answer's citation,
    u03 would get neither it in an answer nor through the source endpoint."""
    import json

    from copilot_api.sources import SourceStore
    from copilot_ingest.settings import PROJECT_ROOT, get_settings

    s = get_settings()
    catalog = sorted(json.loads((PROJECT_ROOT / "users.json").read_text())["groups"])
    store = SourceStore(s.database_url, s.corpus_dir, s.data_dir, known_groups=lambda: catalog)
    cite = Citation(passage_id=HV_PROC_07, doc_id="d", title="HV-PROC-07", doc_type="sop",
                    revision=None, issue_date=None, authority_tier=1, locator="1",
                    viewer_url=f"/sources/{HV_PROC_07}")
    resp = AnswerResponse(
        answer_id="ans_u02", dataset_version="ds", status="answer",
        sentences=[Sentence(kind="statement", segments=[Segment(kind="text", text="step")],
                            citations=[HV_PROC_07])], citations={HV_PROC_07: cite})
    h = make_harness(engine=FakeEngine(resp), sources=store)

    assert h.client("u02").post("/api/ask", json={"question": "E-31 reset?"}).status_code == 200
    u03 = h.client("u03")
    r = u03.post("/api/ask", json={"question": "and the next step?", "previous": {
        "answer_id": "ans_u02", "question": "E-31 reset?", "asset_id": "TAC-C-0143"}})
    assert (r.status_code, r.json()) == (500, {"error": "internal_error"})
    assert HV_PROC_07 not in r.text
    assert u03.get(f"/api/sources/{HV_PROC_07}").status_code == 403
    assert h.client("u02").get(f"/api/sources/{HV_PROC_07}").status_code == 200
