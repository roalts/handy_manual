from pathlib import Path

import yaml

from copilot_ingest.artifacts import load_artifact, save_artifact
from copilot_ingest.models import ExtractResult
from copilot_ingest.settings import CONFIG_DIR
from copilot_ingest.stages.extract import docx as docx_x
from copilot_ingest.stages.extract import html as html_x
from copilot_ingest.stages.extract import messages as msg_x
from copilot_ingest.stages.extract import pdf as pdf_x
from copilot_ingest.stages.extract import tabular as tab_x


class UnsupportedFormat(ValueError):
    pass


def _sources_cfg() -> dict:
    """Source conventions from `sources.yaml`, re-read on every call."""
    return yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text())


def tabular_source_for(rel_path: str) -> str | None:
    """Name of the configured source whose `path` is exactly `rel_path`, or None."""
    for name, cfg in _sources_cfg().items():
        if cfg.get("path") == rel_path:
            return name
    return None


def choose(rel_path: str) -> tuple[str, str, object]:
    """Return (extractor name, version, callable(path, rel, fp))."""
    p = Path(rel_path)
    ext = p.suffix.lower()
    top = p.parts[0] if p.parts else ""
    if ext == ".pdf" and top == "email":
        return "pdf_thread", msg_x.VERSION, msg_x.extract_pdf_thread
    if ext == ".pdf":
        return "pdf", pdf_x.VERSION, pdf_x.extract
    if ext == ".docx":
        return "docx", docx_x.VERSION, docx_x.extract
    if ext in (".html", ".htm"):
        return "html", html_x.VERSION, html_x.extract
    if ext == ".eml":
        return "eml", msg_x.VERSION, msg_x.extract_eml
    if ext == ".json" and top == "chat":
        return "teams", msg_x.VERSION, msg_x.extract_teams
    if ext == ".json" and "salesforce" in p.name:
        return "salesforce", msg_x.VERSION, msg_x.extract_salesforce
    if ext == ".csv":
        source = tabular_source_for(rel_path)
        if source is None:
            raise UnsupportedFormat(f"no source convention configured for {rel_path}")
        cfg = _sources_cfg()[source]
        return ("tabular", tab_x.VERSION,
                lambda path, rel, fp: tab_x.extract(path, rel, fp, cfg))
    raise UnsupportedFormat(f"no extractor for {rel_path}")


def extract_file(abs_path: Path, rel_path: str, fingerprint: str,
                 force: bool = False) -> tuple[ExtractResult, bool]:
    """Extract one file, reusing the stored artifact when the fingerprint and version match
    (unless `force`). Returns (result, from_cache).
    """
    name, version, fn = choose(rel_path)
    stage = f"extract-{name}"
    cached = None if force else load_artifact(fingerprint, stage, version, ExtractResult)
    if cached is not None:
        cached.path = rel_path
        return cached, True
    result = fn(abs_path, rel_path, fingerprint)
    save_artifact(fingerprint, stage, version, result)
    return result, False
