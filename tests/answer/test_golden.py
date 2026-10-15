"""Hosted run over eval/questions.json plus paired restricted questions.

Writes specs/002-answer-engine/golden-run.md. Run: uv run pytest -q -m hosted tests/answer
(model calls served from the cache where possible; `GOLDEN_FRESH=1` bypasses it to measure real
latency and cost).
"""
import json
import os
import time

import pytest

from copilot_answer.engine import Engine
from copilot_answer.identity import load_identity
from copilot_answer.llm import HostedLLM
from copilot_answer.restricted import marker_hits, unsatisfied
from copilot_answer.serving import PgServing
from copilot_answer.validate import norm
from copilot_contracts import AskRequest, PreviousTurn
from copilot_ingest.settings import PROJECT_ROOT

pytestmark = pytest.mark.hosted

# Expected outcome, required facts and forbidden facts per golden question (from the reference
# answers). A required fact given as a tuple is met by any one of its spellings. Every required
# fact must be present for the case to pass.
EXPECT = {
    "q01": ("answer", ["cavitation", "15%", "10 s", "NPSH", "0.30 bar", "PI-01", "8.3"],
            ["0.25 bar"]),
    "q02": ("answer", ["0.38", "0.50 mm"], []),
    "q03": ("answer", [("6,000 h", "6,000 running hours"), "12 months", "SynLube 46",
                       ("4,000 h", "4,000 running hours")], []),
    "q04": ("answer", ["38 N-m", "00041988", "HCP350-240001", "HCP350-241187", "crack",
                       ("June 2026", "2026-06")], []),
    "q05": ("answer", ["HV-PROC-02", "50 V DC", "TP1", "100 MOhm", "P9.01", "210 A",
                       ("notify the site", "inform the site", "tell the site"), "24 hours",
                       "Vastra L2", ("High case", "High priority")], []),
    "q06": ("restricted", ["HV-PROC-07"], ["this technician"]),
    "q07": ("abstain", [], ["12 months"]),
    "q08": ("answer", ["00041207", "00042388", "41-2207", "5.1", "exhaust duct"], []),
    "q09": ("answer", ["SB-2025-014", "EXV", "63-1180", "rev 3", "SOP-020", "KT-WI-14",
                       "low suction pressure", "leak test"], []),
    "q10": ("answer", ["77-0419", "0.5 mm"], []),
}
EXTRA = [
    ("p1", "u06", "How do I recover and recharge the refrigerant on an NK-600?", "restricted",
     ["SOP-020"], []),
    ("p2", "u05", "How do I recover and recharge the refrigerant on an NK-600?", "answer",
     [], []),
    ("p3", "u10", "TAC-C-0143 tripped on E-31. How do I reset it? I am HV certified.",
     "restricted", ["HV-PROC-07"], []),
    ("c1", "u04", "What is the casing bolt torque on the HCP-350 at Fresno?", "clarify", [], []),
    ("a1", "u01", "What is the seal kit for FRS-P-9999?", "abstain", [], []),
    ("n1", "u12", "What's the impeller-to-casing clearance spec on an HCP-200?", "abstain", [],
     ["0.38"]),
    ("m1", "u03", "How do I reset an E-31 fault on a VRS-110?", "restricted", ["HV-PROC-07"],
     []),
    # "Did you mean" and follow-ups (one turn of memory held by the client).
    ("t1", "u01", "What's the impeller-to-casing clearance spec on an HCP-20?", "clarify", [], []),
    ("f1", "u01", "Oh, I meant HCP-200", "answer", ["0.38", "0.50 mm"], [],
     PreviousTurn(answer_id="ans_t1",
                  question="What's the impeller-to-casing clearance spec on an HCP-20?")),
    ("f2", "u03", "how do I reset it?", "restricted", ["HV-PROC-07"], [],
     PreviousTurn(answer_id="ans_x", question="What does E-31 mean on TAC-C-0143?",
                  asset_id="TAC-C-0143")),
    ("f3", "u04", "and on FRS-P-0012?", "answer", ["45 N-m"], [],
     PreviousTurn(answer_id="ans_q04", question="What torque do I use on the casing bolts for "
                  "FRS-P-0031 after a seal change?", asset_id="FRS-P-0031")),
]


def _text(resp) -> str:
    parts = [seg.text for s in resp.sentences for seg in s.segments]
    parts += [side.statement for c in resp.conflicts for side in c.sides]
    parts += [n.text for n in resp.notices]
    if resp.work_order_suggestion:
        parts.append(resp.work_order_suggestion.summary)
    return "\n".join(parts)


