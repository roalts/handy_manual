"""Answer API (feature 003): the HTTP server between the phone client and the answer engine."""
import logging

import psycopg

from copilot_api.app import Deps, create_app
from copilot_api.config import ApiConfig, StartupError, load_config
from copilot_api.engines import EnginePool
from copilot_api.identity import Directory
from copilot_api.memory import MemoryAuditLog, MemoryWorkOrders
from copilot_api.session import Sessions
from copilot_api.sources import SourceStore

log = logging.getLogger("copilot_api")

__all__ = ["Deps", "StartupError", "build_app", "create_app"]


def _work_orders(cfg: ApiConfig, directory: Directory, sources: SourceStore):
    """(work orders, audit log) from copilot_workorders, after migrating its schema.
    Without the package, in-memory ones outside production; production refuses to start."""
    try:
        from copilot_workorders import build_services, migrate
    except ImportError:
        if cfg.production:
            raise StartupError("copilot_workorders is required when APP_ENV=production") from None
        log.warning("copilot_workorders not installed: using in-memory work orders and audit "
                    "log (development only, lost at restart)")
        audit = MemoryAuditLog(sources.visible)

        def region_of(asset_id: str) -> str | None:
            """The asset's region from serving.assets (a new connection per call), or None."""
            with psycopg.connect(cfg.database_url) as conn:
                row = conn.execute("SELECT region FROM serving.assets WHERE asset_id = %s",
                                   (asset_id,)).fetchone()
            return row[0] if row else None

        return MemoryWorkOrders(directory, region_of, sources.visible, audit,
                                sources.dataset_version), audit
    with psycopg.connect(cfg.database_url, autocommit=True) as conn:
        migrate(conn)
    return build_services(cfg.database_url, users_path=cfg.users_path)


def build_app(config: ApiConfig | None = None):
    """The real wiring: answer engine, serving, work orders (005) and audit log."""
    from copilot_answer import build_engine

    cfg = config or load_config()
    directory = Directory(cfg.users_path)
    sources = SourceStore(cfg.database_url, cfg.corpus_dir, cfg.data_dir,
                          known_groups=lambda: directory.groups().keys())
    work_orders, audit = _work_orders(cfg, directory, sources)
    return create_app(Deps(
        config=cfg, directory=directory,
        sessions=Sessions(cfg.session_secret, cfg.session_max_age, secure=cfg.production),
        engines=EnginePool(build_engine, cfg.engine_pool), sources=sources,
        work_orders=work_orders, audit=audit))
