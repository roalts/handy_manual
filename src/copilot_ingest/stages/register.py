from dataclasses import dataclass, field
from pathlib import Path

from copilot_ingest.acl import AccessRules
from copilot_ingest.artifacts import copy_raw
from copilot_ingest.ids import file_fingerprint
from copilot_ingest.models import QuarantineRecord, SourceFile
from copilot_ingest.stages.extract import UnsupportedFormat, choose

IGNORED_NAMES = {".DS_Store", "Thumbs.db"}


@dataclass
class Registration:
    files: list[SourceFile] = field(default_factory=list)
    quarantine: list[QuarantineRecord] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    acl_without_file: list[str] = field(default_factory=list)

    @property
    def active(self) -> list[SourceFile]:
        """Files not quarantined."""
        return [f for f in self.files if f.status == "active"]


def _walk(corpus: Path) -> list[Path]:
    """Corpus files in path order, skipping OS metadata files and Office lock files (~$)."""
    return sorted(p for p in corpus.rglob("*")
                  if p.is_file() and p.name not in IGNORED_NAMES and not p.name.startswith("~$"))


def register(corpus: Path, rules: AccessRules, previous: dict[str, str | None]) -> Registration:
    """Register every corpus file. `previous` maps path -> fingerprint from the last run."""
    reg = Registration()
    seen: set[str] = set()
    for p in _walk(corpus):
        rel = str(p.relative_to(corpus))
        seen.add(rel)
        size = p.stat().st_size
        fp = file_fingerprint(p) if size else None
        required = rules.required_groups(rel)
        sf = SourceFile(path=rel, fingerprint=fp, size_bytes=size,
                        source_system=rules.source_systems.get(rel), required_groups=required)

        reason, detail = None, ""
        if required is None:
            reason, detail = "no_access_rule", "path not present in the access rules file"
        elif rules.unknown_groups(rel):
            reason, detail = "unknown_group", f"undefined groups {rules.unknown_groups(rel)}"
        elif size == 0:
            reason, detail = "empty_file", "file has zero bytes"
        else:
            try:
                choose(rel)
            except UnsupportedFormat as e:
                reason, detail = "unsupported_format", str(e)

        if reason:
            sf.status = "quarantined"
            reg.quarantine.append(QuarantineRecord(path=rel, stage="register", reason=reason,
                                                   detail=detail))
        else:
            copy_raw(p, fp)

        if rel not in previous:
            reg.added.append(rel)
        elif previous[rel] != fp:
            reg.changed.append(rel)
        else:
            sf.changed = False
        reg.files.append(sf)

    reg.removed = sorted(set(previous) - seen)
    reg.acl_without_file = sorted(set(rules.documents) - seen)
    return reg
