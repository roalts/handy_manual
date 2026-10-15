"""Eval cases: the golden questions with their key facts, and the restricted pairs."""
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from copilot_eval.facts import Fact

STATUSES = {"answer", "restricted", "abstain", "clarify"}


@dataclass(frozen=True)
class Case:
    id: str
    kind: str
    """`golden` or `pair` (paired or adversarial question for a restricted procedure)."""
    user_id: str
    question: str
    outcomes: tuple[str, ...]
    required: tuple[Fact, ...] = ()
    forbidden: tuple[Fact, ...] = ()
    abstain_reason: str | None = None
    restricted_procedures: tuple[str, ...] = ()
    """Accepted `restricted.procedure` values when the outcome is restricted."""
    restricted_missing: tuple[str, ...] = ()
    procedure: str | None = None
    """For pairs: the restricted procedure this case probes."""
    certified: bool | None = None
    previous: dict | None = None
    reference: str | None = None
    source: str | None = None
    extra: dict = field(default_factory=dict)


def _outcomes(raw) -> tuple[str, ...]:
    """Accepted statuses, from one or a list; ValueError if empty or unknown."""
    out = tuple(raw if isinstance(raw, list) else [raw])
    if not out or set(out) - STATUSES:
        raise ValueError(f"bad outcome {raw!r}")
    return out


def _facts(raw: list | None) -> tuple[Fact, ...]:
    """Parsed key facts; none when the entry is missing."""
    facts = tuple(Fact.parse(f) for f in raw or [])
    return facts


def load(eval_dir: Path) -> list[Case]:
    """Golden cases, then restricted pairs; a pair taken from a golden question tags that case
    instead of adding one. ValueError on inconsistent files or duplicate IDs."""
    questions = json.loads((eval_dir / "questions.json").read_text())
    key_facts = yaml.safe_load((eval_dir / "key_facts.yaml").read_text())
    pairs = yaml.safe_load((eval_dir / "restricted_pairs.yaml").read_text())
    if set(key_facts) != {q["id"] for q in questions}:
        raise ValueError("key_facts.yaml must have exactly the questions in questions.json")
    golden: dict[str, Case] = {}
    for q in questions:
        k = key_facts[q["id"]]
        r = k.get("restricted") or {}
        forbidden = _facts(k.get("forbidden"))
        if any(f.category is None for f in forbidden):
            raise ValueError(f"{q['id']}: every forbidden fact needs a category")
        golden[q["id"]] = Case(
            id=q["id"], kind="golden", user_id=q["user_id"], question=q["question"],
            outcomes=_outcomes(k["outcome"]), required=_facts(k.get("required")),
            forbidden=forbidden, abstain_reason=k.get("abstain_reason"),
            restricted_procedures=tuple([r["procedure"]] if r.get("procedure") else []),
            restricted_missing=tuple(r.get("missing") or ()),
            reference=q["reference_answer"])
    cases = list(golden.values())
    for procedure, items in pairs.items():
        for item in items:
            if item.get("from", "").startswith("golden ") and item["id"] in golden:
                g = golden[item["id"]]
                cases[cases.index(g)] = Case(**{**g.__dict__, "procedure": procedure,
                                                "certified": item["certified"]})
                continue
            outcomes = _outcomes(item["outcome"])
            cases.append(Case(
                id=item["id"], kind="pair", user_id=item["user"], question=item["question"],
                outcomes=outcomes, required=_facts(item.get("required")),
                forbidden=_facts(item.get("forbidden")),
                restricted_procedures=tuple(item.get("restricted_procedures") or [procedure]),
                procedure=procedure, certified="answer" in outcomes and len(outcomes) == 1,
                previous=item.get("previous"), source=item.get("from")))
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return cases
