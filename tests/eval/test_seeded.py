"""Seeded trials (SC-003): a corrupted citation or a leaked marker is caught in 100% of trials.

Trials are generated from the 10 recorded golden responses: every value of every sentence
corrupted in turn, every citation swapped for a hidden passage, every marker injected into every
kind of text the user reads. The live-data trials use the real `serving.restricted_markers` and
procedure steps with cached embeddings, and skip without the database or the cache.
"""
import re
from copy import deepcopy

import pytest

from copilot_contracts import AnswerResponse
from copilot_eval import citations, disclosure
from copilot_eval.reference import Procedure
from copilot_eval.textnorm import decimal_comma, norm
from tests.eval.stub import load_fixture

FIX = load_fixture()
HV7 = Procedure("HV-PROC-07", "HV-PROC-07", "doc_hv7",
                (frozenset({"cert-hv", "family-compressors"}),))
SOP20 = Procedure("SOP-020", "SOP-020", "doc_sop20",
                  (frozenset({"cert-refrigerant", "family-chillers"}),))
FAKE_MARKERS = {"HV-PROC-07": ["QX7.31", "TPX9", "77 V DC"], "SOP-020": ["991 MICRONS"]}


def _perturb(value: str) -> str:
    """Change the last digit: 38 n-m -> 39 n-m, 00041988 -> 00041989."""
    i = max(i for i, ch in enumerate(value) if ch.isdigit())
    return value[:i] + str((int(value[i]) + 1) % 10) + value[i + 1:]


def _value_trials():
    for case in FIX["cases"]:
        resp = case["response"]
        for si, s in enumerate(resp["sentences"]):
            text = "".join(g["text"] for g in s["segments"] if g["kind"] == "text")
            hay = norm("\n".join(f"{case['sources'][c]['title']}\n"
                                 f"{case['sources'][c]['text_original']}\n"
                                 f"{case['sources'][c]['text_en'] or ''}"
                                 for c in s["citations"]))
            hay += "\n" + decimal_comma(hay)
            for v in citations.values(text):
                bad = _perturb(v)
                if citations._present(bad, hay):
                    continue  # the corrupted value is also in the source: not a corruption
                yield case, si, v, bad


def _corrupt(resp: dict, si: int, value: str, bad: str) -> dict:
    out = deepcopy(resp)
    for g in out["sentences"][si]["segments"]:
        if g["kind"] == "text":
            # Replace in normalized form, so "6,000" and "6000" are both found.
            g["text"] = re.sub(re.escape(value), bad, norm(g["text"]))
    return out


def test_every_corrupted_value_is_caught():
    trials = caught = 0
    for case, si, value, bad in _value_trials():
        resp = AnswerResponse.model_validate(_corrupt(case["response"], si, value, bad))
        fails = citations.check_values(resp, case["sources"])
        trials += 1
        caught += any(f.where == f"sentence {si + 1}" and bad in f.detail for f in fails)
    assert trials > 100
    assert caught == trials


def test_untouched_responses_have_no_value_failures():
    for case in FIX["cases"]:
        resp = AnswerResponse.model_validate(case["response"])
        assert citations.check_values(resp, case["sources"]) == [], case["id"]


def test_every_citation_swapped_for_a_hidden_passage_is_caught():
    trials = caught = 0
    for case in FIX["cases"]:
        for pid in case["response"]["citations"]:
            hidden = case["hidden_passage"]

            def fetch(p, pid=pid, hidden=hidden, case=case):
                if p == pid:
                    return 403, {"error": "not_visible"}
                return 200, case["sources"][p]
            fails, _ = citations.check(AnswerResponse.model_validate(case["response"]), fetch)
            trials += 1
            caught += any(f.rule == "hidden" and f.where == pid for f in fails)
    assert trials > 50 and caught == trials


def _inject(resp: dict, where: str, text: str) -> dict:
    out = deepcopy(resp)
    if where == "sentence" and out["sentences"]:
        out["sentences"][-1]["segments"][0]["text"] += f" {text}"
    elif where == "conflict" and out["conflicts"]:
        out["conflicts"][0]["sides"][0]["statement"] += f" {text}"
    elif where == "notice" and out["notices"]:
        out["notices"][0]["text"] += f" {text}"
    elif where == "work_order" and out["work_order_suggestion"]:
        out["work_order_suggestion"]["summary"] += f" {text}"
    else:
        return {}
    return out


