from dataclasses import dataclass
from functools import lru_cache
from os import environ
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


@dataclass(frozen=True)
class Settings:
    database_url: str
    corpus_dir: Path
    data_dir: Path
    acl_path: Path
    users_path: Path
    openai_api_key: str | None
    llm_model_fast: str
    llm_model_strong: str
    vision_model: str
    embedding_model: str
    embedding_dims: int


def _path(value: str) -> Path:
    """Relative paths resolve against the project root, not the working directory."""
    p = Path(value)
    return p if p.is_absolute() else PROJECT_ROOT / p


@lru_cache
def get_settings() -> Settings:
    """Settings from the environment and `.env`, read once and cached for the process. The
    permissions and users files default to siblings of the corpus directory."""
    load_dotenv(PROJECT_ROOT / ".env")
    corpus = _path(environ.get("CORPUS_DIR", "corpus"))
    return Settings(
        database_url=environ.get("DATABASE_URL", "postgresql:///copilot"),
        corpus_dir=corpus,
        data_dir=_path(environ.get("DATA_DIR", "data")),
        acl_path=_path(environ.get("ACL_PATH", str(corpus.parent / "permissions.json"))),
        users_path=_path(environ.get("USERS_PATH", str(corpus.parent / "users.json"))),
        openai_api_key=environ.get("OPENAI_API_KEY") or None,
        llm_model_fast=environ.get("LLM_MODEL_FAST", ""),
        llm_model_strong=environ.get("LLM_MODEL_STRONG", ""),
        vision_model=environ.get("VISION_MODEL", ""),
        embedding_model=environ.get("EMBEDDING_MODEL", "text-embedding-3-large"),
        embedding_dims=int(environ.get("EMBEDDING_DIMS", "1024")),
    )
