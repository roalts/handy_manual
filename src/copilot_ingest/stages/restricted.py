"""Restricted-procedure content tagging. Tagging only ever adds required groups."""
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from copilot_ingest.models import Passage, ReviewItem
from copilot_ingest.review import Decisions
from copilot_ingest.settings import CONFIG_DIR

VERSION = "restricted-2"


@lru_cache
def _cfg() -> dict:
    """restricted_markers.yaml, loaded once."""
    return yaml.safe_load((CONFIG_DIR / "restricted_markers.yaml").read_text())


def _canon(marker: str) -> str:
    """Upper-case marker with single spaces, 'TP 1' written as 'TP1'."""
    return re.sub(r"\s+", " ", marker.strip()).upper().replace("TP ", "TP")


@dataclass
class Procedure:
    doc_id: str
    path: str
    name: str
    groups: list[str]
    steps: list[Passage]
    markers: list[str] = field(default_factory=list)
    proposed: list[str] = field(default_factory=list)


def _candidates(text: str) -> set[str]:
    """Canonical marker candidates (configured patterns, case-insensitive) found in the text."""
    out: set[str] = set()
    for pattern in _cfg()["candidate_patterns"].values():
        out |= {_canon(m.group(0)) for m in re.finditer(pattern, text, re.I)}
    return out


def _markers_in(text: str, markers: list[str]) -> set[str]:
    """The given markers that occur in the text."""
    found = _candidates(text)
    return {m for m in markers if m in found}


_STEP_LINE = re.compile(
    r"^\s*(?:(?:Step|Stap|Schritt|Steg|#)\s*:\s*)?\d{1,2}(?:\.\d{1,2}){0,2}[.)]?\s+(?=\S)(.{12,})$",
    re.M | re.I)


_CELL_LABEL = re.compile(r"^\|?\s*[\w ]{1,20}:\s*")
MIN_STEP_WORDS = 5  # shorter numbered lines are section headings, not steps


def step_lines(text: str) -> list[str]:
    """Numbered step lines of a passage, number and table-cell label stripped."""
    out: list[str] = []
    for m in _STEP_LINE.finditer(text):
        s = _CELL_LABEL.sub("", m.group(1).strip())
        if s.startswith("|"):  # table row such as revision history, not a step
            continue
        if len(s.split()) >= MIN_STEP_WORDS and s not in out:
            out.append(s)
    return out


def is_step_passage(p: Passage) -> bool:
    """Whether the passage holds procedure steps: a parent or child, a step block, or a
    numbered list."""
    return p.role in ("parent", "child") or "procedure_step" in p.block_types or (
        "list_item" in p.block_types and re.search(r"(?m)^\d{1,2}\.\s", p.text_original)
        is not None)


def build_procedures(docs: dict[str, dict], passages: list[Passage],
                     cert_groups: list[str]) -> list[Procedure]:
    """docs: doc_id -> {"path", "name", "controlled", "groups"} (groups of the strictest origin)."""
    procs = []
    for doc_id, d in docs.items():
        if not d["controlled"] or not set(d["groups"]) & set(cert_groups):
            continue
        steps = [p for p in passages if p.doc_id == doc_id and is_step_passage(p)]
        if steps:
            procs.append(Procedure(doc_id=doc_id, path=d["path"], name=d["name"],
                                   groups=sorted(d["groups"]), steps=steps))
    return procs


def _marker_item(proc: Procedure, proposed: list[str], approved: list[str]) -> ReviewItem:
    """Marker approval item for a procedure. Called with empty lists to look up a decision."""
    return ReviewItem(
        kind="marker_approval", path=proc.path, field=proc.name,
        candidates={"proposed": proposed, "approved": approved},
        reason=f"{len(proposed)} proposed markers for {proc.name} are applied as "
               "restricted until approved or rejected",
        stage="restricted")


