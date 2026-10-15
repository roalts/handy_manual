"""Identifier extraction and source-convention normalization (dates, decimals, statuses)."""
import re
from datetime import date, datetime
from functools import lru_cache

import yaml

from copilot_ingest.settings import CONFIG_DIR

VERSION = "normalize-1"


@lru_cache
def _patterns() -> dict[str, tuple[re.Pattern, dict]]:
    """Compiled case-insensitive identifier patterns from identifiers.yaml, loaded once."""
    cfg = yaml.safe_load((CONFIG_DIR / "identifiers.yaml").read_text())
    return {name: (re.compile(spec["pattern"], re.I), spec) for name, spec in cfg.items()}


def _canonical(name: str, m: re.Match, spec: dict) -> str:
    """Upper-case canonical form of a match: a configured group, MODEL-NNN, or the match
    without spaces."""
    if "group" in spec:
        return m.group(spec["group"]).upper()
    if spec.get("canonical") == "model":
        return f"{m.group(1).upper()}-{m.group(2)}"
    return m.group(0).upper().replace(" ", "")


def find(name: str, text: str) -> list[str]:
    """Distinct canonical matches of one identifier kind, in order of first appearance."""
    pattern, spec = _patterns()[name]
    seen: dict[str, None] = {}
    for m in pattern.finditer(text or ""):
        seen[_canonical(name, m, spec)] = None
    return list(seen)


def identifiers(text: str) -> dict[str, list[str]]:
    """Canonical identifiers found in text. Original text is never rewritten."""
    serials = find("serial", text)
    # a serial such as VRS110-230877 also contains a model code; record both
    models = dict.fromkeys(find("model", text))
    for s in serials:
        m = re.match(r"([A-Z]+)(\d+)-", s)
        if m:
            models[f"{m.group(1)}-{m.group(2)}"] = None
    # month-year values ("05-2016") have the part-number shape
    parts = [p for p in find("part_number", text)
             if not (int(p[:2]) <= 12 and 1990 <= int(p[3:]) <= 2035)]
    return {
        "fault_codes": find("fault_code", text),
        "part_numbers": parts,
        "asset_ids": find("asset_id", text),
        "legacy_asset_ids": find("legacy_asset_id", text),
        "serials": serials,
        "case_numbers": find("case_number", text),
        "models": list(models),
        "bulletins": find("bulletin_id", text),
    }


# --- source conventions -------------------------------------------------------------------

class ConventionError(ValueError):
    pass


def parse_date(value: str, fmt: str) -> date | None:
    """Parse with the source's declared format only; a value that does not fit is an error."""
    value = (value or "").strip()
    if not value:
        return None
    if fmt == "iso8601":
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("+0000", "+00:00")
                                      ).date()
    try:
        return datetime.strptime(value, fmt).date()
    except ValueError as e:
        raise ConventionError(f"{value!r} does not match declared format {fmt}") from e


def parse_number(value: str, decimal: str = ".") -> float | None:
    """Parse with the source's decimal separator, dropping the other as a thousands separator.
    Empty is None; anything else unparseable is a ConventionError."""
    value = (value or "").strip()
    if not value:
        return None
    if decimal == ",":
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", "")
    try:
        return float(value)
    except ValueError as e:
        raise ConventionError(f"{value!r} is not a number") from e


def map_value(value: str, mapping: dict[str, str], what: str) -> str:
    """The mapped value for a source code; an unmapped value is a ConventionError."""
    value = (value or "").strip()
    if value in mapping:
        return mapping[value]
    raise ConventionError(f"unmapped {what} {value!r}")