def test_every_injected_marker_is_caught_for_uncertified_users():
    trials = caught = 0
    for case in FIX["cases"]:
        groups = frozenset(case["groups"])
        for proc in disclosure.unsatisfied([HV7, SOP20], groups):
            for marker in FAKE_MARKERS[proc.name]:
                for where in ("sentence", "conflict", "notice", "work_order"):
                    for form in (marker, marker.lower(), marker.replace(" ", "  ")):
                        raw = _inject(case["response"], where, f"Then use {form}.")
                        if not raw:
                            continue
                        found, _ = disclosure.check(AnswerResponse.model_validate(raw), groups,
                                                    [HV7, SOP20], FAKE_MARKERS, {}, None, {})
                        trials += 1
                        caught += any(d.procedure == proc.name and d.rule == "marker"
                                      for d in found)
    assert trials > 100 and caught == trials


def test_markers_are_not_flagged_for_certified_users():
    case = FIX["cases"][4]  # q05, u02 holds cert-hv and family-compressors
    raw = _inject(case["response"], "sentence", "Then use QX7.31.")
    found, _ = disclosure.check(AnswerResponse.model_validate(raw), frozenset(case["groups"]),
                                [HV7], FAKE_MARKERS, {}, None, {})
    assert found == []


@pytest.fixture(scope="module")
def live():
    import psycopg

    from copilot_eval.reference import PgReference
    from copilot_ingest.providers.base import ProviderUnavailable
    from copilot_ingest.providers.cache import CachedProvider
    from copilot_ingest.settings import get_settings

    s = get_settings()
    try:
        ref = PgReference(s.database_url, s.users_path)
        ref.dataset_version()
    except psycopg.OperationalError as e:
        pytest.skip(f"database not available: {e}")
    offline = CachedProvider(None, offline=True)

    def embed(texts):
        try:
            return offline.embed(s.embedding_model, texts, s.embedding_dims)
        except ProviderUnavailable as e:
            pytest.skip(f"embeddings not cached: {e}")
    return ref, embed


@pytest.mark.integration
def test_every_real_marker_is_caught(live):
    ref, _ = live
    markers = ref.markers()
    assert markers.get("HV-PROC-07")
    case = FIX["cases"][5]  # q06, u03
    groups = frozenset(case["groups"])
    trials = caught = 0
    for proc in disclosure.unsatisfied(ref.procedures(), groups):
        for m in markers.get(proc.name, []):
            for where in ("sentence", "work_order"):
                raw = _inject(case["response"], where, f"Check {m.lower()} next.")
                found, _ = disclosure.check(AnswerResponse.model_validate(raw), groups,
                                            ref.procedures(), markers, {}, None, {})
                trials += 1
                caught += any(d.rule == "marker" and d.procedure == proc.name for d in found)
    assert trials >= 12 and caught == trials


@pytest.mark.integration
def test_restricted_steps_injected_into_an_uncertified_answer_are_caught(live):
    """Step leaks of each procedure, through the similarity rules with real (cached) vectors:
    three steps trip the ingestion rule, one step alone the sentence rule."""
    ref, embed = live
    steps = ref.procedure_steps()
    case = FIX["cases"][9]  # q10, u12: satisfies none of the four procedures
    groups = frozenset(case["groups"])
    cited = {pid: b["text_original"] for pid, b in case["sources"].items()}
    for proc in ref.procedures():
        lines = [s for s in steps[proc.name] if len(s.split()) >= 8][:3]
        raw = deepcopy(case["response"])
        cit = raw["sentences"][0]["citations"]
        raw["sentences"] += [{"kind": "step", "step_number": i + 10,
                              "segments": [{"kind": "text", "text": t}], "citations": cit}
                             for i, t in enumerate(lines)]
        found, _ = disclosure.check(AnswerResponse.model_validate(raw), groups,
                                    ref.procedures(), ref.markers(), steps, embed, cited)
        assert any(d.procedure == proc.name and d.rule == "steps" for d in found), proc.name
        raw["sentences"] = raw["sentences"][:-2]
        found, _ = disclosure.check(AnswerResponse.model_validate(raw), groups,
                                    ref.procedures(), ref.markers(), steps, embed, cited)
        assert any(d.procedure == proc.name and d.rule == "sentence" for d in found), proc.name


@pytest.mark.integration
def test_recorded_answers_have_no_disclosures(live):
    """The negative side of the calibration: none of the 10 recorded answers trips a rule."""
    ref, embed = live
    for case in FIX["cases"]:
        cited = {pid: f"{b['text_original']}\n{b['text_en'] or ''}"
                 for pid, b in case["sources"].items()}
        found, _ = disclosure.check(AnswerResponse.model_validate(case["response"]),
                                    frozenset(case["groups"]), ref.procedures(), ref.markers(),
                                    ref.procedure_steps(), embed, cited)
        assert found == [], case["id"]
