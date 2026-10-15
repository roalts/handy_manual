import hashlib
import re
import unicodedata
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 digest of `data`."""
    return hashlib.sha256(data).hexdigest()


def file_fingerprint(path: Path) -> str:
    """Content hash of a file; same bytes give the same fingerprint wherever the file lives."""
    return sha256_bytes(path.read_bytes())


def short_hash(*parts: str, length: int = 24) -> str:
    """Truncated SHA-256 of the parts, joined with a unit separator so ("ab", "c") and
    ("a", "bc") hash differently."""
    h = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
    return h[:length]


_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalization used for IDs, duplicate detection, and quote verification."""
    text = unicodedata.normalize("NFKC", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    return _WS.sub(" ", text).strip().casefold()


def doc_id_for(full_text: str) -> str:
    """Document ID from normalized text, so a re-saved copy of the same content keeps its ID."""
    return "doc_" + short_hash(normalize_text(full_text))


def passage_id_for(doc_id: str, anchor_key: str, text: str) -> str:
    """Passage ID from document, anchor and normalized text."""
    return "p_" + short_hash(doc_id, anchor_key, normalize_text(text))


def review_item_id(fingerprint: str, stage: str, anchor_key: str, field: str) -> str:
    """Review item ID; includes the source fingerprint, so a changed file raises a new item."""
    return "r_" + short_hash(fingerprint, stage, anchor_key, field, length=16)


def event_id_for(system: str, record_id: str) -> str:
    """Service event ID from source system and that system's record ID."""
    return "e_" + short_hash(system, record_id, length=16)
