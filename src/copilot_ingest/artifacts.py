import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from copilot_ingest.settings import get_settings


def data_dir() -> Path:
    """Root of all pipeline output (DATA_DIR, default `data/`)."""
    return get_settings().data_dir


def artifact_path(fingerprint: str, stage: str, version: str) -> Path:
    """Cache file for one stage's output on one source file. Bumping a stage's version
    points at a new file, so stale results are never reused."""
    return data_dir() / "artifacts" / fingerprint / f"{stage}@{version}.json"


def load_artifact[M: BaseModel](fingerprint: str, stage: str, version: str,
                                model: type[M]) -> M | None:
    """Cached stage output parsed as `model`, or None if that stage has not run on this file."""
    path = artifact_path(fingerprint, stage, version)
    if not path.exists():
        return None
    return model.model_validate_json(path.read_text())


def save_artifact(fingerprint: str, stage: str, version: str, obj: BaseModel) -> Path:
    """Write stage output via a temp file and rename, so an interrupted run never leaves a
    half-written artifact that a later run would load."""
    path = artifact_path(fingerprint, stage, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(obj.model_dump_json(indent=1))
    tmp.replace(path)
    return path


def save_json(path: Path, obj) -> None:
    """Write plain JSON (reports and similar); non-JSON values such as dates become strings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str, ensure_ascii=False))


def copy_raw(src: Path, fingerprint: str) -> Path:
    """Keep a copy of the source file named by its content fingerprint. Skipped if already
    copied, since the same fingerprint means the same bytes."""
    dest = data_dir() / "raw" / f"{fingerprint}{src.suffix.lower()}"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return dest
