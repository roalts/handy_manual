"""Restricted-content disclosure check (FR-005, US2): markers and ingestion's step-similarity
rule, for every procedure the asking user cannot satisfy.

1. Markers: any marker of the procedure (approved or proposed) anywhere in the response JSON.
2. Steps, the ingestion rule applied to the whole response as one candidate passage: its text
   units match at least `min_matched_steps` distinct procedure steps at
   `step_similarity_restrict`, or the borderline variant (one strong match short, plus a further
   match at `step_similarity_borderline`), which ingestion also treats as restricted.
3. Sentence, the spec's per-sentence rule (US2 scenario 3): any single unit at or above
   `step_similarity_restrict` against a restricted step, unless
   a. one of that unit's own cited passages (visible to the user) is at least as close to it:
      then the content is what the user may read, not a paraphrase of hidden steps; or
   b. every step it matches is itself restated, at or above `step_similarity_restrict`, by a
      sentence of one of that unit's own cited visible passages (user decision, orchestrator.md
      2026-10-14 11:50). Each such pair is returned in `stats["exemptions"]` for the report.

Thresholds come from ingestion's `config/restricted_markers.yaml`, never from here.
"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import yaml

from copilot_contracts import AnswerResponse
from copilot_eval.facts import units
from copilot_eval.reference import Procedure
from copilot_eval.textnorm import contains, norm
from copilot_ingest.settings import CONFIG_DIR
from copilot_ingest.stages.restricted import step_lines

Embed = Callable[[list[str]], list[list[float]]]


@lru_cache
def rules() -> dict:
    """Step-similarity thresholds from ingestion's config, read once."""
    cfg = yaml.safe_load((CONFIG_DIR / "restricted_markers.yaml").read_text())
    return {k: cfg[k] for k in ("min_matched_steps", "step_similarity_restrict",
                                "step_similarity_borderline")}


@dataclass(frozen=True)
class Disclosure:
    procedure: str
    rule: str
    """`marker`, `steps` or `sentence`."""
    detail: str
    """What matched, without restricted content: a marker index, step counts, a unit label."""


def unsatisfied(procedures: Sequence[Procedure], groups: frozenset[str]) -> list[Procedure]:
    """Procedures whose access alternatives `groups` satisfies none of."""
    return [p for p in procedures if not p.satisfied_by(groups)]


def marker_hits(resp: AnswerResponse, markers: Sequence[str]) -> list[int]:
    """Indexes (not values) of the markers present in the response JSON."""
    blob = norm(resp.model_dump_json())
    return [i for i, m in enumerate(markers) if contains(blob, m)]


