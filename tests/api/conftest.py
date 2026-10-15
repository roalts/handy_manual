import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from copilot_api import Deps, create_app
from copilot_api.config import ApiConfig
from copilot_api.engines import EnginePool
from copilot_api.identity import Directory
from copilot_api.memory import MemoryAuditLog, MemoryWorkOrders
from copilot_api.session import Sessions
from copilot_ingest.settings import PROJECT_ROOT, get_settings
from tests.api.fakes import FakeEngine, FakeSources

REGIONS = {"FRS": "NA", "TAC": "NA", "RTM": "EU", "GDN": "EU"}


@pytest.fixture
def users_file(tmp_path) -> Path:
    """A private copy of users.json that a test may edit."""
    path = tmp_path / "users.json"
    shutil.copy(PROJECT_ROOT / "users.json", path)
    return path


@pytest.fixture
def web_dir(tmp_path) -> Path:
    """A minimal built client: index.html and one script under assets/."""
    root = tmp_path / "web"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text('<!doctype html><html><body><script type="module" '
                                     'src="/assets/app.js"></script></body></html>')
    (root / "assets" / "app.js").write_text("export const app = 1;\n" * 100)
    return root


@pytest.fixture
def config(users_file, web_dir) -> ApiConfig:
    s = get_settings()
    return ApiConfig(app_env="development", session_secret="test-secret", session_max_age=3600,
                     database_url=s.database_url, users_path=users_file,
                     corpus_dir=s.corpus_dir, data_dir=s.data_dir,
                     web_dir=web_dir, engine_pool=2)


class Harness:
    """An app over fakes, with handles to the engine, audit log and work orders."""

    def __init__(self, config: ApiConfig, engine=None, sources=None) -> None:
        self.config = config
        self.engine = engine or FakeEngine()
        self.sources = sources or FakeSources()
        self.directory = Directory(config.users_path)
        self.audit = MemoryAuditLog(self.sources.visible)
        self.work_orders = MemoryWorkOrders(
            self.directory, lambda a: REGIONS.get(a.split("-")[0]), self.sources.visible,
            self.audit, self.sources.dataset_version)
        self.sessions = Sessions(config.session_secret, config.session_max_age)
        self.app = create_app(Deps(
            config=config, directory=self.directory, sessions=self.sessions,
            engines=EnginePool(lambda: self.engine, config.engine_pool), sources=self.sources,
            work_orders=self.work_orders, audit=self.audit))

    def client(self, user_id: str | None = None) -> TestClient:
        c = TestClient(self.app, raise_server_exceptions=False)
        if user_id:
            c.cookies.set("copilot_session", self.sessions.sign(user_id))
        return c

    def events(self, kind: str | None = None):
        return [e for e in self.audit.events if kind is None or e.kind == kind]


@pytest.fixture
def harness(config) -> Harness:
    return Harness(config)


@pytest.fixture
def make_harness(config):
    def make(engine=None, sources=None, **overrides) -> Harness:
        return Harness(replace(config, **overrides), engine, sources)
    return make
