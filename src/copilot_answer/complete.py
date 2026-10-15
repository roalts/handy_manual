"""Completeness pass (research R19): what the cited passages state that the answer leaves out.

Code lists the candidates; one model call decides which a technician needs and writes them.
Candidates are identifiers (cases, parts, serials, fault codes, bulletins, procedures, campaigns,
tags), values with units, calendar dates, and conditional branches ("if …, …"). An item counts as
present when the answer already holds it: identifiers and values as the citation check matches
them, branches when most of their content words are in one answer sentence.
"""
import re
from dataclasses import dataclass

from copilot_answer.ids import recognize
from copilot_answer.validate import (
    VALUE,
    Grounding,
    _has_ident,
    checkable,
    date_grounded,
    dates,
    ident_norm,
    value_grounded,
)

BRANCH = re.compile(r"\b(?:if|unless)\b[^.;:!?]{3,}?,\s*\S", re.I)
_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_WORD = re.compile(r"[a-z][a-z0-9\-]{3,}")
_STOP = frozenset("""
    about above after again also always before being below between both cannot could does done
    each either every from have here into just more must need never once only other over same
    shall should some such than that their them then there these they this those through under
    unit until very were what when where which while will with within without would your
    """.split())
BRANCH_COVERED = 0.6
BRANCH_MAX_CHARS = 300
REPEAT_COVERED = 0.8


@dataclass(frozen=True)
class Item:
    kind: str  # identifier | value | date | branch
    text: str
    label: str


def _words(text: str) -> set[str]:
    """Content words of four or more characters, without stopwords."""
    return {w for w in _WORD.findall(text.casefold()) if w not in _STOP}


def _branch_sentences(text: str) -> list[str]:
    """Conditional sentences ("if …, …") with at least three content words, truncated."""
    out = []
    for s in _SPLIT.split(text):
        s = s.strip(" -•*\t")
        if BRANCH.search(s) and len(_words(s)) >= 3:
            out.append(s[:BRANCH_MAX_CHARS])
    return out


def missing(answer: list[str], cited: dict[str, str], limit: int,
            question: str = "") -> list[Item]:
    """Items in the cited passages (`label -> English text`, in citation order) that the answer
    sentences don't hold; branches first, then identifiers, dates and values; at most `limit`.
    Fault codes the question doesn't name are left out (fault tables list every other code)."""
    asked = {ident_norm(f) for f in recognize(question).fault_codes}
    whole = "\n".join(answer)
    g = Grounding(whole)
    answer_words = [_words(s) for s in answer]
    seen: set[str] = set()
    branches, idents, when, values = [], [], [], []
    for lab, text in cited.items():
        for s in _branch_sentences(text):
            words = _words(s)
            best = max((len(words & w) / len(words) for w in answer_words), default=0.0)
            key = "b:" + " ".join(sorted(words))
            if best < BRANCH_COVERED and key not in seen:
                seen.add(key)
                branches.append(Item("branch", s, lab))
        _, ids, _ = checkable(text)
        faults = {ident_norm(f) for f in recognize(text).fault_codes} - asked
        for i in ids:
            if ident_norm(i) in faults:
                continue
            key = "i:" + ident_norm(i)
            if key not in seen and not _has_ident(ident_norm(i), g.idents):
                seen.add(key)
                idents.append(Item("identifier", i, lab))
        for y, m, d in dates(text):
            key = f"d:{y}-{m:02d}-{d:02d}"
            if key not in seen and not date_grounded(y, m, d, g.values):
                seen.add(key)
                when.append(Item("date", f"{y}-{m:02d}-{d:02d}", lab))
        for v in (m.group(0) for m in VALUE.finditer(text)):
            key = "v:" + v.casefold()
            if key not in seen and not value_grounded(v, g):
                seen.add(key)
                values.append(Item("value", v, lab))
    return [*branches, *idents, *when, *values][:limit]


def names_any(text: str, procedures: list[str]) -> bool:
    """True when `text` names one of `procedures` (IDs such as "SOP-020"). A sentence routing work
    to a restricted procedure tends to restate that procedure's own steps from the visible
    passages that point to it, so additions naming one the user can't satisfy are not kept."""
    hay = ident_norm(text)
    return any(_has_ident(ident_norm(p), hay) for p in procedures)


def repeats(text: str, others: list[str]) -> bool:
    """True when one of `others` already holds most of `text`'s content words."""
    words = _words(text)
    return bool(words) and any(len(words & _words(o)) / len(words) >= REPEAT_COVERED
                               for o in others)