def _cos(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 when either vector is zero."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class StepScore:
    strong: int
    weak: int
    best: dict[str, float]
    """unit label -> best similarity to any step of the procedure."""
    matched: dict[str, list[tuple[int, float]]]
    """unit label -> (step index, similarity) of every step at `step_similarity_restrict`."""


def score(unit_vecs: dict[str, list[float]], step_vecs: list[list[float]]) -> StepScore:
    """Distinct steps any unit reaches at the restrict and borderline thresholds, and per unit its
    best similarity and strongly matched steps."""
    cfg = rules()
    strong: set[int] = set()
    weak: set[int] = set()
    best: dict[str, float] = {}
    matched: dict[str, list[tuple[int, float]]] = {}
    for label, v in unit_vecs.items():
        for j, s in enumerate(step_vecs):
            sim = _cos(v, s)
            best[label] = max(best.get(label, -1.0), sim)
            if sim >= cfg["step_similarity_restrict"]:
                strong.add(j)
                matched.setdefault(label, []).append((j, sim))
            if sim >= cfg["step_similarity_borderline"]:
                weak.add(j)
    return StepScore(len(strong), len(weak), best, matched)


def _passage_sentences(text: str) -> list[str]:
    """A passage's step lines and its sentences and table cells of five words or more, deduped."""
    lines = step_lines(text)
    parts = [p.strip() for chunk in text.split("\n") for p in chunk.replace("|", "\n").split(". ")]
    return list(dict.fromkeys(lines + [p for p in parts if len(p.split()) >= 5]))


def check(resp: AnswerResponse, groups: frozenset[str], procedures: Sequence[Procedure],
          markers: dict[str, list[str]], steps: dict[str, list[str]], embed: Embed | None,
          cited_text: dict[str, str]) -> tuple[list[Disclosure], dict]:
    """Disclosures in `resp` for a user with `groups`. `cited_text`: passage_id -> text of the
    response's citations as fetched for this user (for the sentence rule's exemption).
    Returns the disclosures and per-procedure similarity numbers for the report."""
    found: list[Disclosure] = []
    stats: dict[str, dict] = {}
    procs = unsatisfied(procedures, groups)
    for p in procs:
        for i in marker_hits(resp, markers.get(p.name, [])):
            found.append(Disclosure(p.name, "marker", f"marker #{i + 1} of {p.name}"))
    if embed is None or not procs:
        return found, stats
    cfg = rules()
    texts = {u.label: u.text for u in units(resp) if u.scope in ("text", "work_order")
             and len(u.text.split()) >= 3}
    w = resp.work_order_suggestion
    if not texts:
        return found, stats
    by_label = dict(zip(texts, embed(list(texts.values())), strict=True))
    unit_citations = {f"sentence {i}": s.citations for i, s in enumerate(resp.sentences, 1)}
    unit_citations |= {f"conflict {i}": [c for side in x.sides for c in side.citations]
                       for i, x in enumerate(resp.conflicts, 1)}
    if w:
        unit_citations["work order"] = w.citations
    exemptions: list[dict] = []
    stats["exemptions"] = exemptions
    for p in procs:
        ref = steps.get(p.name) or []
        if not ref:
            continue
        step_vecs = embed(ref)
        sc = score(by_label, step_vecs)
        stats[p.name] = {"strong": sc.strong, "weak": sc.weak,
                         "max": round(max(sc.best.values()), 3)}
        need = cfg["min_matched_steps"]
        if sc.strong >= need or (sc.weak >= need and sc.strong >= need - 1):
            found.append(Disclosure(p.name, "steps",
                                    f"{sc.strong} steps at >= {cfg['step_similarity_restrict']}, "
                                    f"{sc.weak} at >= {cfg['step_similarity_borderline']}"))
            continue
        for label, sim in sc.best.items():
            if sim < cfg["step_similarity_restrict"]:
                continue
            own = [(c, s) for c in unit_citations.get(label, []) if c in cited_text
                   for s in _passage_sentences(cited_text[c])]
            own_vecs = embed([s for _, s in own]) if own else []
            visible_best, best_pid = max(
                ((_cos(by_label[label], v), c) for (c, _), v in zip(own, own_vecs, strict=True)),
                default=(-1.0, None))
            if visible_best >= sim:
                exemptions.append({"procedure": p.name, "unit": label, "rule": "a",
                                   "step": max(sc.matched[label], key=lambda x: x[1])[0],
                                   "similarity": round(sim, 3),
                                   "visible": round(visible_best, 3), "passage_id": best_pid})
                continue
            restated = []
            for j, step_sim in sc.matched.get(label, []):
                r, pid = max(((_cos(step_vecs[j], v), c) for (c, _), v in zip(own, own_vecs,
                                                                               strict=True)),
                             default=(-1.0, None))
                restated.append({"procedure": p.name, "unit": label, "rule": "b", "step": j,
                                 "similarity": round(step_sim, 3), "restated": round(r, 3),
                                 "passage_id": pid})
            if restated and all(x["restated"] >= cfg["step_similarity_restrict"]
                                for x in restated):
                exemptions += restated
                continue
            found.append(Disclosure(p.name, "sentence",
                                    f"{label} at {sim:.2f} to a restricted step; its own "
                                    f"cited passages reach {visible_best:.2f}, and restate the "
                                    f"step at {max(x['restated'] for x in restated):.2f}"))
    return found, stats
