"""Settings for the answer API, from the environment (`.env` is loaded by copilot_ingest)."""
import logging
import secrets
from dataclasses import dataclass
from os import environ
from pathlib import Path

from copilot_ingest.settings import PROJECT_ROOT, get_settings

log = logging.getLogger("copilot_api")


class StartupError(RuntimeError):
    """The server must not start with this configuration."""


@dataclass(frozen=True)
class ApiConfig:
    app_env: str
    session_secret: str
    session_max_age: int
    database_url: str
    users_path: Path
    corpus_dir: Path
    data_dir: Path
    web_dir: Path
    engine_pool: int

    @property
    def production(self) -> bool:
        """Whether APP_ENV is production: no development sign-in, secure cookies."""
        return self.app_env == "production"


def _path(value: str) -> Path:
    """`value` as a path, relative ones taken from the project root."""
    p = Path(value)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_config() -> ApiConfig:
    """Read the API settings; without SESSION_SECRET, fail in production, else use a random one."""
    s = get_settings()
    app_env = environ.get("APP_ENV", "development").strip().lower() or "development"
    secret = environ.get("SESSION_SECRET", "")
    if not secret:
        if app_env == "production":
            raise StartupError("SESSION_SECRET must be set when APP_ENV=production")
        log.warning("SESSION_SECRET is not set; using a random secret, sessions end at restart")
        secret = secrets.token_urlsafe(32)
    return ApiConfig(
        app_env=app_env,
        session_secret=secret,
        session_max_age=int(environ.get("SESSION_MAX_AGE", str(12 * 3600))),
        database_url=s.database_url,
        users_path=s.users_path,
        corpus_dir=s.corpus_dir,
        data_dir=s.data_dir,
        web_dir=_path(environ.get("WEB_DIR", "web-react/dist")),
        engine_pool=max(1, int(environ.get("ANSWER_ENGINES", "2"))),
    )