def propose_markers(procs: list[Procedure], passages: list[Passage],
                    decisions: Decisions | None = None) -> list[ReviewItem]:
    """Approved markers come from config and from reviewer resolutions; rejected ones are never
    applied; everything else found is proposed and applied until decided."""
    cfg = _cfg()
    restricted_docs = {p.doc_id for p in procs}
    unrestricted_df: dict[str, set[str]] = {}
    for p in passages:
        if p.doc_id in restricted_docs:
            continue
        for c in _candidates(p.text_original):
            unrestricted_df.setdefault(c, set()).add(p.doc_id)
    items = []
    for proc in procs:
        approved = {_canon(m) for m in (cfg.get("approved") or {}).get(proc.name, [])}
        rejected = {_canon(m) for m in (cfg.get("rejected") or {}).get(proc.name, [])}
        decided = decisions.get(_marker_item(proc, [], [])) if decisions else None
        if decided:
            approved |= {_canon(m) for m in decided.get("approved", [])}
            rejected |= {_canon(m) for m in decided.get("rejected", [])}
        approved -= rejected
        found: set[str] = set()
        for s in proc.steps:
            found |= _candidates(s.text_original)
        proposed = sorted(c for c in found - approved - rejected
                          if len(unrestricted_df.get(c, ())) <= cfg["max_unrestricted_documents"])
        proc.markers = sorted(approved | set(proposed))
        proc.proposed = proposed
        if proposed:
            items.append(_marker_item(proc, proposed, sorted(approved)))
    return items


@dataclass
class TagResult:
    tagged: dict[str, list[str]] = field(default_factory=dict)  # passage_id -> procedure names
    review: list[ReviewItem] = field(default_factory=list)
    released: list[str] = field(default_factory=list)  # borderline passages a reviewer released
    similarity_checked: bool = False


def _matched_steps(cand: dict[str, list[float]], proc_steps: list[list[float]],
                   threshold: float) -> tuple[int, dict[str, set[int]]]:
    """Distinct procedure steps matched at or above threshold, and for each matching candidate
    step the procedure steps (by index) it matched."""
    matched: dict[str, set[int]] = {}
    for j, r in enumerate(proc_steps):
        for text, c in cand.items():
            if _cos(c, r) >= threshold:
                matched.setdefault(text, set()).add(j)
    return len(set().union(*matched.values())) if matched else 0, matched


