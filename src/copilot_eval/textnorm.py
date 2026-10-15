"""Text normalization shared by key-fact matching and the citation value check.

Deliberately independent of the engine's validator: the harness must catch what the engine
misses, so it does not reuse the engine's notion of "the same value".
"""
import re
import unicodedata

_DASHES = re.compile(r"[\u2010-\u2015\u2212]")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_UNIT_SPELLINGS = [
    (re.compile(r"(?<=\d)\s*n\s*[-·⋅.]?\s*m\b"), " n-m"),
    (re.compile(r"\bnm\b"), "n-m"),
    (re.compile(r"(?<=\d)\s*(?:mω|megohms?|m\s?ohms?)\b"), " mohm"),
    (re.compile(r"(?<=\d)\s*°\s*c\b"), " c"),
    (re.compile(r"(?<=\d)\s+%"), "%"),
    (re.compile(r"(?<=\d)(?=(?:mm|bar|kg|mohm|ppm|v|a|h|s|min)\b)"), " "),
]
_SPACE = re.compile(r"\s+")


_ISO_TIME = re.compile(r"(\d{4}-\d{2}-\d{2})t(\d)")


def norm(text: str) -> str:
    """Case-folded, dash- and unit-normalized text with single spaces."""
    s = unicodedata.normalize("NFKC", text).casefold()
    s = _DASHES.sub("-", s)
    s = _THOUSANDS.sub("", s)
    s = _ISO_TIME.sub(r"\1 \2", s)
    for pattern, repl in _UNIT_SPELLINGS:
        s = pattern.sub(repl, s)
    return _SPACE.sub(" ", s).strip()


_DECIMAL_COMMA = re.compile(r"(?<![\d/.,])(\d+),(\d{1,3})(?![\d,/])")


def decimal_comma(normed: str) -> str:
    """A decimal comma read as a decimal point ("3,3 bar" -> "3.3 bar"), for normalized passage
    text only (user decision, 2026-10-14 23:10). `norm` has already removed thousands
    separators, so "4,000 h" is "4000 h" here and never becomes "4.0 h"; digits that are part of
    a list ("1,2,3") or a date ("7/28,8/30") are left alone."""
    return _DECIMAL_COMMA.sub(r"\1.\2", normed)


def contains(haystack_norm: str, needle: str) -> bool:
    """`needle` (raw) occurs in normalized `haystack_norm` as a whole token sequence: "8.3" does
    not match "18.3" or "8.35", "TP1" does not match "TP10". A word needle also matches its
    plural ("wear ring" matches "wear rings")."""
    n = norm(needle)
    if not n:
        return False
    left = r"(?<![\w.])" if n[0].isalnum() else ""
    plural = "(?:s|es)?" if re.search(r"[a-z]{3}$", n) else ""
    right = r"(?![\w]|\.\d)" if n[-1].isalnum() else ""
    return re.search(left + re.escape(n) + plural + right, haystack_norm) is not None
