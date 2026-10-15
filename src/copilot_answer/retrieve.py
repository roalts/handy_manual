"""Hybrid retrieval through the serving functions, fused by reciprocal rank (research R1)."""
import re

from copilot_answer import config
from copilot_answer.serving import Passage, Serving

STOPWORDS = set("""
a an and are as at be been but by can do does did for from had has have how i i'm i've if in into
is it its it's me my of on or our should so that the their them then there these they this to up
us was we what when where which who why will with would you your any about again just keeps keep
know known tell please show give get got there's what's whats yes no not also than too very
""".split())

_WORD = re.compile(r"[\w][\w.\-/]*", re.U)


def keyword_query(question: str, ids: list[str]) -> str:
    """OR query of the question's content words plus the identifiers."""
    words = []
    for w in _WORD.findall(question.casefold()):
        w = w.strip(".-/")
        if len(w) < 3 and not any(c.isdigit() for c in w):
            continue
        if w in STOPWORDS:
            continue
        words.append(w)
    words += [i.casefold() for i in ids]
    return " OR ".join(dict.fromkeys(words))


def rrf(rankings: dict[str, list[str]]) -> dict[str, float]:
    """Weighted reciprocal-rank fusion of each retriever's ranking."""
    scores: dict[str, float] = {}
    for name, ranked in rankings.items():
        w = config.RETRIEVER_WEIGHTS[name]
        for rank, pid in enumerate(ranked):
            scores[pid] = scores.get(pid, 0.0) + w / (config.RRF_K + rank + 1)
    return scores


def retrieve(serving: Serving, groups: frozenset[str], question: str, ids: list[str],
             embedding: list[float] | None, keyword_ids: list[str] | None = None
             ) -> dict[str, float]:
    """`ids` are specific identifiers (asset, serial, codes, parts, cases); model names only
    feed the keyword query, since a model alone matches hundreds of passages equally."""
    k = config.RETRIEVE_K
    kq = keyword_query(question, keyword_ids if keyword_ids is not None else ids)
    rankings = {
        "identifier": serving.identifier_search(groups, ids, k),
        "keyword": serving.keyword_search(groups, kq, k),
        "vector": serving.vector_search(groups, embedding, k) if embedding else [],
    }
    return rrf(rankings)


def consolidate(order: list[str], passages: dict[str, Passage]) -> list[str]:
    """Give procedures whole: a parent replaces its children; two children pull in the parent."""
    children: dict[str, list[str]] = {}
    for pid in order:
        p = passages.get(pid)
        if p and p.role == "child" and p.parent_passage_id:
            children.setdefault(p.parent_passage_id, []).append(pid)
    out: list[str] = []
    for pid in order:
        p = passages.get(pid)
        if p is None:
            continue
        if p.role == "child" and p.parent_passage_id:
            parent = p.parent_passage_id
            if parent in order or len(children.get(parent, [])) >= 2:
                if parent in passages and parent not in out:
                    out.append(parent)
                continue
        if pid not in out:
            out.append(pid)
    return out