def test_golden_run():
    fresh = os.environ.get("GOLDEN_FRESH") == "1"
    engine = Engine(PgServing(), HostedLLM(fresh=fresh))
    questions = json.loads((PROJECT_ROOT / "eval/questions.json").read_text())
    cases = [(q["id"], q["user_id"], q["question"], *EXPECT[q["id"]]) for q in questions]
    cases += EXTRA
    markers = engine.serving.restricted_markers()
    rows, disclosures, results, failures = [], [], {}, []
    for qid, user, question, expected, facts, forbidden, *prev in cases:
        identity = load_identity(user)
        start = time.monotonic()
        resp = engine.answer(identity, AskRequest(question=question,
                                                  previous=prev[0] if prev else None))
        seconds = time.monotonic() - start
        resp.check()
        text = _text(resp)
        hit = [_label(f) for f in facts if _has(f, text)]
        missed = [_label(f) for f in facts if not _has(f, text)]
        bad = [f for f in forbidden if norm(f) in norm(text)]
        # Disclosure check: markers of every procedure the user can't satisfy, anywhere in the
        # response JSON, and every citation visible to the user right now.
        uns = unsatisfied(engine.procedures, identity.groups)
        blob = resp.model_dump_json()
        leaks = [m for name in uns for m in marker_hits(blob, markers.get(name, ()))]
        visible = engine.serving.visible_passages(identity.groups, list(resp.citations))
        hidden = sorted(set(resp.citations) - visible)
        if leaks or hidden:
            disclosures.append((qid, user, leaks, hidden))
        cost = engine.last_meter.cost_usd
        extra = ""
        if resp.status == "restricted" and resp.restricted:
            missing = ", ".join(resp.restricted.missing_groups)
            extra = f"{resp.restricted.procedure}, missing {missing}"
        elif resp.status == "abstain":
            extra = resp.abstain_reason or ""
        if resp.status == "clarify" and resp.clarification and not extra:
            extra = " / ".join(o.question or o.asset_id or "" for o in resp.clarification.options)
        if resp.question_used:
            extra += f"; answering: {resp.question_used}"
        if prev and resp.asset:
            extra += f"; machine {resp.asset.asset_id}"
        if resp.work_order_suggestion and not resp.work_order_suggestion.asset_id:
            extra += "; work order without asset"
        rows.append((qid, user, expected, resp.status, extra, hit, missed, bad, seconds, cost,
                     len(resp.sentences), len(resp.conflicts)))
        results[qid] = json.loads(resp.model_dump_json())
        if resp.status != expected or missed or bad:
            failures.append(f"{qid}: got {resp.status}, missed {missed}, forbidden {bad}")
    _write(rows, disclosures, results, fresh)
    assert not disclosures
    assert not failures, "\n".join(failures)


def _has(fact, text: str) -> bool:
    spellings = fact if isinstance(fact, tuple) else (fact,)
    return any(norm(s) in norm(text) for s in spellings)


def _label(fact) -> str:
    return " or ".join(fact) if isinstance(fact, tuple) else fact


def _write(rows, disclosures, results, fresh) -> None:
    how = ("Model calls bypass the cache in this run, so both are real (question embeddings may "
           "be cached; they cost well under a hundredth of a cent)." if fresh else
           "Model calls were served from the cache where an identical call had been made before; "
           "those show near-zero latency and $0, so latency and cost are real only for the new "
           "calls (set GOLDEN_FRESH=1 to measure all).")
    lines = ["# Golden run: Answer Engine (002)", "",
             f"Run at {time.strftime('%Y-%m-%d %H:%M')} against the published dataset with "
             "`uv run pytest -q -m hosted tests/answer/test_golden.py`. Latency is wall-clock "
             "for the whole pipeline; cost is model spend for that question. " + how, "",
             "| Q | User | Expected | Actual | Detail | Key facts hit | Missed | Forbidden "
             "present | Sentences / conflicts | Latency | Cost |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    total = 0.0
    for (qid, user, exp, act, extra, hit, missed, bad, secs, cost, n, nc) in rows:
        total += cost
        ok = "" if exp == act else " ✗"
        lines.append(f"| {qid} | {user} | {exp} | {act}{ok} | {extra} | {', '.join(hit) or '-'}"
                     f" | {', '.join(missed) or '-'} | {', '.join(bad) or '-'} | {n} / {nc} | "
                     f"{secs:.1f} s | ${cost:.4f} |")
    lines += ["", f"Total model cost of this run: ${total:.4f}.", "",
              "## Restricted-content disclosure check", "",
              "For every response, the whole response JSON was scanned for the markers of every "
              "restricted procedure the asking user cannot satisfy, and every cited passage was "
              "re-checked with `serving.can_see` for that user.", "",
              f"Disclosures found: **{len(disclosures)}**."]
    for d in disclosures:
        lines.append(f"- {d}")
    lines += ["", "## Responses", ""]
    for qid, r in results.items():
        lines.append(f"<details><summary>{qid}: {r['status']}</summary>\n")
        for s in r["sentences"]:
            num = f"{s['step_number']}. " if s["step_number"] else ""
            txt = "".join(seg["text"] or f"[unverified, page {seg['page']}]"
                          for seg in s["segments"])
            lines.append(f"- {s['kind']}: {num}{txt} ({len(s['citations'])} citations)")
        for c in r["conflicts"]:
            lines.append(f"- conflict {c['topic']}: "
                         + " vs ".join(side["statement"] for side in c["sides"])
                         + f" (preferred {c['preferred']})")
        for n in r["notices"]:
            lines.append(f"- notice {n['kind']}: {n['text']}")
        if r["work_order_suggestion"]:
            lines.append(f"- work order: {json.dumps(r['work_order_suggestion'])}")
        lines.append("\n</details>\n")
    path = PROJECT_ROOT / "specs/002-answer-engine/golden-run.md"
    path.write_text("\n".join(lines) + "\n")