def tag(procs: list[Procedure], passages: list[Passage],
        embed: Callable[[list[str]], list[list[float]]] | None = None,
        paths: dict[str, str] | None = None,
        decisions: Decisions | None = None) -> TagResult:
    """Tag passages that reproduce restricted procedure content.

    Similarity is checked step against step: whole-passage similarity measures topic, so any
    warning or reference list about the same machine would match. A passage counts only if its
    numbered steps match several distinct steps of the procedure.
    embed: text -> vector function (cached); None skips the similarity check.
    paths: doc_id -> source path, for review items.
    """
    cfg = _cfg()
    result = TagResult()
    restricted_docs = {p.doc_id for p in procs}
    candidates = {p.passage_id: step_lines(p.text_original) for p in passages
                  if p.doc_id not in restricted_docs}
    candidates = {k: v for k, v in candidates.items() if len(v) >= cfg["min_candidate_steps"]}
    # Parent and child passages repeat the same steps; count each step once.
    proc_steps = {proc.name: list(dict.fromkeys(s for p in proc.steps
                                                for s in step_lines(p.text_original)))
                  for proc in procs}
    vec: dict[str, list[float]] = {}
    if embed and candidates:
        texts = sorted({s for v in candidates.values() for s in v}
                       | {s for v in proc_steps.values() for s in v})
        vec = dict(zip(texts, embed(texts), strict=True)) if texts else {}
    evidence: dict[str, list[tuple[Procedure, dict[str, set]]]] = {}
    for p in passages:
        if p.doc_id in restricted_docs:
            continue
        for proc in procs:
            hits = _markers_in(p.text_original, proc.markers)
            reason, found = None, {}
            if len(hits) >= cfg["min_markers"]:
                reason, found = f"markers {sorted(hits)}", {m: {m} for m in hits}
            elif vec and p.passage_id in candidates and proc_steps[proc.name]:
                cand = {s: vec[s] for s in candidates[p.passage_id]}
                ref = [vec[s] for s in proc_steps[proc.name]]
                strong, strong_hits = _matched_steps(cand, ref, cfg["step_similarity_restrict"])
                weak, weak_hits = _matched_steps(cand, ref, cfg["step_similarity_borderline"])
                if strong >= cfg["min_matched_steps"]:
                    reason = f"{strong} steps match at >= {cfg['step_similarity_restrict']}"
                    found = strong_hits
                elif (weak >= cfg["min_matched_steps"]
                      and strong >= cfg["min_matched_steps"] - 1):
                    found = weak_hits
                    item = ReviewItem(
                        kind="restricted_borderline", path=(paths or {}).get(p.doc_id),
                        anchor={"passage_id": p.passage_id, **p.anchor.model_dump(
                            exclude_none=True, exclude_defaults=True)},
                        field=proc.name,
                        candidates={"matched_steps_borderline": weak,
                                    "matched_steps_strong": strong},
                        reason="treated as restricted until reviewed", stage="restricted")
                    decided = decisions.get(item) if decisions else None
                    if decided == "release":
                        result.released.append(p.passage_id)
                    elif decided == "restrict":
                        reason = f"reviewer confirmed ({weak} steps match)"
                    else:
                        reason = (f"borderline: {weak} steps match at >= "
                                  f"{cfg['step_similarity_borderline']}")
                        result.review.append(item)
            if reason:
                _apply(p, proc, f"{proc.name}: {reason}", result)
                evidence.setdefault(p.passage_id, []).append((proc, found))
    _spread_to_family(passages, evidence, result)
    result.similarity_checked = embed is not None
    return result


def _apply(p: Passage, proc: Procedure, why: str, result: TagResult) -> None:
    """Add the procedure's tag and groups to the passage and record why."""
    p.restricted_tags = sorted(set(p.restricted_tags) | {proc.name})
    p.restricted_groups = sorted(set(p.restricted_groups) | set(proc.groups))
    result.tagged.setdefault(p.passage_id, []).append(why)


def _held(p: Passage, found: dict[str, set]) -> set:
    """Procedure steps (or markers) of the parent's match that this child holds."""
    units = set(step_lines(p.text_original)) | _candidates(p.text_original)
    return set().union(*(keys for unit, keys in found.items() if unit in units))


def _children_to_restrict(kids: list[Passage], found: dict[str, set]) -> list[Passage]:
    """Every child holding any matched step or marker; all children if none can be pinned down.
    Restricting only enough children to break the match would leave most of the sequence
    readable (each window of a split procedure holds one or two of its steps)."""
    holding = [c for c in kids if _held(c, found)]
    return holding or kids


def _spread_to_family(passages: list[Passage],
                      evidence: dict[str, list[tuple[Procedure, dict[str, set]]]],
                      result: TagResult) -> None:
    """A parent contains its children's text, so a tagged child tags its parent, and a tagged
    parent tags the children holding its matched steps or markers."""
    by_id = {p.passage_id: p for p in passages}
    children: dict[str, list[Passage]] = {}
    for p in passages:
        if p.parent_passage_id:
            children.setdefault(p.parent_passage_id, []).append(p)
    for pid, matches in evidence.items():
        src = by_id[pid]
        for proc, found in matches:
            family = _children_to_restrict(children.get(pid, []), found)
            if src.parent_passage_id and src.parent_passage_id in by_id:
                family = [*family, by_id[src.parent_passage_id]]
            for p in family:
                _apply(p, proc, f"{proc.name}: same family as {pid}", result)


def _cos(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0.0 if either vector is zero."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
