"""Failure categories (FR-007, SC-002): exactly one per failure, decided by code.

| Category | Meaning |
|---|---|
| ingestion | the fact is in no passage the user can see (the corpus can't support it) |
| retrieval | the fact is in a passage the user can see, but not in any cited passage |
| applicability | evidence for another model, serial, site or revision, or the wrong machine |
| generation | the fact is in a cited passage but the answer doesn't state it, or wrong wording |
| citation | a cited passage doesn't exist or doesn't hold the sentence's values |
| policy | access or restricted-procedure rules broken: disclosure, hidden citation, wrong outcome |
"""
from dataclasses import dataclass

from copilot_eval.facts import Fact, in_text

CATEGORIES = ("ingestion", "retrieval", "applicability", "generation", "citation", "policy")


@dataclass(frozen=True)
class Failure:
    case_id: str
    check: str
    """outcome, fact, forbidden, citation, disclosure, grid."""
    category: str
    blocking: bool
    detail: str
    evidence: str = ""

    def __post_init__(self) -> None:
        """Reject a category outside CATEGORIES."""
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown category {self.category!r}")


def missed_fact(fact: Fact, cited: dict[str, str], visible: dict[str, str]) -> tuple[str, str]:
    """Category and evidence for a required fact the response doesn't state."""
    if fact.category:
        return fact.category, "category set in the key facts file"
    if fact.where in ("work_order", "restricted", "asset"):
        return "generation", f"not in the response's {fact.where.replace('_', ' ')}"
    if fact.where == "sources":
        return "retrieval", "no cited source matches"
    for pid, text in cited.items():
        if in_text(fact, text):
            return "generation", f"stated in cited passage {pid}"
    for pid, text in visible.items():
        if in_text(fact, text):
            return "retrieval", f"in visible passage {pid}, which was not cited"
    return "ingestion", "in no passage visible to this user"


def outcome(expected: tuple[str, ...], actual: str, fact_in_visible: bool) -> str:
    """Category of an outcome mismatch."""
    if "restricted" in expected or actual == "restricted":
        return "policy"
    if "clarify" in expected or actual == "clarify":
        return "applicability"
    if "abstain" in expected:
        return "applicability"  # answered where no permitted source exists: a substitute was used
    return "retrieval" if fact_in_visible else "ingestion"
