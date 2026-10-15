"""Rule b of the per-sentence disclosure rule (user decision, orchestrator.md 2026-10-14 11:50):
a sentence close to a restricted step is exempt only when that step is itself restated, at or
above 0.75, by a sentence of one of the sentence's own cited passages that the user can see.
Offline: a fake embedding pins every similarity."""
import hashlib
import math
import random
from copy import deepcopy

from copilot_contracts import AnswerResponse
from copilot_eval import disclosure
from copilot_eval.cases import load
from copilot_eval.client import Api
from copilot_eval.reference import Procedure
from copilot_eval.runner import run
from copilot_ingest.settings import PROJECT_ROOT
from tests.eval.stub import FakeReference, StubApi, load_fixture, users

DIMS = 64
SOP20 = Procedure("SOP-020", "SOP-020 Chiller Leak Test", "doc_sop20",
                  (frozenset({"cert-refrigerant", "family-chillers"}),))
STEP = "Kilo kilo check the campaign bulletin before anything else on this unit."
ANSWER = "Lima lima the campaign bulletin says the valve fault looks like low charge."
RESTATE = "Mike mike the bulletin says a sticking valve gives the same alarm as low charge."
WEAK = "November november the bulletin covers the expansion valve campaign."
OTHER = "Oscar oscar another statement about the chiller history on site."


def _unit(*coords: tuple[int, float]) -> list[float]:
    v = [0.0] * DIMS
    for i, x in coords:
        v[i] = x
    return v


# cos(ANSWER, STEP) = 0.80; cos(RESTATE, STEP) = 0.80 but cos(RESTATE, ANSWER) = 0.64, so the
# existing exemption (rule a) does not apply; cos(WEAK, STEP) = 0.70.
VECTORS = {"kilo kilo": _unit((0, 1.0)),
           "lima lima": _unit((0, 0.8), (1, 0.6)),
           "mike mike": _unit((0, 0.8), (2, 0.6)),
           "november november": _unit((0, 0.7), (2, math.sqrt(1 - 0.49)))}


def embed(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        key = next((k for k in VECTORS if k in t.lower()), None)
        if key:
            out.append(VECTORS[key])
            continue
        rnd = random.Random(hashlib.sha256(t.encode()).digest())
        v = [0.0] * 3 + [rnd.gauss(0, 1) for _ in range(DIMS - 3)]
        n = math.sqrt(sum(x * x for x in v))
        out.append([x / n for x in v])
    return out


FIX = load_fixture()
Q10 = next(c for c in FIX["cases"] if c["id"] == "q10")  # u12 satisfies no procedure
PA, PB = list(Q10["response"]["citations"])[:2]


def _raw() -> dict:
    raw = deepcopy(Q10["response"])
    raw["sentences"] = [
        {"kind": "statement", "step_number": None,
         "segments": [{"kind": "text", "text": ANSWER}], "citations": [PA]},
        {"kind": "statement", "step_number": None,
         "segments": [{"kind": "text", "text": OTHER}], "citations": [PB]}]
    raw["conflicts"] = []
    raw["work_order_suggestion"] = None
    return raw


def _check(cited: dict[str, str]):
    return disclosure.check(AnswerResponse.model_validate(_raw()), frozenset(Q10["groups"]),
                            [SOP20], {}, {"SOP-020": [STEP]}, embed, cited)


def test_step_restated_by_the_sentences_own_visible_citation_is_exempt_and_listed():
    found, stats = _check({PA: f"Section 1. {RESTATE}"})
    assert found == []
    [x] = stats["exemptions"]
    assert x == {"procedure": "SOP-020", "unit": "sentence 1", "rule": "b", "step": 0,
                 "similarity": 0.8, "restated": 0.8, "passage_id": PA}


def test_restating_passage_cited_only_by_another_sentence_does_not_exempt():
    found, stats = _check({PA: "Section 1. Unrelated text about the chiller room.",
                           PB: f"Section 2. {RESTATE}"})
    assert [(d.procedure, d.rule) for d in found] == [("SOP-020", "sentence")]
    assert stats["exemptions"] == []


def test_restatement_under_threshold_does_not_exempt():
    found, stats = _check({PA: f"Section 1. {WEAK}"})
    assert [(d.procedure, d.rule) for d in found] == [("SOP-020", "sentence")]
    assert "restate the step at 0.70" in found[0].detail
    assert stats["exemptions"] == []


def _gate(hidden: bool):
    """End to end through the stub API: the restating passage is visible, or 403 for u12."""
    case = next(c for c in load(PROJECT_ROOT / "eval") if c.id == "q10")
    stub = StubApi(FIX)
    stub.responses[("u12", case.question)] = _raw()
    body = {**stub.sources["u12"][PA], "text_original": f"Section 1. {RESTATE}", "text_en": None}
    if hidden:
        del stub.sources["u12"][PA]
        stub.hidden.setdefault("u12", set()).add(PA)
    else:
        stub.sources["u12"][PA] = body
    ref = FakeReference(FIX, procedures=[SOP20], markers={}, steps={"SOP-020": [STEP]})
    ref._visible[frozenset(Q10["groups"])][PA] = body["text_original"]
    result = run([case], Api("http://stub", transport=stub.transport()), ref, users(FIX),
                 embed=embed, progress=lambda *_: None)
    return result.results[0]


def test_exemption_through_the_api_when_the_passage_is_visible():
    r = _gate(hidden=False)
    assert not [f for f in r.failures if f.check == "disclosure"]
    assert [x["rule"] for x in r.disclosure_stats["exemptions"]] == ["b"]


def test_no_exemption_when_the_restating_passage_is_not_visible_to_the_user():
    r = _gate(hidden=True)
    assert [f.category for f in r.failures if f.check == "disclosure"] == ["policy"]
    assert any(f.check == "citation" and f.category == "policy" for f in r.failures)
    assert r.disclosure_stats["exemptions"] == []
