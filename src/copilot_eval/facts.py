"""Deterministic key-fact matching (FR-002, FR-003).

A fact is a list of terms that must all occur in one text unit of the response (one sentence,
one conflict, one notice, the work-order suggestion, ...). A term may list alternatives
separated by " | ". Matching is by value and identifier after normalization, never by model.
"""
from dataclasses import dataclass, field

from copilot_contracts import AnswerResponse
from copilot_eval.textnorm import contains, norm

SCOPES = ("text", "sources", "work_order", "restricted", "asset", "any")


@dataclass(frozen=True)
class Fact:
    fact: str
    """The fact in words, as the reviewer reads it."""
    all: tuple[tuple[str, ...], ...]
    """Terms; each term is a tuple of alternatives."""
    where: str = "text"
    category: str | None = None
    """Category hint used when this fact fails (forbidden facts must have one)."""

    @classmethod
    def parse(cls, raw: dict) -> "Fact":
        """Fact from its key-facts entry; ValueError on an unknown scope or an empty term."""
        terms = tuple(tuple(a.strip() for a in str(t).split(" | ") if a.strip())
                      for t in raw["all"])
        where = raw.get("where", "text")
        if where not in SCOPES:
            raise ValueError(f"unknown scope {where!r} in fact {raw['fact']!r}")
        if not terms or any(not t for t in terms):
            raise ValueError(f"fact {raw['fact']!r} has an empty term")
        return cls(raw["fact"], terms, where, raw.get("category"))


@dataclass(frozen=True)
class Unit:
    scope: str
    label: str
    text: str


@dataclass
class FactResult:
    fact: Fact
    hit: bool
    evidence: str | None = None
    missing_terms: list[str] = field(default_factory=list)


def _segments_text(segments) -> str:
    """Sentence text, each unverified scanned value replaced by a pointer to its page."""
    return "".join(s.text if s.kind == "text" else f"[value unverified, see scanned page {s.page}]"
                   for s in segments)


def units(resp: AnswerResponse) -> list[Unit]:
    """Every piece of the response a technician reads, labelled by where it is."""
    out: list[Unit] = []
    for i, s in enumerate(resp.sentences, 1):
        out.append(Unit("text", f"sentence {i}", _segments_text(s.segments)))
    for i, c in enumerate(resp.conflicts, 1):
        sides = " / ".join(side.statement for side in c.sides)
        out.append(Unit("text", f"conflict {i}", f"{c.topic}: {sides}"))
    for n in resp.notices:
        out.append(Unit("text", f"notice {n.kind}", n.text))
    if resp.clarification:
        opts = "; ".join(o.label + (f" ({o.question})" if o.question else "")
                         for o in resp.clarification.options)
        out.append(Unit("text", "clarification", f"{resp.clarification.question} {opts}"))
    if resp.restricted:
        r = resp.restricted
        out.append(Unit("restricted", "restricted",
                        f"{r.procedure} missing {' '.join(r.missing_groups)}"))
    if w := resp.work_order_suggestion:
        parts = " ".join(f"{p.part_number} x{p.quantity}" for p in w.parts)
        out.append(Unit("work_order", "work order",
                        f"asset {w.asset_id or '-'}; fault {w.fault_code or '-'}; certification "
                        f"{' '.join(w.required_certification) or '-'}; parts {parts or '-'}; "
                        f"campaign {w.campaign_code or '-'}; {w.summary}"))
    if a := resp.asset:
        out.append(Unit("asset", "asset", f"{a.asset_id} {a.model} {a.serial} "
                        f"firmware {a.firmware or '-'} {a.site} {a.site_name}"))
    for c in resp.citations.values():
        out.append(Unit("sources", f"source {c.title}",
                        f"{c.title}; {c.locator}; revision {c.revision or '-'}; "
                        f"{c.issue_date or ''}{'; scanned' if c.ocr else ''}"
                        f"{'; machine translated' if c.translated else ''}"
                        f"{'; superseded' if c.superseded else ''}"))
    return out


def match(fact: Fact, resp_units: list[Unit]) -> FactResult:
    """Hit on the first unit in the fact's scope holding every term; on a miss, the missing terms
    of the closest unit."""
    pool = [u for u in resp_units if fact.where == "any" or u.scope == fact.where]
    best_missing: list[str] | None = None
    for u in pool:
        hay = norm(u.text)
        missing = [t[0] for t in fact.all if not any(contains(hay, alt) for alt in t)]
        if not missing:
            return FactResult(fact, True, f"{u.label}: {u.text}")
        if best_missing is None or len(missing) < len(best_missing):
            best_missing = missing
    return FactResult(fact, False, None, best_missing or [t[0] for t in fact.all])


def in_text(fact: Fact, text: str) -> bool:
    """All terms of `fact` in one passage text (used to place a missed fact in a stage)."""
    hay = norm(text)
    return all(any(contains(hay, alt) for alt in t) for t in fact.all)
