"""Identifier recognition in questions and answer sentences (FR-004)."""
import re
from dataclasses import dataclass, field

# Spacing-tolerant variants of the canonical patterns in config/identifiers.yaml.
ASSET = re.compile(r"\b(FRS|TAC|RTM|GDN)[\s-]?([PCHV])[\s-]?(\d{4})\b", re.I)
LEGACY_ASSET = re.compile(r"\b(MFL|BPF)[\s-]?(KM|CP|PO|TB)[\s-]?(\d{2})\b", re.I)
SERIAL = re.compile(r"\b(HCP|VRS|NK|BX)[\s-]?(\d{2,3})[\s-](\d{6})\b", re.I)
MODEL = re.compile(r"\b(HCP|VRS|NK|BX)[\s-]?(\d{2,3})(?![\d-]*\d{6})\b", re.I)
FAULT = re.compile(r"(?<![\w-])([EPLC])[\s-]?(\d{2})\b(?![.,]\d|-\d)", re.I)
CASE = re.compile(r"\b(?:SF\s?)?(000\d{5})\b", re.I)
PART = re.compile(r"(?<![\d-])(\d{2}-\d{4})(?![\d-])")
BULLETIN = re.compile(r"\bSB[\s-]?(\d{4})[\s-](\d{3})\b", re.I)
CAMPAIGN = re.compile(r"\b(NK-C\d{2}-\d{2})\b", re.I)
PROCEDURE = re.compile(r"\b(HV|CS)[\s-]?PROC[\s-]?(\d{2})\b|\bSOP[\s-]?(\d{3})\b|"
                       r"\bKT[\s-]?WI[\s-]?(\d{2})\b|\bFS[\s-]?STD[\s-]?(\d{3})\b", re.I)


@dataclass
class Recognized:
    asset_ids: list[str] = field(default_factory=list)
    legacy_ids: list[str] = field(default_factory=list)
    serials: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    fault_codes: list[str] = field(default_factory=list)
    case_numbers: list[str] = field(default_factory=list)
    part_numbers: list[str] = field(default_factory=list)
    bulletins: list[str] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)

    def search_ids(self) -> list[str]:
        """Canonical identifiers to pass to `serving.identifier_search`."""
        out = [*self.asset_ids, *self.serials, *self.models, *self.fault_codes,
               *self.case_numbers, *self.part_numbers]
        return list(dict.fromkeys(out))


def _uniq(items) -> list[str]:
    """Items in first-seen order without duplicates."""
    return list(dict.fromkeys(items))


def canonical_procedure(m: re.Match) -> str:
    """Canonical name of a `PROCEDURE` match (upper case, hyphenated)."""
    if m.group(1):
        return f"{m.group(1).upper()}-PROC-{m.group(2)}"
    if m.group(3):
        return f"SOP-{m.group(3)}"
    if m.group(4):
        return f"KT-WI-{m.group(4)}"
    return f"FS-STD-{m.group(5)}"


def recognize(text: str) -> Recognized:
    """Canonical identifiers in `text`; fault codes skip asset and procedure IDs, part numbers
    skip serials."""
    r = Recognized()
    r.asset_ids = _uniq(f"{a.upper()}-{b.upper()}-{c}" for a, b, c in ASSET.findall(text))
    r.legacy_ids = _uniq(f"{a.upper()}-{b.upper()}{c}" for a, b, c in LEGACY_ASSET.findall(text))
    serials = SERIAL.findall(text)
    r.serials = _uniq(f"{a.upper()}{b}-{c}" for a, b, c in serials)
    r.models = _uniq([f"{a.upper()}-{b}" for a, b in MODEL.findall(text)]
                     + [f"{a.upper()}-{b}" for a, b, _ in serials])
    no_ids = PROCEDURE.sub(" ", ASSET.sub(" ", text))
    r.fault_codes = _uniq(f"{a.upper()}-{b}" for a, b in FAULT.findall(no_ids))
    r.case_numbers = _uniq(CASE.findall(text))
    r.part_numbers = _uniq(PART.findall(SERIAL.sub(" ", text)))
    r.bulletins = _uniq(f"SB-{a}-{b}" for a, b in BULLETIN.findall(text))
    r.procedures = _uniq(canonical_procedure(m) for m in PROCEDURE.finditer(text))
    return r
