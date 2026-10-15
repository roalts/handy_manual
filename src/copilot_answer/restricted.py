"""Restricted procedures as safety controls (Principle V, FR-014..016, research R5)."""
import re
from dataclasses import dataclass

from copilot_answer.serving import ProcedureAlt
from copilot_answer.validate import norm


@dataclass(frozen=True)
class Unsatisfied:
    name: str
    title: str
    missing_groups: tuple[str, ...]


def unsatisfied(procs: list[ProcedureAlt], groups: frozenset[str]) -> dict[str, Unsatisfied]:
    """Procedures none of whose access alternatives the user satisfies, with the smallest set of
    groups they would need."""
    by_name: dict[str, list[ProcedureAlt]] = {}
    for p in procs:
        by_name.setdefault(p.name, []).append(p)
    out = {}
    for name, alts in by_name.items():
        if any(a.required_groups <= groups for a in alts):
            continue
        best = min(alts, key=lambda a: (len(a.required_groups - groups), sorted(a.required_groups)))
        out[name] = Unsatisfied(name, best.title, tuple(sorted(best.required_groups - groups)))
    return out


def names_in(text: str, names: list[str]) -> list[str]:
    """Procedure names in `text`, tolerant of case, hyphens and spaces ("hv proc 07")."""
    out = []
    for n in names:
        parts = re.findall(r"[a-z]+|\d+", n.casefold())
        pattern = r"[\s\-_]?".join(re.escape(x) for x in parts)
        if re.search(rf"(?<![a-z0-9]){pattern}(?![0-9])", text.casefold()):
            out.append(n)
    return out


HOW_TO = re.compile(r"\bhow (do|can|should|would|could|to)\b|\b(steps?|procedure for|"
                    r"instructions|walk me through|tell me how|explain how|show me how|"
                    r"what (do|should) i do)\b", re.I)
_STOP = {"a", "an", "and", "at", "for", "in", "of", "on", "the", "to", "with"}


def terms(text: str) -> set[str]:
    """Content words for scope matching: plural "s" dropped, cut to five letters ("isolate" and
    "isolation" meet); identifiers with digits ("VRS-110") kept whole."""
    out = set()
    for w in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.casefold()):
        if w in _STOP:
            continue
        if any(ch.isdigit() for ch in w):
            out.add(w)
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w[:5])
    return out


def scope_terms(u: Unsatisfied) -> set[str]:
    """What the procedure covers, from its published title without its name
    ("CS-PROC-03 Confined Space Entry, Pump Pits" gives confined, space, entry, pump, pit)."""
    return terms(re.sub(re.escape(u.name), " ", u.title, flags=re.I))


def covering(question: str, procedures: dict[str, Unsatisfied],
             min_terms: int) -> Unsatisfied | None:
    """The unsatisfied procedure covering the work a how-to question asks about: at least
    `min_terms` of its scope terms are in the question; the most terms wins, then the larger share
    of its scope, then the name. None when the question doesn't ask how to do something."""
    if not HOW_TO.search(question):
        return None
    asked = terms(question)
    ranked = []
    for name, u in procedures.items():
        scope = scope_terms(u)
        hit = len(scope & asked)
        if scope and hit >= min_terms:
            ranked.append((-hit, -hit / len(scope), name))
    return procedures[min(ranked)[2]] if ranked else None


def marker_hits(text: str, markers: tuple[str, ...]) -> list[str]:
    """Markers in `text` after value normalization, not inside a longer token."""
    hay = norm(text)
    hits = []
    for m in markers:
        tok = norm(m)
        if re.search(rf"(?<![a-z0-9.]){re.escape(tok)}(?![0-9])", hay):
            hits.append(m)
    return hits


def guard(text: str, procedures: list[str], markers: dict[str, tuple[str, ...]]) -> list[str]:
    """Markers of the given (unsatisfied) procedures present in `text`."""
    return [h for name in procedures for h in marker_hits(text, markers.get(name, ()))]
