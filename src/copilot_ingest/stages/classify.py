"""Deterministic document classification: type, authority tier, controlled status.

Revision and issue date are taken only from explicit document fields (controlled-document
property tables). Free-text metadata extraction with quote verification is in enrich.py.
"""
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from copilot_ingest.models import ExtractResult
from copilot_ingest.settings import CONFIG_DIR

_TABULAR_TYPES = {"fleet_register.csv": "fleet_register"}


@lru_cache
def _cfg() -> dict:
    """authority.yaml, loaded once."""
    return yaml.safe_load((CONFIG_DIR / "authority.yaml").read_text())


def doc_type_for(rel_path: str, title: str | None, source_system: str | None) -> str:
    """Document type from the first matching file-name or title rule, else the source system's
    default type, else "wiki"."""
    name = Path(rel_path).name
    if name in _TABULAR_TYPES:
        return _TABULAR_TYPES[name]
    for rule in _cfg()["type_rules"]:
        pattern = re.compile(rule["pattern"])
        if pattern.search(name) or (title and pattern.search(title)):
            return rule["doc_type"]
    return _cfg()["source_system_types"].get(source_system or "", "wiki")


def authority_tier(doc_type: str) -> int:
    """Configured authority tier for a document type; KeyError if the type has none."""
    return _cfg()["tiers"][doc_type]


def is_controlled(doc_type: str) -> bool:
    """Whether documents of this type are controlled documents."""
    return doc_type in _cfg()["controlled_types"]


def source_rank(source_system: str | None) -> int:
    """Position in the configured source-system ranking (lower wins); unranked systems last."""
    rank = _cfg().get("source_system_rank", [])
    return rank.index(source_system) if source_system in rank else len(rank)


def certification_groups() -> list[str]:
    """Permission groups that represent technician certifications."""
    return list(_cfg()["certification_groups"])


_REV_KEYS = ("Revision", "Versie / Version", "Version", "Rev.")
_DATE_KEYS = ("Effective date", "Datum / Date", "Date")


def _parse_doc_date(value: str) -> date | None:
    """Date from YYYY-MM-DD (prefix) or DD-MM-YYYY, or None for any other form."""
    value = value.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})$", value)  # EU documents: DD-MM-YYYY
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def document_properties(result: ExtractResult) -> dict:
    """Revision and date from an explicit property table, when the document has one."""
    props = result.flags.get("doc_properties") or {}
    revision = next((props[k].strip() for k in _REV_KEYS if props.get(k)), None)
    issued = next((_parse_doc_date(props[k]) for k in _DATE_KEYS if props.get(k)), None)
    return {"revision": revision, "issue_date": issued}
